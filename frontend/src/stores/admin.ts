/** 管理 store（FE-10 / CFG）：配置分组展示 + 热更新 + 任务日志查看器 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

import * as api from '@/api'
import { isApiError } from '@/api/http'
import type { ConfigItem, ReloadResp, TaskInfo, TaskLogItem } from '@/types'
import { friendlyError } from '@/utils/errors'

export const useAdminStore = defineStore('admin', () => {
  // ---- 配置 ----
  const configs = ref<ConfigItem[]>([])
  const configsLoading = ref(false)
  /** 约定接口 GET /api/admin/configs 尚未实现（404）时置 true，页面展示占位说明 */
  const configsUnavailable = ref(false)
  const configsError = ref<string | null>(null)
  const reloading = ref(false)
  const reloadResult = ref<ReloadResp | null>(null)

  // ---- 任务日志 ----
  const taskInfo = ref<TaskInfo | null>(null)
  const taskLogs = ref<TaskLogItem[]>([])
  const taskLoading = ref(false)
  const taskError = ref<string | null>(null)
  const searchedTaskId = ref<number | null>(null)

  async function loadConfigs(): Promise<void> {
    configsLoading.value = true
    configsError.value = null
    configsUnavailable.value = false
    try {
      configs.value = await api.listConfigs()
    } catch (e) {
      if (isApiError(e) && (e.code === 404 || e.code === 40401)) {
        configsUnavailable.value = true
      } else {
        configsError.value = isApiError(e) ? friendlyError(e.code, e.message) : '配置加载失败'
      }
      configs.value = []
    } finally {
      configsLoading.value = false
    }
  }

  async function reload(): Promise<void> {
    reloading.value = true
    reloadResult.value = null
    try {
      reloadResult.value = await api.reloadConfigs()
    } catch (e) {
      reloadResult.value = {
        status: 'error',
        message: isApiError(e) ? friendlyError(e.code, e.message) : '重载请求失败',
      }
    } finally {
      reloading.value = false
    }
  }

  /** 任务日志查看器：task 状态 + 日志一起拉 */
  async function queryTask(taskId: number): Promise<void> {
    taskLoading.value = true
    taskError.value = null
    taskInfo.value = null
    taskLogs.value = []
    searchedTaskId.value = taskId
    try {
      taskInfo.value = await api.getTask(taskId)
    } catch (e) {
      taskError.value = isApiError(e) ? friendlyError(e.code, e.message) : '任务查询失败'
      taskLoading.value = false
      return
    }
    try {
      taskLogs.value = await api.getTaskLogs(taskId)
    } catch (e) {
      taskError.value = isApiError(e) ? friendlyError(e.code, e.message) : '日志查询失败'
    } finally {
      taskLoading.value = false
    }
  }

  return {
    configs,
    configsLoading,
    configsUnavailable,
    configsError,
    reloading,
    reloadResult,
    taskInfo,
    taskLogs,
    taskLoading,
    taskError,
    searchedTaskId,
    loadConfigs,
    reload,
    queryTask,
  }
})
