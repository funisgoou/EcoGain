/**
 * 接口层：函数与 docs/API-接口设计文档.md 一一对应。
 * USE_MOCK=true 时全部切换到 src/api/mock.ts 的内存实现，调用方无感。
 */
import type { AxiosResponse } from 'axios'

import type {
  AnalysisResult,
  ConfigItem,
  ConversationItem,
  CreateConversationResp,
  HistoryMessage,
  ReloadResp,
  TaskInfo,
  TaskLogItem,
  UploadAttachmentResp,
  UserInfo,
  WsTokenResp,
} from '@/types'
import { parseFilename } from '@/utils/download'

import { http } from './http'
import { mockApi } from './mock'
import { USE_MOCK } from './runtime'

const get = <T>(url: string, config?: object) => http.get(url, config) as unknown as Promise<T>
const post = <T>(url: string, data?: unknown, config?: object) =>
  http.post(url, data, config) as unknown as Promise<T>

export interface DownloadedFile {
  blob: Blob
  filename: string
}

// ============ 认证（§3） ============

/**
 * 获取当前用户（含角色）。
 * 注意：契约暂无此接口，约定 GET /api/auth/me，待后端补充（见 README「契约缺口」）。
 */
export function getMe(): Promise<UserInfo> {
  if (USE_MOCK) return mockApi.getMe()
  return get<UserInfo>('/api/auth/me')
}

/** 登出：POST /auth/logout（契约 §3.3，非 /api 前缀） */
export function logout(): Promise<{ ok: boolean }> {
  if (USE_MOCK) return mockApi.logout()
  return post<{ ok: boolean }>('/auth/logout')
}

// ============ 会话（§4） ============

export function listConversations(includeArchived = false): Promise<ConversationItem[]> {
  if (USE_MOCK) return mockApi.listConversations()
  return get<ConversationItem[]>('/api/chat/ls', { params: { include_archived: includeArchived } })
}

export function createConversation(title?: string): Promise<CreateConversationResp> {
  if (USE_MOCK) return mockApi.createConversation(title)
  return post<CreateConversationResp>('/api/chat/create', title ? { title } : {})
}

export function deleteConversations(ids: number[]): Promise<{ deleted_count: number }> {
  if (USE_MOCK) return mockApi.deleteConversations(ids)
  return post<{ deleted_count: number }>('/api/chat/delete', { conversation_ids: ids })
}

export function renameConversation(id: number, title: string): Promise<{ conversation_id: number; title: string }> {
  if (USE_MOCK) return mockApi.renameConversation(id, title)
  return post<{ conversation_id: number; title: string }>('/api/chat/update', { conversation_id: id, title })
}

export function listMessages(conversationId: number): Promise<HistoryMessage[]> {
  if (USE_MOCK) return mockApi.listMessages(conversationId)
  return get<HistoryMessage[]>(`/api/chat/ls/${conversationId}`)
}

// ============ 附件（§5） ============

export function uploadAttachment(
  conversationId: number,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadAttachmentResp> {
  if (USE_MOCK) return mockApi.uploadAttachment(conversationId, file, onProgress)
  const form = new FormData()
  form.append('conversation_id', String(conversationId))
  form.append('file', file)
  return post<UploadAttachmentResp>('/api/attachment/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e: { loaded: number; total?: number }) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}

export function deleteAttachment(attachmentId: number): Promise<{ deleted: boolean }> {
  if (USE_MOCK) return mockApi.deleteAttachment(attachmentId)
  return post<{ deleted: boolean }>('/api/attachment/delete', { attachment_id: attachmentId })
}

export async function downloadAttachment(attachmentId: number): Promise<DownloadedFile> {
  if (USE_MOCK) return mockApi.downloadAttachment(attachmentId)
  const resp = (await http.get('/api/attachment/get', {
    params: { attachment_id: attachmentId },
    responseType: 'blob',
  })) as unknown as AxiosResponse<Blob>
  return {
    blob: resp.data,
    filename: parseFilename(resp.headers['content-disposition'], `attachment_${attachmentId}`),
  }
}

// ============ WS 令牌（§8.1） ============

export function getWsToken(conversationId: number): Promise<WsTokenResp> {
  if (USE_MOCK) return mockApi.getWsToken(conversationId)
  return post<WsTokenResp>('/api/chat/ws-token', { conversation_id: conversationId })
}

// ============ 任务与结果（§6） ============

export function getTask(taskId: number): Promise<TaskInfo> {
  if (USE_MOCK) return mockApi.getTask(taskId)
  return get<TaskInfo>(`/api/tasks/${taskId}`)
}

export function getResult(taskId: number): Promise<AnalysisResult> {
  if (USE_MOCK) return mockApi.getResult(taskId)
  return get<AnalysisResult>(`/api/results/${taskId}`)
}

export async function downloadResult(taskId: number): Promise<DownloadedFile> {
  if (USE_MOCK) return mockApi.downloadResult(taskId)
  const resp = (await http.get(`/api/results/${taskId}/download`, {
    responseType: 'blob',
  })) as unknown as AxiosResponse<Blob>
  return {
    blob: resp.data,
    filename: parseFilename(resp.headers['content-disposition'], `result_${taskId}.md`),
  }
}

// ============ 管理（§7） ============

export function reloadConfigs(): Promise<ReloadResp> {
  if (USE_MOCK) return mockApi.reloadConfigs()
  return post<ReloadResp>('/api/admin/reload')
}

/**
 * 配置读取。
 * 注意：契约暂无此接口，约定 GET /api/admin/configs，待后端补充（见 README「契约缺口」）。
 */
export function listConfigs(): Promise<ConfigItem[]> {
  if (USE_MOCK) return mockApi.listConfigs()
  return get<ConfigItem[]>('/api/admin/configs')
}

export function getTaskLogs(taskId: number): Promise<TaskLogItem[]> {
  if (USE_MOCK) return mockApi.getTaskLogs(taskId)
  return get<TaskLogItem[]>(`/api/admin/tasks/${taskId}/logs`)
}
