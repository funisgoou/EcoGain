<script setup lang="ts">
/** 左侧会话列表（FE-3）：新建 / 切换 / 行内重命名 / 删除（确认弹窗） */
import { nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'

import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { isApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'
import type { ConversationItem } from '@/types'
import { friendlyError } from '@/utils/errors'
import { formatRelative } from '@/utils/time'
import { toast } from '@/utils/toast'

const conversationStore = useConversationStore()
const chatStore = useChatStore()
const authStore = useAuthStore()
const router = useRouter()

const creating = ref(false)
const editingId = ref<number | null>(null)
const editingTitle = ref('')
const editInput = ref<HTMLInputElement | null>(null)
const deleting = ref<ConversationItem | null>(null)
const deleteSubmitting = ref(false)

async function onCreate(): Promise<void> {
  if (creating.value) return
  creating.value = true
  try {
    const id = await conversationStore.create()
    // 新建后自动切换并建立 WS
    await chatStore.switchConversation(id)
  } catch (e) {
    toast(isApiError(e) ? friendlyError(e.code, e.message) : '创建会话失败', 'error')
  } finally {
    creating.value = false
  }
}

async function onSelect(item: ConversationItem): Promise<void> {
  if (editingId.value === item.conversation_id) return
  await chatStore.switchConversation(item.conversation_id)
}

async function startRename(item: ConversationItem): Promise<void> {
  editingId.value = item.conversation_id
  editingTitle.value = item.title
  await nextTick()
  editInput.value?.focus()
  editInput.value?.select()
}

async function submitRename(): Promise<void> {
  const id = editingId.value
  if (id === null) return
  const title = editingTitle.value.trim()
  editingId.value = null
  const item = conversationStore.list.find((c) => c.conversation_id === id)
  if (!title || !item || item.title === title) return
  try {
    await conversationStore.rename(id, title)
  } catch (e) {
    toast(isApiError(e) ? friendlyError(e.code, e.message) : '重命名失败', 'error')
  }
}

function cancelRename(): void {
  editingId.value = null
}

async function confirmDelete(): Promise<void> {
  const item = deleting.value
  if (!item || deleteSubmitting.value) return
  deleteSubmitting.value = true
  try {
    const wasCurrent = item.conversation_id === conversationStore.currentId
    await conversationStore.remove([item.conversation_id])
    if (wasCurrent) chatStore.leaveConversation()
    toast('会话已删除', 'success')
  } catch (e) {
    toast(isApiError(e) ? friendlyError(e.code, e.message) : '删除失败', 'error')
  } finally {
    deleteSubmitting.value = false
    deleting.value = null
  }
}
</script>

<template>
  <aside class="sidebar">
    <button class="btn-primary new-btn" :disabled="creating" @click="onCreate">
      <svg viewBox="0 0 16 16" width="15" height="15" fill="none" aria-hidden="true">
        <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
      新建分析
    </button>

    <div class="conv-list">
      <div v-if="conversationStore.loading" class="list-placeholder"><span class="spinner"></span></div>
      <div v-else-if="conversationStore.sorted.length === 0" class="list-placeholder empty">
        暂无会话，点击上方按钮开始分析
      </div>
      <div
        v-for="item in conversationStore.sorted"
        :key="item.conversation_id"
        class="conv-item"
        :class="{ active: item.conversation_id === conversationStore.currentId }"
        @click="onSelect(item)"
      >
        <template v-if="editingId === item.conversation_id">
          <input
            ref="editInput"
            v-model="editingTitle"
            class="rename-input"
            maxlength="200"
            @keydown.enter.prevent="submitRename"
            @keydown.esc.prevent="cancelRename"
            @blur="submitRename"
            @click.stop
          />
        </template>
        <template v-else>
          <div class="conv-main">
            <div class="conv-title">{{ item.title }}</div>
            <div class="conv-time">{{ formatRelative(item.last_message_at) }}</div>
          </div>
          <div class="conv-actions">
            <button class="icon-btn" title="重命名" @click.stop="startRename(item)">
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
                <path
                  d="M11.3 2.3a1.4 1.4 0 012 2L5.6 12l-2.8.8.8-2.8 7.7-7.7z"
                  stroke="currentColor"
                  stroke-width="1.3"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
            <button class="icon-btn danger" title="删除" @click.stop="deleting = item">
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
                <path
                  d="M2.5 4h11M6.5 2.5h3M6 6.5v5M10 6.5v5M3.5 4l.7 8.2a1.2 1.2 0 001.2 1.1h5.2a1.2 1.2 0 001.2-1.1L12.5 4"
                  stroke="currentColor"
                  stroke-width="1.3"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>
        </template>
      </div>
    </div>

    <div class="sidebar-footer">
      <div class="user-info">
        <div class="avatar">{{ (authStore.user?.display_name || '用').slice(0, 1) }}</div>
        <span class="user-name">{{ authStore.user?.display_name || '当前用户' }}</span>
      </div>
      <div class="footer-actions">
        <button v-if="authStore.isAdmin" class="icon-btn" title="系统管理" @click="router.push('/admin')">
          <svg viewBox="0 0 16 16" width="15" height="15" fill="none" aria-hidden="true">
            <path
              d="M8 5.2a2.8 2.8 0 100 5.6 2.8 2.8 0 000-5.6zM13.6 8a5.6 5.6 0 01-.1 1l1.4 1.1-1.3 2.2-1.6-.6a5.6 5.6 0 01-1.7 1l-.3 1.7H6l-.3-1.7a5.6 5.6 0 01-1.7-1l-1.6.6-1.3-2.2L2.5 9a5.6 5.6 0 010-2L1.1 5.9l1.3-2.2 1.6.6a5.6 5.6 0 011.7-1L6 1.6h4l.3 1.7a5.6 5.6 0 011.7 1l1.6-.6 1.3 2.2-1.4 1.1c.07.33.1.66.1 1z"
              stroke="currentColor"
              stroke-width="1.1"
              stroke-linejoin="round"
            />
          </svg>
        </button>
        <button class="icon-btn" title="退出登录" @click="authStore.logout()">
          <svg viewBox="0 0 16 16" width="15" height="15" fill="none" aria-hidden="true">
            <path
              d="M6 2.5H3.5a1 1 0 00-1 1v9a1 1 0 001 1H6M10.5 11L13.5 8l-3-3M13.5 8H6.5"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </div>
    </div>

    <ConfirmDialog
      :visible="deleting !== null"
      title="删除会话"
      :message="`确定删除「${deleting?.title}」吗？该会话的全部消息与附件将被清除，且不可恢复。`"
      confirm-text="删除"
      danger
      @confirm="confirmDelete"
      @cancel="deleting = null"
    />
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  flex-shrink: 0;
  background: var(--color-bg-sidebar);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  padding: 14px 12px 10px;
}

.new-btn {
  width: 100%;
  padding: 10px 0;
  border-radius: var(--radius-md);
  font-size: 14px;
  flex-shrink: 0;
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.list-placeholder {
  padding: 30px 0;
  display: flex;
  justify-content: center;
  color: var(--color-text-muted);
  font-size: 12.5px;
  text-align: center;
}

.conv-item {
  display: flex;
  align-items: center;
  border-radius: var(--radius-md);
  padding: 9px 10px;
  cursor: pointer;
  transition: background 0.12s ease;
  position: relative;
}

.conv-item:hover {
  background: rgba(255, 255, 255, 0.75);
}

.conv-item.active {
  background: var(--color-card);
  box-shadow: var(--shadow-sm);
}

.conv-item.active .conv-title {
  color: var(--color-primary);
  font-weight: 500;
}

.conv-main {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 13.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-time {
  font-size: 11.5px;
  color: var(--color-text-muted);
  margin-top: 1px;
}

.conv-actions {
  display: none;
  gap: 2px;
  flex-shrink: 0;
}

.conv-item:hover .conv-actions {
  display: flex;
}

.icon-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  transition: all 0.12s ease;
}

.icon-btn:hover {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.icon-btn.danger:hover {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

.rename-input {
  width: 100%;
  border: 1px solid var(--color-primary-border);
  border-radius: var(--radius-sm);
  padding: 5px 8px;
  font-size: 13.5px;
  background: #fff;
}

.sidebar-footer {
  flex-shrink: 0;
  border-top: 1px solid var(--color-border);
  padding-top: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  font-size: 12.5px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.footer-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
</style>
