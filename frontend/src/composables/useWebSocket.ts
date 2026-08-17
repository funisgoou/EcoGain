/**
 * useWebSocket（FE-9，严格按 SPEC 5.2 状态机）：
 * idle → connecting → open → closed(reconnecting)
 * - 建连：POST /api/chat/ws-token 取一次性令牌 → 拼接 WS URL（同源，经 Vite/nginx 代理）
 * - onopen 启动 30s ping；关闭码 4401 重新取 token 再连；4408/其他指数退避 1s/2s/4s/8s 上限 30s
 * - 连续 10 次失败置 networkError（UI 提示网络异常）
 * - 切会话：close() 后 connect(新会话)
 */
import { ref } from 'vue'

import { getWsToken } from '@/api'
import { createMockSocket, type WsLike } from '@/api/mock'
import { USE_MOCK } from '@/api/runtime'
import type { WsDown, WsUp } from '@/types'

export type WsState = 'idle' | 'connecting' | 'open' | 'closed' | 'reconnecting'

const MAX_RETRIES = 10
const PING_INTERVAL = 30_000

export function useWebSocket(onMessage: (msg: WsDown) => void) {
  const state = ref<WsState>('idle')
  const networkError = ref(false)

  let ws: WsLike | null = null
  let conversationId: number | null = null
  let manualClose = false
  let retries = 0
  let pingTimer: ReturnType<typeof setInterval> | undefined
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined

  function clearTimers(): void {
    if (pingTimer) clearInterval(pingTimer)
    if (reconnectTimer) clearTimeout(reconnectTimer)
    pingTimer = undefined
    reconnectTimer = undefined
  }

  function startPing(): void {
    if (pingTimer) clearInterval(pingTimer)
    pingTimer = setInterval(() => send({ type: 'ping' }), PING_INTERVAL)
  }

  function open(token: string, cid: number): void {
    if (USE_MOCK) {
      ws = createMockSocket(cid)
    } else {
      const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${protocol}://${location.host}/api/chat/ws/chat?websocket_token=${encodeURIComponent(token)}&conversation_id=${cid}`
      ws = new WebSocket(url) as unknown as WsLike
    }
    ws.onopen = () => {
      state.value = 'open'
      retries = 0
      startPing()
    }
    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data) as WsDown)
      } catch {
        // 非 JSON 帧忽略
      }
    }
    ws.onerror = () => {
      // 错误后必有 close，统一在 onclose 处理
    }
    ws.onclose = (ev) => {
      if (pingTimer) clearInterval(pingTimer)
      if (manualClose) {
        state.value = 'closed'
        return
      }
      // 4401：令牌无效/过期/已消费 → 重新取 token 再连
      if (ev.code === 4401) {
        state.value = 'reconnecting'
        void connect(cid)
        return
      }
      // 4408（心跳超时）/1000/其他 → 指数退避重连
      scheduleReconnect()
    }
  }

  function scheduleReconnect(): void {
    if (manualClose || conversationId === null) return
    if (retries >= MAX_RETRIES) {
      state.value = 'closed'
      networkError.value = true
      return
    }
    const delay = Math.min(1000 * 2 ** retries, 30_000)
    retries += 1
    state.value = 'reconnecting'
    reconnectTimer = setTimeout(() => {
      if (conversationId !== null) void connect(conversationId)
    }, delay)
  }

  async function connect(cid: number): Promise<void> {
    clearTimers()
    if (ws) {
      const old = ws
      ws = null
      old.onclose = null
      try {
        old.close()
      } catch {
        /* 忽略 */
      }
    }
    manualClose = false
    conversationId = cid
    networkError.value = false
    state.value = 'connecting'
    try {
      const { websocket_token } = await getWsToken(cid)
      // 等待令牌期间可能已切换会话
      if (conversationId !== cid || manualClose) return
      open(websocket_token, cid)
    } catch {
      scheduleReconnect()
    }
  }

  function send(msg: WsUp): boolean {
    if (ws && state.value === 'open') {
      ws.send(JSON.stringify(msg))
      return true
    }
    return false
  }

  function close(): void {
    manualClose = true
    conversationId = null
    clearTimers()
    if (ws) {
      const old = ws
      ws = null
      try {
        old.close()
      } catch {
        /* 忽略 */
      }
    }
    state.value = 'closed'
  }

  return { state, networkError, connect, send, close }
}
