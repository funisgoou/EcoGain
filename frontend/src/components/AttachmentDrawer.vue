<script setup lang="ts">
/** 会话附件抽屉（FE-7）：上传（进度条）/ 解析状态可视化 / 选用 / 下载 / 删除 */
import { computed, ref } from 'vue'

import { useAttachmentStore } from '@/stores/attachment'
import { useChatStore } from '@/stores/chat'
import type { AttachmentBrief } from '@/types'

const attachmentStore = useAttachmentStore()
const chatStore = useChatStore()

const fileInput = ref<HTMLInputElement | null>(null)

const items = computed(() => attachmentStore.listFor(chatStore.conversationId))
const selectedIds = computed(() => attachmentStore.selected.map((s) => s.attachment_id))

function pickFile(): void {
  fileInput.value?.click()
}

async function onFileChange(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || chatStore.conversationId === null) return
  await attachmentStore.upload(chatStore.conversationId, file)
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function statusOf(a: AttachmentBrief): { text: string; cls: string } {
  switch (a.parse_status) {
    case 'pending':
      return { text: '待解析', cls: 'parsing' }
    case 'parsing':
      return { text: '解析中', cls: 'parsing' }
    case 'ready':
      return { text: '已就绪', cls: 'ready' }
    case 'failed':
      return { text: '解析失败，请删除后重传', cls: 'failed' }
  }
}
</script>

<template>
  <teleport to="body">
    <div v-if="attachmentStore.drawerOpen" class="drawer-mask" @click="attachmentStore.drawerOpen = false"></div>
    <transition name="slide">
      <div v-if="attachmentStore.drawerOpen" class="drawer">
        <div class="drawer-header">
          <h3>会话附件</h3>
          <button class="close-btn" title="关闭" @click="attachmentStore.drawerOpen = false">×</button>
        </div>

        <button class="btn-primary upload-btn" :disabled="attachmentStore.uploadProgress !== null" @click="pickFile">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
            <path d="M8 10.5v-7M5 6l3-3 3 3M3 12.5v1a1 1 0 001 1h8a1 1 0 001-1v-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          上传附件
        </button>
        <p class="upload-hint">支持 csv / xlsx / txt / md，单个不超过 10MB</p>
        <input ref="fileInput" type="file" accept=".csv,.xlsx,.txt,.md" hidden @change="onFileChange" />

        <div v-if="attachmentStore.uploadProgress" class="upload-progress">
          <div class="progress-name">{{ attachmentStore.uploadProgress.fileName }}</div>
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${attachmentStore.uploadProgress.percent}%` }"></div>
          </div>
          <div class="progress-percent">{{ attachmentStore.uploadProgress.percent }}%</div>
        </div>

        <div class="att-list">
          <div v-if="!items.length" class="att-empty">
            暂无附件。<br />上传数据文件后，分析时会自动纳入取证范围。
          </div>
          <div v-for="a in items" :key="a.attachment_id" class="att-item">
            <div class="att-icon">{{ a.file_type.toUpperCase() }}</div>
            <div class="att-main">
              <div class="att-name" :title="a.file_name">{{ a.file_name }}</div>
              <div class="att-meta">
                <span>{{ formatSize(a.file_size) }}</span>
                <span class="att-status" :class="statusOf(a).cls">
                  <span v-if="a.parse_status === 'pending' || a.parse_status === 'parsing'" class="spinner mini"></span>
                  <span v-else-if="a.parse_status === 'ready'" class="dot-ready"></span>
                  {{ statusOf(a).text }}
                </span>
              </div>
            </div>
            <div class="att-actions">
              <button
                v-if="!selectedIds.includes(a.attachment_id)"
                class="att-action"
                :disabled="a.parse_status !== 'ready'"
                title="随下一条消息发送"
                @click="attachmentStore.select(a)"
              >
                选用
              </button>
              <span v-else class="att-selected">已选</span>
              <button class="att-action" title="下载" @click="attachmentStore.download(a.attachment_id)">下载</button>
              <button
                class="att-action danger"
                :disabled="a.parse_status === 'parsing'"
                :title="a.parse_status === 'parsing' ? '解析中不可删除' : '删除'"
                @click="chatStore.conversationId !== null && attachmentStore.remove(chatStore.conversationId, a.attachment_id)"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<style scoped>
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.25);
  z-index: 800;
}

.drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 340px;
  max-width: 90vw;
  background: var(--color-card);
  box-shadow: var(--shadow-lg);
  z-index: 810;
  display: flex;
  flex-direction: column;
  padding: 18px;
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.2s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.drawer-header h3 {
  font-size: 15.5px;
  font-weight: 600;
}

.close-btn {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  font-size: 18px;
  line-height: 1;
}

.close-btn:hover {
  background: var(--color-bg);
  color: var(--color-text);
}

.upload-btn {
  width: 100%;
  padding: 9px 0;
}

.upload-hint {
  margin-top: 7px;
  font-size: 12px;
  color: var(--color-text-muted);
  text-align: center;
}

.upload-progress {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-name {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.progress-track {
  flex: 2;
  height: 6px;
  border-radius: 3px;
  background: var(--color-bg);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--color-primary);
  border-radius: 3px;
  transition: width 0.15s ease;
}

.progress-percent {
  font-size: 12px;
  color: var(--color-text-muted);
  width: 36px;
  text-align: right;
}

.att-list {
  flex: 1;
  overflow-y: auto;
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.att-empty {
  padding: 36px 12px;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 12.5px;
  line-height: 1.8;
}

.att-item {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
}

.att-icon {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: 9.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.att-main {
  flex: 1;
  min-width: 0;
}

.att-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.att-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.att-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.att-status.ready {
  color: var(--color-success);
}

.att-status.failed {
  color: var(--color-danger);
}

.dot-ready {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-success);
}

.spinner.mini {
  width: 10px;
  height: 10px;
  border-width: 1.5px;
}

.att-actions {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex-shrink: 0;
}

.att-action {
  font-size: 12px;
  color: var(--color-primary);
  padding: 1px 6px;
  border-radius: 4px;
  text-align: right;
}

.att-action:hover:not(:disabled) {
  background: var(--color-primary-light);
}

.att-action:disabled {
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.att-action.danger {
  color: var(--color-danger);
}

.att-action.danger:hover:not(:disabled) {
  background: var(--color-danger-light);
}

.att-selected {
  font-size: 12px;
  color: var(--color-success);
  text-align: right;
  padding: 1px 6px;
}
</style>
