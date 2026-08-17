/** 会话 store（FE-3）：列表 / 新建 / 删除 / 重命名 / 当前会话 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as api from '@/api'
import type { ConversationItem } from '@/types'

export const useConversationStore = defineStore('conversation', () => {
  const list = ref<ConversationItem[]>([])
  const currentId = ref<number | null>(null)
  const loading = ref(false)

  const sorted = computed(() =>
    [...list.value].sort((a, b) => (b.last_message_at ?? '').localeCompare(a.last_message_at ?? '')),
  )
  const current = computed(() => list.value.find((c) => c.conversation_id === currentId.value) ?? null)

  async function load(): Promise<void> {
    loading.value = true
    try {
      list.value = await api.listConversations()
    } finally {
      loading.value = false
    }
  }

  async function create(title?: string): Promise<number> {
    const resp = await api.createConversation(title)
    list.value.unshift({
      conversation_id: resp.conversation_id,
      title: resp.title,
      status: resp.status,
      last_message_at: null,
    })
    return resp.conversation_id
  }

  async function remove(ids: number[]): Promise<void> {
    await api.deleteConversations(ids)
    list.value = list.value.filter((c) => !ids.includes(c.conversation_id))
    if (currentId.value !== null && ids.includes(currentId.value)) {
      currentId.value = null
    }
  }

  async function rename(id: number, title: string): Promise<void> {
    const resp = await api.renameConversation(id, title)
    const item = list.value.find((c) => c.conversation_id === id)
    if (item) item.title = resp.title
  }

  /** 有新消息时把会话顶到列表最前 */
  function touch(id: number): void {
    const item = list.value.find((c) => c.conversation_id === id)
    if (item) item.last_message_at = new Date().toISOString()
  }

  return { list, currentId, current, sorted, loading, load, create, remove, rename, touch }
})
