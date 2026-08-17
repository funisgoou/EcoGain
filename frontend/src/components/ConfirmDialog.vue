<script setup lang="ts">
/** 通用确认弹窗 */
withDefaults(
  defineProps<{
    visible: boolean
    title: string
    message: string
    confirmText?: string
    danger?: boolean
  }>(),
  { confirmText: '确认', danger: false },
)

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()
</script>

<template>
  <teleport to="body">
    <div v-if="visible" class="dialog-mask" @click.self="emit('cancel')">
      <div class="dialog">
        <h3 class="dialog-title">{{ title }}</h3>
        <p class="dialog-message">{{ message }}</p>
        <div class="dialog-actions">
          <button class="btn-ghost" @click="emit('cancel')">取消</button>
          <button class="btn-primary" :class="{ danger }" @click="emit('confirm')">{{ confirmText }}</button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.dialog-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 900;
}

.dialog {
  width: 380px;
  max-width: calc(100vw - 48px);
  background: var(--color-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 24px;
}

.dialog-title {
  font-size: 16px;
  font-weight: 600;
}

.dialog-message {
  margin-top: 10px;
  color: var(--color-text-secondary);
  font-size: 13.5px;
}

.dialog-actions {
  margin-top: 22px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.btn-primary.danger {
  background: var(--color-danger);
}

.btn-primary.danger:hover {
  background: #dc2626;
}
</style>
