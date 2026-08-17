/**
 * 认证 store：
 * - 会话为 HttpOnly Cookie（ecogain_session），前端拿不到 token；
 *   登录态校验 = 探测 GET /api/auth/me（约定接口，待后端补充）
 * - 40101 → 未登录；404/网络错误 → 降级为「已登录但角色未知」（隐藏 admin 入口）
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as api from '@/api'
import { isApiError, setUnauthorizedHandler } from '@/api/http'
import type { UserInfo } from '@/types'

/** 角色未知时的占位用户（已登录，但 /api/auth/me 不可用） */
const UNKNOWN_USER: UserInfo = { user_id: 0, username: '', display_name: '当前用户', role: 'unknown' }

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(null)
  const checked = ref(false)
  const roleUnknown = ref(false)

  const isLoggedIn = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function ensureChecked(force = false): Promise<void> {
    if (checked.value && !force) return
    try {
      user.value = await api.getMe()
      roleUnknown.value = false
    } catch (e) {
      if (isApiError(e) && e.code === 40101) {
        user.value = null
      } else {
        // 404（接口未实现）/网络错误：降级为已登录但角色未知
        user.value = UNKNOWN_USER
        roleUnknown.value = true
      }
    } finally {
      checked.value = true
    }
  }

  async function logout(): Promise<void> {
    try {
      await api.logout()
    } catch {
      // 即使登出接口失败也清理本地状态
    }
    user.value = null
    checked.value = false
    roleUnknown.value = false
    window.location.href = '/login'
  }

  /** http 层 40101 时调用：清登录态并跳登录页 */
  function onUnauthorized(): void {
    user.value = null
    checked.value = false
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
  }

  return { user, checked, roleUnknown, isLoggedIn, isAdmin, ensureChecked, logout, onUnauthorized }
})

/** 在 main.ts 中注册一次：http 拦截器 → auth store */
export function registerUnauthorizedHandler(): void {
  const auth = useAuthStore()
  setUnauthorizedHandler(() => auth.onUnauthorized())
}
