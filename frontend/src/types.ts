/**
 * 类型定义：严格对应 docs/API-接口设计文档.md（统一响应包、DTO、WS 协议）。
 * 字段一律 snake_case，与线报文保持一致。
 */

// ============ 通用 ============

/** 统一响应包（2.2） */
export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

// ============ 认证（§3 + 待补充接口） ============

/**
 * 当前用户信息。
 * 注意：契约暂无「获取当前用户」接口，前端约定调用 GET /api/auth/me，
 * 期望返回本结构（待后端补充，详见 README「契约缺口」）。
 */
export interface UserInfo {
  user_id: number
  username: string
  display_name: string
  role: string // 'admin' | 'user' 等
}

// ============ 会话（§4） ============

export interface ConversationItem {
  conversation_id: number
  title: string
  status: string // 'active' | 'archived'
  last_message_at: string | null
}

export interface CreateConversationResp {
  conversation_id: number
  title: string
  status: string
}

// ============ 附件（§5） ============

export type ParseStatus = 'pending' | 'parsing' | 'ready' | 'failed'

export interface AttachmentBrief {
  attachment_id: number
  file_name: string
  file_type: string
  file_size: number
  parse_status: ParseStatus
}

export interface UploadAttachmentResp {
  attachment_id: number
  file_name: string
  file_path: string
  parse_status: ParseStatus
}

// ============ 历史消息（§4.5） ============

export type MessageRole = 'user' | 'assistant' | 'tool'
export type MessageType = 'text' | 'tool_call' | 'result'
export type ToolStatus = 'success' | 'failed'

export interface HistoryMessage {
  message_id: number
  role: MessageRole | string
  message_type: MessageType | string
  content: string
  tool_name: string | null
  tool_status: ToolStatus | null
  task_id: number | null
  attachments: AttachmentBrief[]
  created_at: string
}

// ============ 任务（§6.1、§8） ============

export type TaskStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelled'
export type CurrentStep = 'planning' | 'querying' | 'summarizing'

export interface TaskInfo {
  task_id: number
  task_status: TaskStatus
  current_step: CurrentStep | null
  started_at: string | null
  finished_at: string | null
  error_message: string | null
}

// ============ 结果（§6.2） ============

export interface KeyMetric {
  metric_name: string
  metric_value: number | string
  metric_unit: string
  metric_period: string
}

export type Confidence = 'high' | 'medium' | 'low'

export interface EvidenceItem {
  source_type: string
  source_name: string
  evidence_text: string
  related_metric: string
  confidence: Confidence | string
}

export interface AnalysisResult {
  problem_definition: string
  key_metrics: KeyMetric[]
  evidence_list: EvidenceItem[]
  conclusion_text: string
  missing_data_text: string
  next_action_text: string
  result_markdown: string
  exported: boolean
}

// ============ 管理（§7 + 待补充接口） ============

export interface ReloadResp {
  status: 'ok' | 'error'
  message: string
}

export interface TaskLogItem {
  log_level: 'info' | 'warn' | 'error' | string
  log_type: string
  log_content: string
  created_at: string
}

/**
 * 系统配置项。
 * 注意：契约暂无配置读取接口，前端约定调用 GET /api/admin/configs，
 * 期望返回本结构数组（待后端补充，详见 README「契约缺口」）。
 */
export interface ConfigItem {
  config_group: string // llm / agent / datasource / feature
  config_key: string
  config_value: string
  description: string
  updated_at: string
}

// ============ WebSocket（§8） ============

export interface WsTokenResp {
  websocket_token: string
  expires_in: number
}

/** 上行消息（客户端 → 服务端，§8.2） */
export type WsUp =
  | { type: 'user_message'; text: string; attachment_ids: number[] }
  | { type: 'cancel'; task_id: number }
  | { type: 'ping' }

/** 下行消息（服务端 → 客户端，§8.3） */
export type WsDown =
  | { type: 'message_start'; task_id: number; conversation_id: number; message_id: number }
  | { type: 'message_delta'; task_id: number; message_id: number; delta_text: string }
  | { type: 'tool_start'; task_id: number; tool_name: string; tool_input_summary: string }
  | {
      type: 'tool_finish'
      task_id: number
      tool_name: string
      tool_status: ToolStatus
      tool_result_summary: string
    }
  | { type: 'task_status'; task_id: number; task_status: TaskStatus; current_step: CurrentStep | null }
  | { type: 'result_ready'; task_id: number; result_id: number }
  | { type: 'error'; task_id: number; error_code: number; error_message: string }
  | { type: 'done'; task_id: number; finished_at: string }
  | { type: 'attachment_status'; attachment_id: number; parse_status: ParseStatus }
  | { type: 'pong' }
