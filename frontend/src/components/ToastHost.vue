<script setup lang="ts">
import { toasts } from '@/utils/toast'
</script>

<template>
  <div class="toast-host">
    <transition-group name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="`toast-${t.type}`">
        {{ t.text }}
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  pointer-events: none;
}

.toast {
  padding: 9px 18px;
  border-radius: var(--radius-md);
  font-size: 13.5px;
  box-shadow: var(--shadow-md);
  background: var(--color-card);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

.toast-success {
  background: var(--color-success-light);
  border-color: #a7f3d0;
  color: #047857;
}

.toast-error {
  background: var(--color-danger-light);
  border-color: #fecaca;
  color: #b91c1c;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
