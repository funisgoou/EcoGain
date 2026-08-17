/** 契约 §2.3 错误码的友好文案（服务端 message 优先，此处为兜底） */
const ERROR_TEXT: Record<number, string> = {
  40001: '请求参数有误，请检查输入',
  40002: '附件格式或大小不合规（仅支持 csv/xlsx/txt/md，≤10MB）',
  40101: '登录态已失效，请重新登录',
  40301: '没有权限执行此操作',
  40401: '资源不存在或已被删除',
  40901: '当前会话已有运行中的任务，请稍候',
  42901: '并发任务过多，请稍后重试',
  50001: '模型服务异常，请稍后重试',
  50002: '工具执行被安全策略拒绝',
  50003: '任务执行超时',
  50000: '服务器内部错误，请稍后重试',
}

export function friendlyError(code: number, message?: string): string {
  if (message) return message
  return ERROR_TEXT[code] ?? `未知错误（${code}）`
}
