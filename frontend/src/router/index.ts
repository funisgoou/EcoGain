import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/workbench' },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/auth/callback', name: 'auth-callback', component: () => import('@/views/AuthCallbackView.vue') },
    { path: '/workbench', name: 'workbench', component: () => import('@/views/WorkbenchView.vue') },
    { path: '/admin', name: 'admin', component: () => import('@/views/AdminView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/workbench' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  // 公开页
  if (to.path === '/login' || to.path === '/auth/callback') {
    if (to.path === '/login') {
      await auth.ensureChecked()
      if (auth.isLoggedIn) return { path: '/workbench' }
    }
    return true
  }
  // 受保护页：探测登录态（40101 → /login）
  await auth.ensureChecked()
  if (!auth.isLoggedIn) return { path: '/login' }
  // admin 页：已知非 admin 角色直接回工作台；角色未知放行（由页面优雅处理 40301）
  if (to.path === '/admin' && !auth.roleUnknown && !auth.isAdmin) return { path: '/workbench' }
  return true
})

export default router
