/**
 * 聊天 store（FE-4/FE-6）：
 * - 发送走 WS 上行（user_message），本地乐观渲染用户气泡
 * - message_delta 增量 append 到当前 assistant 气泡；tool_start/finish 生成可折叠工具块
 * - error → 错误条 + 重试；运行中（message_start 至 done/error）输入禁用、发送键变取消
 * - 切会话/刷新：GET /api/chat/ls/{cid} 回放历史，进行中任务用 GET /api/tasks/{id} 补状态
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as api from '@/api'
import { isApiError } from '@/api/http'
import { useWebSocket } from '@/composables/useWebSocket'
import { useAttachmentStore } from '@/stores/attachment'
import { useConversationStore } from '@/stores/conversation'
import { useResultStore } from '@/stores/result'
import { useTaskStore } from '@/stores/task'
import type { AttachmentBrief, HistoryMessage, WsDown } from '@/types'
import { friendlyError } from '@/utils/errors'

export interface UiMessage {
  local_id: string
  message_id: number | null
  role: 'user' | 'assistant' | 'tool'
  kind: 'text' | 'tool_call' | 'result'
  content: string
  tool_name: string | null
  tool_status: 'running' | 'success' | 'failed' | null
  tool_input_summary: string
  tool_result_summary: string
  tool_duration_ms: number | null
  tool_started_at: number | null
  task_id: number | null
  attachments: AttachmentBrief[]
  created_at: string
  streaming: boolean
}

export interface ChatError {
  code: number
  message: string
}

let localSeq = 0
const nextLocalId = () => `local-${++localSeq}`

export const useChatStore = defineStore('chat', () => {
  const taskStore = useTaskStore()
  const conversationStore = useConversationStore()

  const conversationId = ref<number | null>(null)
  const messages = ref<UiMessage[]>([])
  const loadingHistory = ref(false)
  const error = ref<ChatError | null>(null)
  const lastSent = ref<{ text: string; briefs: AttachmentBrief[] } | null>(null)

  const running = computed(() => taskStore.isRunning)

  // ---------- WS 编排 ----------

  const ws = useWebSocket(dispatch)
  const wsState = ws.state
  const networkError = ws.networkError

  function dispatch(msg: WsDown): void {
    const resultStore = useResultStore()
    const attachmentStore = useAttachmentStore()
    switch (msg.type) {
      case 'message_start':
        taskStore.onTaskStart(msg.task_id)
        error.value = null
        messages.value.push({
          local_id: nextLocalId(),
          message_id: msg.message_id,
          role: 'assistant',
          kind: 'text',
          content: '',
          tool_name: null,
          tool_status: null,
          tool_input_summary: '',
          tool_result_summary: '',
          tool_duration_ms: null,
          tool_started_at: null,
          task_id: msg.task_id,
          attachments: [],
          created_at: new Date().toISOString(),
          streaming: true,
        })
        if (conversationId.value !== null) conversationStore.touch(conversationId.value)
        break
      case 'message_delta': {
        const target = [...messages.value].reverse().find((m) => m.streaming && m.kind === 'text')
        if (target) target.content += msg.delta_text
        break
      }
      case 'tool_start':
        taskStore.onToolStart(msg.task_id, msg.tool_name, msg.tool_input_summary)
        messages.value.push({
          local_id: nextLocalId(),
          message_id: null,
          role: 'tool',
          kind: 'tool_call',
          content: '',
          tool_name: msg.tool_name,
          tool_status: 'running',
          tool_input_summary: msg.tool_input_summary,
          tool_result_summary: '',
          tool_duration_ms: null,
          tool_started_at: Date.now(),
          task_id: msg.task_id,
          attachments: [],
          created_at: new Date().toISOString(),
          streaming: false,
        })
        break
      case 'tool_finish': {
        taskStore.onToolFinish(msg.tool_name, msg.tool_status, msg.tool_result_summary)
        const target = [...messages.value]
          .reverse()
          .find((m) => m.kind === 'tool_call' && m.tool_name === msg.tool_name && m.tool_status === 'running')
        if (target) {
          target.tool_status = msg.tool_status
          target.tool_result_summary = msg.tool_result_summary
          target.tool_duration_ms = target.tool_started_at ? Date.now() - target.tool_started_at : null
        }
        break
      }
      case 'task_status':
        taskStore.onTaskStatus(msg.task_id, msg.task_status, msg.current_step)
        break
      case 'result_ready':
        messages.value.push({
          local_id: nextLocalId(),
          message_id: null,
          role: 'assistant',
          kind: 'result',
          content: '归因分析报告已生成',
          tool_name: null,
          tool_status: null,
          tool_input_summary: '',
          tool_result_summary: '',
          tool_duration_ms: null,
          tool_started_at: null,
          task_id: msg.task_id,
          attachments: [],
          created_at: new Date().toISOString(),
          streaming: false,
        })
        void resultStore.load(msg.task_id)
        break
      case 'error': {
        const text = friendlyError(msg.error_code, msg.error_message)
        error.value = { code: msg.error_code, message: text }
        // task_id=0 表示发送被拒（未产生任务，如 40901），仅出错误条，不动任务区
        if (msg.task_id !== 0) taskStore.onError(text)
        finalizeStreaming()
        break
      }
      case 'done':
        taskStore.onDone()
        finalizeStreaming()
        break
      case 'attachment_status':
        attachmentStore.onWsStatus(msg.attachment_id, msg.parse_status)
        break
      case 'pong':
        break
    }
  }

  function finalizeStreaming(): void {
    for (const m of messages.value) m.streaming = false
  }

  // ---------- 会话切换与历史回放 ----------

  async function switchConversation(cid: number): Promise<void> {
    if (conversationId.value === cid) return
    ws.close()
    taskStore.reset()
    useResultStore().clear()
    error.value = null
    messages.value = []
    conversationId.value = cid
    conversationStore.currentId = cid
    await loadHistory(cid)
    void ws.connect(cid)
  }

  async function loadHistory(cid: number): Promise<void> {
    loadingHistory.value = true
    try {
      const history = await api.listMessages(cid)
      messages.value = history.filter((m) => !(m.role === 'user' && !m.content)).map(mapHistoryMessage)
      useAttachmentStore().refreshFromHistory(cid, history)
      await restoreRunningTask()
    } catch (e) {
      if (isApiError(e)) error.value = { code: e.code, message: friendlyError(e.code, e.message) }
    } finally {
      loadingHistory.value = false
    }
  }

  function mapHistoryMessage(m: HistoryMessage): UiMessage {
    const base: UiMessage = {
      local_id: nextLocalId(),
      message_id: m.message_id,
      role: m.role === 'tool' ? 'tool' : m.role === 'user' ? 'user' : 'assistant',
      kind: 'text',
      content: m.content,
      tool_name: m.tool_name,
      tool_status: m.tool_status,
      tool_input_summary: '',
      tool_result_summary: '',
      tool_duration_ms: null,
      tool_started_at: null,
      task_id: m.task_id,
      attachments: m.attachments,
      created_at: m.created_at,
      streaming: false,
    }
    if (m.message_type === 'tool_call') {
      base.kind = 'tool_call'
      // 历史工具块 content 为「输入摘要\n\n结果摘要」，拆分展示
      const idx = m.content.indexOf('\n\n')
      if (idx >= 0) {
        base.tool_input_summary = m.content.slice(0, idx)
        base.tool_result_summary = m.content.slice(idx + 2)
      } else {
        base.tool_input_summary = m.content
      }
    } else if (m.message_type === 'result') {
      base.kind = 'result'
    }
    return base
  }

  /** 进行中任务补状态：取最后一条带 task_id 的消息查询任务状态 */
  async function restoreRunningTask(): Promise<void> {
    const lastWithTask = [...messages.value].reverse().find((m) => m.task_id !== null)
    if (!lastWithTask?.task_id) return
    try {
      const task = await api.getTask(lastWithTask.task_id)
      if (task.task_status === 'queued' || task.task_status === 'running') {
        taskStore.onTaskStart(task.task_id)
        taskStore.onTaskStatus(task.task_id, task.task_status, task.current_step)
      }
    } catch {
      // 任务查询失败不阻塞历史展示
    }
  }

  // ---------- 发送 / 取消 / 重试 ----------

  function send(text: string, briefs: AttachmentBrief[]): void {
    const trimmed = text.trim()
    if (!trimmed || running.value) return
    lastSent.value = { text: trimmed, briefs }
    messages.value.push({
      local_id: nextLocalId(),
      message_id: null,
      role: 'user',
      kind: 'text',
      content: trimmed,
      tool_name: null,
      tool_status: null,
      tool_input_summary: '',
      tool_result_summary: '',
      tool_duration_ms: null,
      tool_started_at: null,
      task_id: null,
      attachments: briefs,
      created_at: new Date().toISOString(),
      streaming: false,
    })
    const ok = ws.send({ type: 'user_message', text: trimmed, attachment_ids: briefs.map((b) => b.attachment_id) })
    if (!ok) {
      error.value = { code: -1, message: '连接未建立或已断开，请稍后重试' }
    }
    if (conversationId.value !== null) conversationStore.touch(conversationId.value)
  }

  function cancel(): void {
    if (taskStore.taskId !== null) {
      ws.send({ type: 'cancel', task_id: taskStore.taskId })
    }
  }

  /** 重发上一问题（错误条「重试」按钮） */
  function retry(): void {
    if (!lastSent.value || running.value) return
    error.value = null
    send(lastSent.value.text, lastSent.value.briefs)
  }

  function clearError(): void {
    error.value = null
  }

  function leaveConversation(): void {
    ws.close()
    taskStore.reset()
    messages.value = []
    conversationId.value = null
    error.value = null
  }

  /** 手动重连当前会话（网络异常提示条的「重连」按钮） */
  function reconnect(): void {
    if (conversationId.value !== null) void ws.connect(conversationId.value)
  }

  return {
    conversationId,
    messages,
    loadingHistory,
    error,
    running,
    wsState,
    networkError,
    switchConversation,
    send,
    cancel,
    retry,
    clearError,
    leaveConversation,
    reconnect,
  }
})
