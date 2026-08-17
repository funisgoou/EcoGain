<script setup lang="ts">
/** 实时任务区（FE-5）：五态五色徽标 + current_step 文案 + 工具执行时间线 + 取消 */
import { computed, ref } from 'vue'

import { useChatStore } from '@/stores/chat'
import { TASK_STATUS_META, useTaskStore } from '@/stores/task'

const taskStore = useTaskStore()
const chatStore = useChatStore()

const expanded = ref(false)

const visible = computed(() => taskStore.status !== null && taskStore.status !== 'success')

const meta = computed(() => (taskStore.status ? TASK_STATUS_META[taskStore.status] : null))

const statusText = computed(() => {
  if (taskStore.status === 'queued') return '任务排队中…'
  if (taskStore.status === 'running') {
    const runningTool = taskStore.tools.find((t) => t.status === 'running')
    if (runningTool) return `正在执行 ${runningTool.tool_name}…`
    if (taskStore.stepText) return `正在${taskStore.stepText}…`
    return '正在分析…'
  }
  if (taskStore.status === 'failed') return taskStore.errorMessage ?? '任务执行失败'
  if (taskStore.status === 'cancelled') return '任务已取消'
  return ''
})

function formatDuration(ms: number | null): string {
  if (ms === null) return '…'
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<template>
  <div v-if="visible" class="task-bar" :class="{ terminal: !taskStore.isRunning }">
    <div class="task-line">
      <span v-if="taskStore.isRunning" class="spinner"></span>
      <span class="task-badge" :style="{ color: meta?.color, background: `${meta?.color}1a` }">
        {{ meta?.text }}
      </span>
      <span class="task-text">{{ statusText }}</span>
      <span class="task-spacer"></span>
      <button v-if="taskStore.tools.length" class="timeline-toggle" @click="expanded = !expanded">
        工具时间线（{{ taskStore.tools.length }}）
        <svg :class="{ open: expanded }" viewBox="0 0 12 12" width="11" height="11" fill="none" aria-hidden="true">
          <path d="M3 4.5L6 7.5l3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <button v-if="taskStore.isRunning" class="cancel-btn" @click="chatStore.cancel()">
        <svg viewBox="0 0 12 12" width="10" height="10" fill="none" aria-hidden="true">
          <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
        </svg>
        取消
      </button>
    </div>
    <div v-if="expanded && taskStore.tools.length" class="timeline">
      <div v-for="(t, i) in taskStore.tools" :key="i" class="timeline-item">
        <span class="t-dot" :class="t.status"></span>
        <span class="t-name">{{ t.tool_name }}</span>
        <span class="t-status" :class="t.status">
          {{ t.status === 'running' ? '执行中' : t.status === 'success' ? '成功' : '失败' }}
        </span>
        <span class="t-duration">{{ formatDuration(t.duration_ms) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-bar {
  margin-bottom: 16px;
  background: var(--color-card);
  border: 1px solid var(--color-primary-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.task-bar.terminal {
  border-color: var(--color-border);
}

.task-line {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 14px;
}

.task-badge {
  font-size: 12px;
  border-radius: 5px;
  padding: 1px 8px;
  flex-shrink: 0;
}

.task-text {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-spacer {
  flex: 1;
}

.timeline-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.timeline-toggle:hover {
  color: var(--color-primary);
}

.timeline-toggle svg {
  transition: transform 0.15s ease;
}

.timeline-toggle svg.open {
  transform: rotate(180deg);
}

.cancel-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 3px 10px;
  flex-shrink: 0;
  transition: all 0.12s ease;
}

.cancel-btn:hover {
  color: var(--color-danger);
  border-color: #fecaca;
  background: var(--color-danger-light);
}

.timeline {
  border-top: 1px solid var(--color-border);
  padding: 8px 14px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.timeline-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}

.t-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.t-dot.running {
  background: var(--color-primary);
  animation: pulse 1.2s infinite;
}

.t-dot.success {
  background: var(--color-success);
}

.t-dot.failed {
  background: var(--color-danger);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

.t-name {
  font-family: var(--font-mono);
  font-size: 12px;
}

.t-status.success {
  color: var(--color-success);
}

.t-status.failed {
  color: var(--color-danger);
}

.t-status.running {
  color: var(--color-primary);
}

.t-duration {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: 12px;
}
</style>
