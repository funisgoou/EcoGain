import { reactive } from 'vue'

export interface ToastItem {
  id: number
  type: 'info' | 'success' | 'error'
  text: string
}

export const toasts = reactive<ToastItem[]>([])

let seq = 0

/** 轻量全局提示，3s 自动消失 */
export function toast(text: string, type: ToastItem['type'] = 'info'): void {
  const id = ++seq
  toasts.push({ id, type, text })
  window.setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, 3000)
}
