/**
 * 附件 store（FE-7）：
 * - 上传（前端先校验 csv/xlsx/txt/md ≤10MB）+ axios 进度
 * - 上传完成入列表后 5s 轮询 parse_status（经 GET /api/chat/ls/{cid} 附件聚合），
 *   收到 WS attachment_status 提前停止；pending/parsing → ready/failed 可视化
 * - 删除（parsing 禁删）/ 下载（blob 保存，保留文件名）
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as api from '@/api'
import { isApiError } from '@/api/http'
import type { AttachmentBrief, HistoryMessage, ParseStatus } from '@/types'
import { saveBlob } from '@/utils/download'
import { friendlyError } from '@/utils/errors'
import { toast } from '@/utils/toast'

export const ALLOWED_EXT = ['csv', 'xlsx', 'txt', 'md']
export const MAX_SIZE = 10 * 1024 * 1024

const POLL_INTERVAL = 5000

export const useAttachmentStore = defineStore('attachment', () => {
  /** 按会话分组的附件表：conversation_id → (attachment_id → brief) */
  const byConv = ref<Record<number, Record<number, AttachmentBrief>>>({})
  /** 待发送选中的附件 chips */
  const selected = ref<AttachmentBrief[]>([])
  const uploadProgress = ref<{ fileName: string; percent: number } | null>(null)
  const drawerOpen = ref(false)

  const pollTimers = new Map<number, ReturnType<typeof setInterval>>()

  const selectedIds = computed(() => selected.value.map((s) => s.attachment_id))

  function listFor(conversationId: number | null): AttachmentBrief[] {
    if (conversationId === null) return []
    return Object.values(byConv.value[conversationId] ?? {}).sort(
      (a, b) => b.attachment_id - a.attachment_id,
    )
  }

  function upsert(conversationId: number, brief: AttachmentBrief): void {
    const map = { ...(byConv.value[conversationId] ?? {}) }
    map[brief.attachment_id] = brief
    byConv.value = { ...byConv.value, [conversationId]: map }
  }

  /** 从历史消息的附件聚合重建会话附件表 */
  function refreshFromHistory(conversationId: number, history: HistoryMessage[]): void {
    const map: Record<number, AttachmentBrief> = { ...(byConv.value[conversationId] ?? {}) }
    for (const m of history) {
      for (const a of m.attachments) map[a.attachment_id] = { ...a }
    }
    byConv.value = { ...byConv.value, [conversationId]: map }
  }

  /** 前端预校验，返回错误文案（null 为通过） */
  function validate(file: File): string | null {
    const ext = file.name.includes('.') ? file.name.split('.')!.pop()!.toLowerCase() : ''
    if (!ALLOWED_EXT.includes(ext)) return '仅支持 csv / xlsx / txt / md 格式的附件'
    if (file.size > MAX_SIZE) return '附件大小不能超过 10MB'
    return null
  }

  async function upload(conversationId: number, file: File): Promise<void> {
    const invalid = validate(file)
    if (invalid) {
      toast(invalid, 'error')
      return
    }
    uploadProgress.value = { fileName: file.name, percent: 0 }
    try {
      const resp = await api.uploadAttachment(conversationId, file, (p) => {
        if (uploadProgress.value) uploadProgress.value.percent = p
      })
      const ext = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : ''
      upsert(conversationId, {
        attachment_id: resp.attachment_id,
        file_name: resp.file_name,
        file_type: ext,
        file_size: file.size,
        parse_status: resp.parse_status,
      })
      startPolling(conversationId, resp.attachment_id)
    } catch (e) {
      toast(isApiError(e) ? friendlyError(e.code, e.message) : '上传失败，请重试', 'error')
    } finally {
      uploadProgress.value = null
    }
  }

  /** 5s 轮询解析状态，直至 ready/failed（收到 WS attachment_status 会提前停止） */
  function startPolling(conversationId: number, attachmentId: number): void {
    stopPolling(attachmentId)
    const timer = setInterval(async () => {
      try {
        const history = await api.listMessages(conversationId)
        refreshFromHistory(conversationId, history)
        const found = history.flatMap((m) => m.attachments).find((a) => a.attachment_id === attachmentId)
        if (found && (found.parse_status === 'ready' || found.parse_status === 'failed')) {
          stopPolling(attachmentId)
        }
      } catch {
        // 轮询失败静默，下个周期重试
      }
    }, POLL_INTERVAL)
    pollTimers.set(attachmentId, timer)
  }

  function stopPolling(attachmentId: number): void {
    const timer = pollTimers.get(attachmentId)
    if (timer) clearInterval(timer)
    pollTimers.delete(attachmentId)
  }

  /** WS attachment_status 下行：更新状态并停止该附件的轮询 */
  function onWsStatus(attachmentId: number, parseStatus: ParseStatus): void {
    for (const [cidStr, map] of Object.entries(byConv.value)) {
      const existing = map[attachmentId]
      if (existing) {
        upsert(Number(cidStr), { ...existing, parse_status: parseStatus })
      }
    }
    if (parseStatus === 'ready' || parseStatus === 'failed') stopPolling(attachmentId)
  }

  async function remove(conversationId: number, attachmentId: number): Promise<void> {
    try {
      await api.deleteAttachment(attachmentId)
      const map = { ...(byConv.value[conversationId] ?? {}) }
      delete map[attachmentId]
      byConv.value = { ...byConv.value, [conversationId]: map }
      selected.value = selected.value.filter((s) => s.attachment_id !== attachmentId)
      stopPolling(attachmentId)
    } catch (e) {
      toast(isApiError(e) ? friendlyError(e.code, e.message) : '删除失败', 'error')
    }
  }

  async function download(attachmentId: number): Promise<void> {
    try {
      const { blob, filename } = await api.downloadAttachment(attachmentId)
      saveBlob(blob, filename)
    } catch (e) {
      toast(isApiError(e) ? friendlyError(e.code, e.message) : '下载失败', 'error')
    }
  }

  function select(brief: AttachmentBrief): void {
    if (brief.parse_status !== 'ready') {
      toast('附件尚未解析完成，暂不能随消息发送', 'error')
      return
    }
    if (!selectedIds.value.includes(brief.attachment_id)) {
      selected.value.push(brief)
    }
  }

  function deselect(attachmentId: number): void {
    selected.value = selected.value.filter((s) => s.attachment_id !== attachmentId)
  }

  function clearSelected(): void {
    selected.value = []
  }

  function reset(): void {
    pollTimers.forEach((t) => clearInterval(t))
    pollTimers.clear()
    byConv.value = {}
    selected.value = []
    uploadProgress.value = null
  }

  return {
    byConv,
    selected,
    uploadProgress,
    drawerOpen,
    listFor,
    refreshFromHistory,
    upload,
    onWsStatus,
    remove,
    download,
    select,
    deselect,
    clearSelected,
    reset,
  }
})
