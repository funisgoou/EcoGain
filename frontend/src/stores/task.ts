/** 任务 store（FE-5）：实时任务区——五态徽标、current_step 文案、工具执行时间线 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import type { CurrentStep, TaskStatus } from '@/types'

export interface ToolTimelineItem {
  tool_name: string
  status: 'running' | 'success' | 'failed'
  started_at: number // Date.now()
  duration_ms: number | null
  input_summary: string
  result_summary: string
}

export const STEP_TEXT: Record<CurrentStep, string> = {
  planning: '规划分析路径',
  querying: '查询取证',
  summarizing: '归纳结论',
}

export const TASK_STATUS_META: Record<TaskStatus, { text: string; color: string }> = {
  queued: { text: '排队中', color: '#6b7280' },
  running: { text: '运行中', color: '#2563eb' },
  success: { text: '已完成', color: '#10b981' },
  failed: { text: '失败', color: '#ef4444' },
  cancelled: { text: '已取消', color: '#f59e0b' },
}

export const useTaskStore = defineStore('task', () => {
  const taskId = ref<number | null>(null)
  const status = ref<TaskStatus | null>(null)
  const currentStep = ref<CurrentStep | null>(null)
  const errorMessage = ref<string | null>(null)
  const tools = ref<ToolTimelineItem[]>([])
  const startedAt = ref<number | null>(null)

  const isRunning = computed(() => status.value === 'queued' || status.value === 'running')
  const stepText = computed(() => (currentStep.value ? STEP_TEXT[currentStep.value] : null))

  function reset(): void {
    taskId.value = null
    status.value = null
    currentStep.value = null
    errorMessage.value = null
    tools.value = []
    startedAt.value = null
  }

  function onTaskStart(id: number): void {
    reset()
    taskId.value = id
    startedAt.value = Date.now()
  }

  function onTaskStatus(id: number, s: TaskStatus, step: CurrentStep | null): void {
    taskId.value = id
    status.value = s
    currentStep.value = step
  }

  function onToolStart(id: number, toolName: string, inputSummary: string): void {
    taskId.value = id
    tools.value.push({
      tool_name: toolName,
      status: 'running',
      started_at: Date.now(),
      duration_ms: null,
      input_summary: inputSummary,
      result_summary: '',
    })
  }

  function onToolFinish(toolName: string, toolStatus: 'success' | 'failed', resultSummary: string): void {
    const item = [...tools.value].reverse().find((t) => t.tool_name === toolName && t.status === 'running')
    if (item) {
      item.status = toolStatus
      item.result_summary = resultSummary
      item.duration_ms = Date.now() - item.started_at
    }
  }

  function onError(message: string): void {
    errorMessage.value = message
    status.value = 'failed'
  }

  function onDone(): void {
    // done 不代表成功，终态以 task_status 为准；此处仅兜底收尾
    if (isRunning.value) status.value = 'success'
    currentStep.value = null
  }

  return {
    taskId,
    status,
    currentStep,
    errorMessage,
    tools,
    startedAt,
    isRunning,
    stepText,
    reset,
    onTaskStart,
    onTaskStatus,
    onToolStart,
    onToolFinish,
    onError,
    onDone,
  }
})
