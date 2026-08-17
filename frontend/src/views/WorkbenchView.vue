<script setup lang="ts">
/** 聊天工作台（FE-3~9）：左会话列表 / 中对话区 / 右结果面板（<1366px 折叠为抽屉） */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AttachmentDrawer from '@/components/AttachmentDrawer.vue'
import ChatInput from '@/components/ChatInput.vue'
import ConversationSidebar from '@/components/ConversationSidebar.vue'
import MessageItem from '@/components/MessageItem.vue'
import ResultPanel from '@/components/ResultPanel.vue'
import TaskStatusBar from '@/components/TaskStatusBar.vue'
import { useAttachmentStore } from '@/stores/attachment'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'
import { useResultStore } from '@/stores/result'

const conversationStore = useConversationStore()
const chatStore = useChatStore()
const resultStore = useResultStore()
const attachmentStore = useAttachmentStore()

// ---------- 响应式：<1366px 结果区折叠为抽屉 ----------
const isNarrow = ref(window.innerWidth < 1366)
const resultDrawerOpen = ref(false)

function onResize(): void {
  isNarrow.value = window.innerWidth < 1366
}

// ---------- 消息区滚动跟随：用户上滚时暂停 ----------
const msgListEl = ref<HTMLElement | null>(null)
const follow = ref(true)

function onScroll(): void {
  const el = msgListEl.value
  if (!el) return
  follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

async function scrollToBottom(force = false): Promise<void> {
  if (!force && !follow.value) return
  await nextTick()
  const el = msgListEl.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => [chatStore.messages.length, chatStore.messages[chatStore.messages.length - 1]?.content],
  () => scrollToBottom(),
)

watch(
  () => chatStore.conversationId,
  () => {
    follow.value = true
    scrollToBottom(true)
  },
)

// ---------- 结果卡片回看 ----------
function onViewResult(taskId: number): void {
  void resultStore.load(taskId)
  if (isNarrow.value) resultDrawerOpen.value = true
}

// 新结果就绪时窄屏自动展开抽屉
watch(
  () => resultStore.result,
  (r) => {
    if (r && isNarrow.value) resultDrawerOpen.value = true
  },
)

const title = computed(() => conversationStore.current?.title ?? 'EcoGain 经营归因分析')

const wsStateText = computed(() => {
  switch (chatStore.wsState) {
    case 'connecting':
      return '连接中'
    case 'reconnecting':
      return '重连中'
    case 'open':
      return '已连接'
    default:
      return '未连接'
  }
})

onMounted(async () => {
  window.addEventListener('resize', onResize)
  await conversationStore.load()
  // 默认进入最近会话
  const first = conversationStore.sorted[0]
  if (first && chatStore.conversationId === null) {
    await chatStore.switchConversation(first.conversation_id)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chatStore.leaveConversation()
  attachmentStore.reset()
})
</script>

<template>
  <div class="workbench">
    <ConversationSidebar />

    <main class="chat-column">
      <header class="chat-header">
        <h2 class="chat-title">{{ title }}</h2>
        <div class="header-right">
          <span class="ws-state" :class="chatStore.wsState">
            <span class="ws-dot"></span>{{ wsStateText }}
          </span>
          <button v-if="isNarrow" class="btn-ghost panel-toggle" @click="resultDrawerOpen = !resultDrawerOpen">
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
              <rect x="1.5" y="2.5" width="13" height="11" rx="2" stroke="currentColor" stroke-width="1.3" />
              <path d="M10 2.5v11" stroke="currentColor" stroke-width="1.3" />
            </svg>
            结果
          </button>
        </div>
      </header>

      <div v-if="chatStore.networkError" class="net-banner">
        网络异常，连接已断开
        <button class="net-retry" @click="chatStore.reconnect()">重新连接</button>
      </div>

      <div ref="msgListEl" class="msg-list" @scroll.passive="onScroll">
        <div class="msg-inner">
          <div v-if="chatStore.loadingHistory" class="list-state"><span class="spinner"></span></div>

          <div v-else-if="chatStore.conversationId === null" class="list-state empty">
            <svg viewBox="0 0 48 48" width="46" height="46" fill="none" aria-hidden="true">
              <path d="M6 40V10a4 4 0 014-4h28a4 4 0 014 4v20a4 4 0 01-4 4H16l-10 6z" stroke="#cbd2e0" stroke-width="2" stroke-linejoin="round" />
              <path d="M14 18h20M14 25h12" stroke="#cbd2e0" stroke-width="2" stroke-linecap="round" />
            </svg>
            <p>从左侧新建一个分析会话，<br />用自然语言开始经营归因分析</p>
          </div>

          <div v-else-if="!chatStore.messages.length" class="list-state empty">
            <p>输入你的经营问题，例如：<br />「为什么上周护肤品类的退款率明显上升？」</p>
          </div>

          <template v-for="m in chatStore.messages" :key="m.local_id">
            <MessageItem :message="m" @view-result="onViewResult" />
          </template>

          <TaskStatusBar />

          <div v-if="chatStore.error" class="error-bar">
            <span class="error-msg">{{ chatStore.error.message }}</span>
            <button class="btn-ghost retry-btn" @click="chatStore.retry()">重试</button>
            <button class="error-close" title="关闭" @click="chatStore.clearError()">×</button>
          </div>
        </div>
      </div>

      <ChatInput />
    </main>

    <!-- 结果面板：宽屏固定侧栏 / 窄屏抽屉 -->
    <aside v-if="!isNarrow" class="result-aside">
      <ResultPanel />
    </aside>
    <teleport v-else to="body">
      <div v-if="resultDrawerOpen" class="result-mask" @click="resultDrawerOpen = false"></div>
      <transition name="slide">
        <aside v-if="resultDrawerOpen" class="result-drawer">
          <ResultPanel drawer-mode @close="resultDrawerOpen = false" />
        </aside>
      </transition>
    </teleport>

    <AttachmentDrawer />
  </div>
</template>

<style scoped>
.workbench {
  height: 100%;
  display: flex;
  overflow: hidden;
}

.chat-column {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
}

.chat-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 22px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-card);
}

