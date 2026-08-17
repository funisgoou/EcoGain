import axios, { AxiosError, type AxiosResponse } from 'axios'

import type { ApiEnvelope } from '@/types'

/** 业务错误：code 与契约 §2.3 一致；code=-1 表示网络层异常 */
export class ApiError extends Error {
  code: number

  constructor(code: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError
}

/** 40101 兜底跳转（由 auth store 注册，避免 http 层反向依赖 router） */
let unauthorizedHandler: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void): void {
  unauthorizedHandler = fn
}

function handleUnauthorized(): void {
  const path = window.location.pathname
  if (path !== '/login' && path !== '/auth/callback') {
    unauthorizedHandler?.()
  }
}

export const http = axios.create({
  baseURL: '/',
  withCredentials: true, // 契约：Cookie 会话 ecogain_session
  timeout: 30_000,
})

/** 解包统一响应包：code!==0 抛业务错误；blob 响应原样透传 */
function unwrap<T>(resp: AxiosResponse<ApiEnvelope<T>>): T {
  if (resp.config.responseType === 'blob') return resp as unknown as T
  const body = resp.data
  if (body && typeof body === 'object' && 'code' in body) {
    if (body.code === 0) return body.data
    if (body.code === 40101) handleUnauthorized()
    throw new ApiError(body.code, body.message)
  }
  return body as unknown as T
}

async function unwrapError(error: unknown): Promise<never> {
  if (error instanceof ApiError) throw error
  const err = error as AxiosError<ApiEnvelope<unknown>>
  const resp = err.response
  if (resp) {
    let body = resp.data
    // 下载接口（responseType=blob）的错误体也是 JSON 统一包，需解析后取业务码
    if (body instanceof Blob) {
      try {
        body = JSON.parse(await body.text()) as ApiEnvelope<unknown>
      } catch {
        body = undefined as unknown as ApiEnvelope<unknown>
      }
    }
    if (body && typeof body === 'object' && 'code' in body && typeof body.code === 'number') {
      if (body.code === 40101) handleUnauthorized()
      throw new ApiError(body.code, body.message ?? '')
    }
    // 非统一包响应（如接口未实现的裸 404）：以 HTTP 状态码表达
    throw new ApiError(resp.status, resp.statusText || '请求失败')
  }
  throw new ApiError(-1, '网络异常，请检查连接')
}

http.interceptors.response.use(unwrap, unwrapError)
