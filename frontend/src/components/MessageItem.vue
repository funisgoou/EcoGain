<script setup lang="ts">
/** 消息渲染：用户气泡 / assistant Markdown / 深色工具块（可折叠）/ 结果卡片 */
import { computed, ref } from 'vue'

import type { UiMessage } from '@/stores/chat'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ message: UiMessage }>()

const emit = defineEmits<{
  viewResult: [taskId: number]
}>()

const collapsed = ref(false)

const html = computed(() => renderMarkdown(props.message.content))

const toolStatusMeta = computed(() => {
  switch (props.message.tool_status) {
    case 'running':
      return { text: '执行中', cls: 'running' }
    case 'success':
      return { text: '执行成功', cls: 'success' }
    case 'failed':
      return { text: '执行失败', cls: 'failed' }
    default:
      return { text: '', cls: '' }
  }
})

const durationText = computed(() => {
  const ms = props.message.tool_duration_ms
  if (ms === null) return ''
  return `耗时 ${(ms / 1000).toFixed(1)}s`
})

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <!-- 用户气泡 -->
  <div v-if="message.role === 'user'" class="msg-row user">
    <div class="user-bubble">
      <div v-if="message.attachments.length" class="bubble-attachments">
        <span v-for="a in message.attachments" :key="a.attachment_id" class="bubble-chip">
          <svg viewBox="0 0 16 16" width="11" height="11" fill="none" aria-hidden="true">
            <path
              d="M10.5 3.5l3 3-6.8 6.8a2.4 2.4 0 01-3.4-3.4l6.4-6.4a1.6 1.6 0 012.3 2.3l-6.4 6.4a.8.8 0 01-1.1-1.1l5.8-5.8"
              stroke="currentColor"
              stroke-width="1.2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          {{ a.file_name }}
          <span class="chip-size">{{ formatSize(a.file_size) }}</span>
        </span>
      </div>
      <div class="user-text">{{ message.content }}</div>
    </div>
  </div>

  <!-- 工具块 -->
  <div v-else-if="message.kind === 'tool_call'" class="msg-row">
    <div class="tool-block">
      <button class="tool-header" @click="collapsed = !collapsed">
        <span class="tool-left">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
            <rect x="2" y="2" width="12" height="12" rx="2.5" stroke="currentColor" stroke-width="1.3" />
            <path d="M5.5 6.5L4 8l1.5 1.5M10.5 6.5L12 8l-1.5 1.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span class="tool-name">{{ message.tool_name }}</span>
        </span>
        <span class="tool-right">
          <span class="tool-badge" :class="toolStatusMeta.cls">
            <span v-if="message.tool_status === 'running'" class="spinner mini"></span>
            <svg v-else-if="message.tool_status === 'success'" viewBox="0 0 12 12" width="11" height="11" fill="none" aria-hidden="true">
              <path d="M2.5 6.5l2.4 2.4L9.5 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            {{ toolStatusMeta.text }}
            <template v-if="durationText"> · {{ durationText }}</template>
          </span>
          <svg class="fold-icon" :class="{ collapsed }" viewBox="0 0 12 12" width="12" height="12" fill="none" aria-hidden="true">
            <path d="M3 4.5L6 7.5l3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
      </button>
      <div v-show="!collapsed" class="tool-body">
        <pre v-if="message.tool_input_summary" class="tool-code">{{ message.tool_input_summary }}</pre>
        <div v-if="message.tool_result_summary" class="tool-summary">{{ message.tool_result_summary }}</div>
      </div>
    </div>
  </div>

  <!-- 结果卡片 -->
  <div v-else-if="message.kind === 'result'" class="msg-row">
    <button class="result-card" @click="message.task_id !== null && emit('viewResult', message.task_id)">
      <span class="result-icon">
        <svg viewBox="0 0 16 16" width="15" height="15" fill="none" aria-hidden="true">
          <path d="M3 13.5V6.5M8 13.5V2.5M13 13.5v-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
      </span>
      <span class="result-text">
        <span class="result-title">归因分析报告已生成</span>
        <span class="result-sub">点击查看六段结构化结论</span>
      </span>
      <span class="result-arrow">→</span>
    </button>
  </div>

  <!-- assistant 文本 -->
  <div v-else class="msg-row">
    <div class="assistant-card" :class="{ streaming: message.streaming }">
      <div v-if="message.content" class="md-body" v-html="html"></div>
      <div v-else-if="message.streaming" class="thinking">
        <span class="dot"></span><span class="dot"></span><span class="dot"></span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg-row {
  display: flex;
  margin-bottom: 16px;
}

.msg-row.user {
  justify-content: flex-end;
}

.user-bubble {
  max-width: 72%;
  background: var(--color-primary);
  color: #fff;
  border-radius: 14px 14px 4px 14px;
  padding: 10px 14px;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.22);
}

.user-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.65;
}

.bubble-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.bubble-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: rgba(255, 255, 255, 0.18);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 12px;
}

.chip-size {
  opacity: 0.7;
  font-size: 11px;
}

.assistant-card {
  max-width: 100%;
  flex: 1;
  min-width: 0;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-left: 3px solid var(--color-primary);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  box-shadow: var(--shadow-sm);
}

.assistant-card.streaming {
  border-left-color: var(--color-primary-border);
}

.thinking {
  display: flex;
  gap: 5px;
  padding: 6px 0;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-primary-border);
  animation: blink 1.2s infinite;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

/* 深色工具块 */
.tool-block {
  flex: 1;
  min-width: 0;
  background: var(--color-dark-block);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.tool-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 14px;
  background: var(--color-dark-block-header);
  color: var(--color-dark-text);
}

.tool-left {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--color-dark-muted);
}

.tool-name {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--color-dark-text);
}

.tool-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.tool-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  border-radius: 5px;
  padding: 2px 8px;
}

.tool-badge.success {
  color: #34d399;
  background: rgba(16, 185, 129, 0.12);
}

.tool-badge.failed {
  color: #f87171;
  background: rgba(239, 68, 68, 0.12);
}

.tool-badge.running {
  color: #93c5fd;
  background: rgba(59, 130, 246, 0.14);
}

.spinner.mini {
  width: 10px;
  height: 10px;
  border-width: 1.5px;
}

.fold-icon {
  color: var(--color-dark-muted);
  transition: transform 0.15s ease;
}

.fold-icon.collapsed {
  transform: rotate(-90deg);
}

.tool-body {
  padding: 12px 14px;
}

.tool-code {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--color-dark-text);
  white-space: pre-wrap;
  word-break: break-all;
}

.tool-summary {
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 12px;
  color: var(--color-dark-muted);
}

/* 结果卡片 */
.result-card {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--color-success-light);
  border: 1px solid #a7f3d0;
  border-radius: var(--radius-md);
  padding: 12px 16px;
  text-align: left;
  transition: box-shadow 0.15s ease;
}

.result-card:hover {
  box-shadow: var(--shadow-md);
}

.result-icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--color-success);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.result-text {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.result-title {
  font-weight: 600;
  font-size: 13.5px;
  color: #065f46;
}

.result-sub {
  font-size: 12px;
  color: #059669;
}

.result-arrow {
  color: var(--color-success);
  font-size: 16px;
}
</style>
