<script setup lang="ts">
/** 登录回调页（FE-2）：loading 态；URL 带 error/message 时展示原因 + 重试 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const errorMessage = computed(() => {
  const message = route.query.message
  const error = route.query.error
  if (typeof message === 'string' && message) return message
  if (typeof error === 'string' && error) return `登录失败（${error}）`
  return null
})

function retry(): void {
  window.location.href = '/auth/login'
}
</script>

<template>
  <div class="callback-page">
    <div class="callback-card">
      <template v-if="errorMessage">
        <div class="error-icon">!</div>
        <h2 class="callback-title">登录未完成</h2>
        <p class="callback-text error-text">{{ errorMessage }}</p>
        <button class="btn-primary retry-btn" @click="retry">重试登录</button>
      </template>
      <template v-else>
        <span class="spinner big"></span>
        <h2 class="callback-title">正在完成登录…</h2>
        <p class="callback-text">正在校验授权信息，请稍候</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.callback-page {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg);
}

.callback-card {
  width: 400px;
  max-width: calc(100vw - 48px);
  background: var(--color-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 48px 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.spinner.big {
  width: 34px;
  height: 34px;
  border-width: 3px;
}

.callback-title {
  margin-top: 20px;
  font-size: 18px;
  font-weight: 600;
}

.callback-text {
  margin-top: 8px;
  color: var(--color-text-secondary);
}

.error-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--color-danger-light);
  color: var(--color-danger);
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.error-text {
  color: var(--color-danger);
  word-break: break-all;
}

.retry-btn {
  margin-top: 24px;
  padding: 10px 28px;
}
</style>
