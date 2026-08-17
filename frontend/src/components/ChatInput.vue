<script setup lang="ts">
/** 输入区：附件 chips + 输入框 + 回形针（附件抽屉）+ 发送/取消 */
import { ref } from 'vue'

import { useAttachmentStore } from '@/stores/attachment'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()
const attachmentStore = useAttachmentStore()

const text = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)

function autoResize(): void {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`
}

function doSend(): void {
  if (!text.value.trim() || chatStore.running || chatStore.conversationId === null) return
  chatStore.send(text.value, attachmentStore.selected)
  attachmentStore.clearSelected()
  text.value = ''
  autoResize()
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    doSend()
  }
}
</script>

<template>
  <div class="input-area">
    <!-- 已选附件 chips -->
    <div v-if="attachmentStore.selected.length" class="chips">
      <span v-for="a in attachmentStore.selected" :key="a.attachment_id" class="chip">
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
        <button class="chip-x" title="移除" @click="attachmentStore.deselect(a.attachment_id)">×</button>
      </span>
    </div>

    <div class="input-box" :class="{ disabled: chatStore.conversationId === null }">
      <button
        class="attach-btn"
        title="会话附件"
        :disabled="chatStore.conversationId === null"
        @click="attachmentStore.drawerOpen = true"
      >
        <svg viewBox="0 0 18 18" width="17" height="17" fill="none" aria-hidden="true">
          <path
            d="M12 4.5l3.4 3.4-7.4 7.4a3.4 3.4 0 01-4.8-4.8l7-7a2.3 2.3 0 013.2 3.2l-7 7a1.1 1.1 0 01-1.6-1.6l6.2-6.2"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
      <textarea
        ref="textarea"
        v-model="text"
        rows="1"
        :placeholder="chatStore.conversationId === null ? '请先选择或新建一个分析会话' : '输入问题或指令…'"
        :disabled="chatStore.conversationId === null"
        @input="autoResize"
        @keydown="onKeydown"
      ></textarea>
      <button v-if="chatStore.running" class="send-btn cancel" title="取消任务" @click="chatStore.cancel()">
        <svg viewBox="0 0 14 14" width="13" height="13" fill="none" aria-hidden="true">
          <rect x="2" y="2" width="10" height="10" rx="2" fill="currentColor" />
        </svg>
      </button>
      <button
        v-else
        class="send-btn"
        title="发送"
        :disabled="!text.trim() || chatStore.conversationId === null"
        @click="doSend"
      >
        <svg viewBox="0 0 18 18" width="16" height="16" fill="none" aria-hidden="true">
          <path
            d="M15.5 2.5L8 10M15.5 2.5L10.8 15.6a.4.4 0 01-.75.03L8 10 2.37 7.95a.4.4 0 01.03-.75L15.5 2.5z"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.input-area {
  padding: 0 24px 18px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
  max-width: 860px;
  margin-left: auto;
  margin-right: auto;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 7px;
  padding: 3px 8px;
  font-size: 12.5px;
  color: var(--color-text-secondary);
  box-shadow: var(--shadow-sm);
}

.chip-x {
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 1;
  padding: 0 1px;
}

.chip-x:hover {
  color: var(--color-danger);
}

.input-box {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 14px;
  padding: 10px 10px 10px 12px;
  box-shadow: var(--shadow-md);
  transition: border-color 0.15s ease;
}

.input-box:focus-within {
  border-color: var(--color-primary-border);
}

.input-box.disabled {
  opacity: 0.65;
}

.attach-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  flex-shrink: 0;
  transition: all 0.12s ease;
}

.attach-btn:hover:not(:disabled) {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

textarea {
  flex: 1;
  resize: none;
  line-height: 1.6;
  max-height: 140px;
  padding: 5px 2px;
}

textarea::placeholder {
  color: var(--color-text-muted);
}

.send-btn {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--color-primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s ease;
}

.send-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.send-btn:disabled {
  background: #a5bff5;
  cursor: not-allowed;
}

.send-btn.cancel {
  background: var(--color-danger);
}

.send-btn.cancel:hover {
  background: #dc2626;
}
</style>
