/** 结果 store（FE-8 / RES-3 / RES-4）：六段结构化结果加载、复制、导出 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

import * as api from '@/api'
import { isApiError } from '@/api/http'
import type { AnalysisResult } from '@/types'
import { saveBlob } from '@/utils/download'
import { friendlyError } from '@/utils/errors'
import { toast } from '@/utils/toast'

export const useResultStore = defineStore('result', () => {
  const currentTaskId = ref<number | null>(null)
  const result = ref<AnalysisResult | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const copied = ref(false)
  const exporting = ref(false)

  let copiedTimer: ReturnType<typeof setTimeout> | undefined

  async function load(taskId: number): Promise<void> {
    loading.value = true
    error.value = null
    try {
      result.value = await api.getResult(taskId)
      currentTaskId.value = taskId
    } catch (e) {
      error.value = isApiError(e) ? friendlyError(e.code, e.message) : '结果加载失败'
      result.value = null
      currentTaskId.value = null
    } finally {
      loading.value = false
    }
  }

  function clear(): void {
    currentTaskId.value = null
    result.value = null
    error.value = null
    loading.value = false
  }

  /** RES-3：一键复制 result_markdown */
  async function copy(): Promise<void> {
    if (!result.value) return
    try {
      await navigator.clipboard.writeText(result.value.result_markdown)
      copied.value = true
      if (copiedTimer) clearTimeout(copiedTimer)
      copiedTimer = setTimeout(() => (copied.value = false), 2000)
    } catch {
      toast('复制失败，请检查浏览器剪贴板权限', 'error')
    }
  }

  /** RES-4：导出 Markdown（40301 时提示导出功能已关闭） */
  async function exportMarkdown(): Promise<void> {
    if (currentTaskId.value === null || exporting.value) return
    exporting.value = true
    try {
      const { blob, filename } = await api.downloadResult(currentTaskId.value)
      saveBlob(blob, filename)
    } catch (e) {
      if (isApiError(e) && e.code === 40301) {
        toast('导出功能已关闭或当前账号无权限', 'error')
      } else {
        toast(isApiError(e) ? friendlyError(e.code, e.message) : '导出失败', 'error')
      }
    } finally {
      exporting.value = false
    }
  }

  return { currentTaskId, result, loading, error, copied, exporting, load, clear, copy, exportMarkdown }
})
