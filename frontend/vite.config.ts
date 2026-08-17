import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // REST + WebSocket（ws: true）均代理到后端
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
      // 授权登录 / 登出（非 /api 前缀）
      // 注意：/auth/callback 有两副面孔——真实 OAuth 回调由浏览器直连后端 :8000
      // （redirect_uri 指向后端 PUBLIC_BASE_URL）；前端同名路由只是错误展示页
      // （后端失败时 302 到 {FRONTEND_BASE}/auth/callback?error=...）。
      // 因此 dev 代理必须放行 /auth/callback 给 SPA，否则错误页会被代理到死后端。
      '/auth': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        bypass(req) {
          if (req.url?.startsWith('/auth/callback')) return req.url
        },
      },
    },
  },
})
