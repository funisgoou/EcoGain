<script setup lang="ts">
/** 授权登录入口页（FE-1）：完全还原 designs/login.png */
function goAuthorize(): void {
  // 契约 §3.1：GET /auth/login → 302 到认证中心
  window.location.href = '/auth/login'
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <svg class="brand-icon" viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <path
            d="M4 22l6-8 5 4 9-12"
            stroke="#2563eb"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M19 6h6v6"
            stroke="#2563eb"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <span class="brand-name">EcoGain</span>
      </div>
      <h1 class="title">经营归因分析系统</h1>
      <p class="subtitle">用自然语言完成查数—归因—追问—出报告的分析闭环</p>
      <button class="btn-primary login-btn" @click="goAuthorize">
        <svg viewBox="0 0 20 20" width="17" height="17" fill="none" aria-hidden="true">
          <path
            d="M10 2l6 2.4V9c0 4-2.6 6.9-6 8-3.4-1.1-6-4-6-8V4.4L10 2z"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linejoin="round"
          />
          <path d="M7.2 9.8l2 2 3.6-3.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        授权登录
      </button>
      <p class="hint">支持账号类型：分析用户 / 系统管理员</p>
    </div>
    <footer class="copyright">2024 EcoGain. All rights reserved.</footer>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  background: var(--color-bg);
}

.login-card {
  width: 480px;
  max-width: calc(100vw - 48px);
  background: var(--color-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 56px 64px 48px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-icon {
  width: 34px;
  height: 34px;
}

.brand-name {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 0.2px;
}

.title {
  margin-top: 28px;
  font-size: 23px;
  font-weight: 600;
}

.subtitle {
  margin-top: 14px;
  color: var(--color-text-secondary);
  font-size: 14.5px;
  text-align: center;
}

.login-btn {
  margin-top: 36px;
  width: 260px;
  padding: 13px 0;
  font-size: 16px;
  border-radius: 12px;
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.28);
}

.login-btn:hover {
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.34);
}

.hint {
  margin-top: 26px;
  font-size: 12.5px;
  color: var(--color-text-muted);
}

.copyright {
  position: absolute;
  left: 24px;
  bottom: 18px;
  font-size: 12.5px;
  color: var(--color-text-muted);
}

@media (max-width: 560px) {
  .login-card {
    padding: 40px 28px 36px;
  }

  .login-btn {
    width: 100%;
  }
}
</style>