.chat-title {
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.ws-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.ws-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #cbd2e0;
}

.ws-state.open .ws-dot {
  background: var(--color-success);
}

.ws-state.connecting .ws-dot,
.ws-state.reconnecting .ws-dot {
  background: var(--color-warning);
  animation: pulse 1.2s infinite;
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

.panel-toggle {
  font-size: 12.5px;
}

.net-banner {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: var(--color-warning-light);
  border-bottom: 1px solid #fde68a;
  color: #92400e;
  font-size: 13px;
  padding: 7px 0;
}

.net-retry {
  color: var(--color-primary);
  font-size: 13px;
  text-decoration: underline;
}

.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 8px;
}

.msg-inner {
  max-width: 860px;
  margin: 0 auto;
}

.list-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 80px 0;
  color: var(--color-text-muted);
  font-size: 13.5px;
  text-align: center;
  line-height: 1.9;
}

.error-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--color-danger-light);
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  padding: 9px 14px;
  margin-bottom: 16px;
}

.error-msg {
  flex: 1;
  font-size: 13px;
  color: #b91c1c;
}

.retry-btn {
  font-size: 12.5px;
  color: var(--color-danger);
  border-color: #fecaca;
}

.error-close {
  color: #b91c1c;
  font-size: 16px;
  line-height: 1;
  padding: 2px 4px;
}

.result-aside {
  width: var(--result-panel-width);
  flex-shrink: 0;
  border-left: 1px solid var(--color-border);
  overflow: hidden;
}

.result-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.25);
  z-index: 700;
}

.result-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: var(--result-panel-width);
  max-width: 92vw;
  z-index: 710;
  box-shadow: var(--shadow-lg);
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.2s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
</style>
