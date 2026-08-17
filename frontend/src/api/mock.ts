/**
 * Mock 模式内存实现（VITE_USE_MOCK=true 时启用）。
 * 覆盖契约全部 REST 接口 + WebSocket 时序回放（API 文档 §8.4），
 * 演示案例取自 designs/workspace.png 的「护肤品类退款率异常归因」。
 */
import type {
  AnalysisResult,
  AttachmentBrief,
  ConfigItem,
  ConversationItem,
  CreateConversationResp,
  HistoryMessage,
  ParseStatus,
  ReloadResp,
  TaskInfo,
  TaskLogItem,
  UploadAttachmentResp,
  UserInfo,
  WsDown,
  WsTokenResp,
  WsUp,
} from '@/types'
import { ApiError } from './http'

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

function pad(n: number, w = 2): string {
  return String(n).padStart(w, '0')
}

/** ISO 8601 毫秒本地时间（与契约格式一致） */
function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

function agoIso(ms: number): string {
  return isoLocal(new Date(Date.now() - ms))
}

// ============ 内存数据 ============

let convSeq = 1006
let msgSeq = 5010
let taskSeq = 302
let attachSeq = 201
let resultSeq = 900

const MIN = 60_000
const HOUR = 3_600_000
const DAY = 86_400_000

const REFUND_SQL = `SELECT category, refund_rate, COUNT(*) AS order_count, DATE(created_at) AS date
FROM orders
WHERE category = '护肤品'
  AND created_at >= '2026-08-01'
GROUP BY DATE(created_at)
ORDER BY date DESC;`

const REFUND_SQL_SUMMARY = '返回 7 行 · 退款率均值 6.4% · 峰值日期 2026-08-05'

/** 流式第一段（工具调用前的初步分析） */
const ANSWER_PART_1 = `根据历史数据对比，上周护肤品类退款率从 **4.2%** 上升至 **8.7%**，偏离正常波动范围（±1.2%）。主要异常集中在两个维度：

1. **退款原因分布变化**：「未收到货」占比从 12% 上升至 35%
2. **时间集中度**：异常集中在 8月5日—8月8日，期间退款率峰值达 **14.3%**

需要进一步定位具体 SKU 和物流链路问题。`

/** 流式第二段（工具调用后的归因结论） */
const ANSWER_PART_2 = `进一步查询显示：8月5日—8月8日期间，**W3 仓库（华南）发货延迟率上升至 28%**，直接引发「未收到货」类退款激增。

**归因结论**：本次退款率异常主要由 W3 仓库暴雨导致的发货延迟驱动，该因素可解释约 **68%** 的异常增量。受影响 SKU 共 23 个（退货 >20 单），其中 **SKU-A1023** 贡献最大，占类目退款量的 31%。

结构化归因报告已生成，可在右侧面板查看完整结论与建议。`

function buildRefundResult(): AnalysisResult {
  return {
    problem_definition:
      '定位上周（8月5日—8月8日）护肤品类退款率从 4.2% 异常上升至 8.7% 的核心驱动因素与影响范围',
    key_metrics: [
      { metric_name: '退款率（周均值）', metric_value: 8.7, metric_unit: '%', metric_period: '近7天' },
      { metric_name: '退款率（峰值）', metric_value: 14.3, metric_unit: '%', metric_period: '8月5日' },
      { metric_name: '环比变化', metric_value: '+4.5', metric_unit: 'pp', metric_period: '对比前一周' },
      { metric_name: '异常 SKU 数量', metric_value: 23, metric_unit: '个', metric_period: '退货 >20 单' },
    ],
    evidence_list: [
      {
        source_type: 'sql',
        source_name: '订单数据',
        evidence_text: '护肤品类退款订单量周同比增长 187%，8月5日达峰值',
        related_metric: '退款率（周均值）',
        confidence: 'high',
      },
      {
        source_type: 'sql',
        source_name: '物流数据',
        evidence_text: '8月5日—8月8日 W3 仓库发货延迟率升至 28%，与退款峰值窗口完全重合',
        related_metric: '退款率（峰值）',
        confidence: 'high',
      },
      {
        source_type: 'text',
        source_name: '客服记录',
        evidence_text: '「未收到货」投诉占比由 12% 升至 35%，集中于 W3 仓库覆盖区域',
        related_metric: '环比变化',
        confidence: 'medium',
      },
      {
        source_type: 'text',
        source_name: '供应商反馈',
        evidence_text: 'W3 仓库因暴雨天气导致部分批次发货延迟',
        related_metric: '退款率（周均值）',
        confidence: 'low',
      },
    ],
    conclusion_text:
      '本次退款率异常主要由 W3 仓库发货延迟导致。8月5日—8月8日期间，W3 仓库因暴雨天气导致发货延迟率上升至 28%，直接引发「未收到货」退款激增。该因素可解释约 68% 的异常增量；其余增量与 SKU-A1023 的「描述不符」投诉相关，建议结合客服工单进一步复核。',
    missing_data_text: `- W3 仓库天气恢复后的发货恢复时间表
- 受影响 SKU 级别的退货原因分布
- 同类天气事件的历史对照数据`,
    next_action_text: `1. 联系 W3 仓库运营方，获取恢复时间表和补偿方案
2. 对受影响的订单进行主动沟通，降低客诉升级风险
3. 评估是否需要临时调整该区域的配送策略
4. 建立天气预警机制，在类似事件前触发应急预案`,
    result_markdown: `# 经营归因分析报告

## 问题定义
定位上周（8月5日—8月8日）护肤品类退款率从 4.2% 异常上升至 8.7% 的核心驱动因素与影响范围。

## 关键指标
| 指标 | 数值 | 单位 | 口径 |
| --- | --- | --- | --- |
| 退款率（周均值） | 8.7 | % | 近7天 |
| 退款率（峰值） | 14.3 | % | 8月5日 |
| 环比变化 | +4.5 | pp | 对比前一周 |
| 异常 SKU 数量 | 23 | 个 | 退货 >20 单 |

## 证据列表
- **[高] 订单数据**：护肤品类退款订单量周同比增长 187%，8月5日达峰值
- **[高] 物流数据**：8月5日—8月8日 W3 仓库发货延迟率升至 28%，与退款峰值窗口完全重合
- **[中] 客服记录**：「未收到货」投诉占比由 12% 升至 35%，集中于 W3 仓库覆盖区域
- **[低] 供应商反馈**：W3 仓库因暴雨天气导致部分批次发货延迟

## 归因结论
本次退款率异常主要由 W3 仓库发货延迟导致。8月5日—8月8日期间，W3 仓库因暴雨天气导致发货延迟率上升至 28%，直接引发「未收到货」退款激增。该因素可解释约 68% 的异常增量；其余增量与 SKU-A1023 的「描述不符」投诉相关，建议结合客服工单进一步复核。

## 待补充数据
- W3 仓库天气恢复后的发货恢复时间表
- 受影响 SKU 级别的退货原因分布
- 同类天气事件的历史对照数据

## 下一步建议
1. 联系 W3 仓库运营方，获取恢复时间表和补偿方案
2. 对受影响的订单进行主动沟通，降低客诉升级风险
3. 评估是否需要临时调整该区域的配送策略
4. 建立天气预警机制，在类似事件前触发应急预案
`,
    exported: true,
  }
}

interface MockAttachment extends AttachmentBrief {
  conversation_id: number
  error_message?: string
}

const conversations: ConversationItem[] = [
  { conversation_id: 1001, title: '8月退款率异常归因', status: 'active', last_message_at: agoIso(2 * MIN) },
  { conversation_id: 1002, title: '商品目录优化分析', status: 'active', last_message_at: agoIso(15 * MIN) },
  { conversation_id: 1003, title: 'Q3营销活动ROI归因', status: 'active', last_message_at: agoIso(2 * HOUR) },
  { conversation_id: 1004, title: '供应链成本异常追踪', status: 'active', last_message_at: agoIso(DAY) },
  { conversation_id: 1005, title: '新用户转化漏斗诊断', status: 'active', last_message_at: agoIso(DAY + 3 * HOUR) },
  { conversation_id: 1006, title: '库存周转率分析', status: 'active', last_message_at: agoIso(3 * DAY) },
]

const messagesByConv: Record<number, HistoryMessage[]> = {
  1001: [
    {
      message_id: 5001,
      role: 'user',
      message_type: 'text',
      content: '为什么上周护肤品类的退款率明显上升？',
      tool_name: null,
      tool_status: null,
      task_id: 301,
      attachments: [
        { attachment_id: 201, file_name: 'orders_2026Q3.csv', file_type: 'csv', file_size: 20480, parse_status: 'ready' },
      ],
      created_at: agoIso(6 * MIN),
    },
    {
      message_id: 5002,
      role: 'assistant',
      message_type: 'text',
      content: ANSWER_PART_1,
      tool_name: null,
      tool_status: null,
      task_id: 301,
      attachments: [],
      created_at: agoIso(5 * MIN),
    },
    {
      message_id: 5003,
      role: 'tool',
      message_type: 'tool_call',
      content: `${REFUND_SQL}\n\n${REFUND_SQL_SUMMARY}`,
      tool_name: 'sql_query',
      tool_status: 'success',
      task_id: 301,
      attachments: [],
      created_at: agoIso(4 * MIN + 30_000),
    },
    {
      message_id: 5004,
      role: 'assistant',
      message_type: 'text',
      content: ANSWER_PART_2,
      tool_name: null,
      tool_status: null,
      task_id: 301,
      attachments: [],
      created_at: agoIso(4 * MIN),
    },
    {
      message_id: 5005,
      role: 'assistant',
      message_type: 'result',
      content: '归因分析报告已生成',
      tool_name: null,
      tool_status: null,
      task_id: 301,
      attachments: [],
      created_at: agoIso(3 * MIN + 30_000),
    },
    {
      message_id: 5006,
      role: 'user',
      message_type: 'text',
      content: '受影响的 SKU 主要有哪些？',
      tool_name: null,
      tool_status: null,
      task_id: 302,
      attachments: [],
      created_at: agoIso(2 * MIN + 30_000),
    },
    {
      message_id: 5007,
      role: 'assistant',
      message_type: 'text',
      content:
        '受影响 SKU 共 **23 个**（退货 >20 单），按退款量排序 Top 3：\n\n1. **SKU-A1023**（保湿面霜 50g）：周退款 47 单，占类目 31%，主因「描述不符」与发货延迟叠加\n2. **SKU-A2056**（氨基酸洁面乳）：周退款 29 单，占类目 19%，主因发货延迟\n3. **SKU-B0912**（防晒喷雾）：周退款 21 单，占类目 14%，主因发货延迟\n\n完整清单已纳入归因报告，可在右侧面板查看。',
      tool_name: null,
      tool_status: null,
      task_id: 302,
      attachments: [],
      created_at: agoIso(2 * MIN),
    },
  ],
  1002: [
    {
      message_id: 5101,
      role: 'user',
      message_type: 'text',
      content: '哪些商品长期零销量，可以考虑下架？',
      tool_name: null,
      tool_status: null,
      task_id: null,
      attachments: [],
      created_at: agoIso(16 * MIN),
    },
    {
      message_id: 5102,
      role: 'assistant',
      message_type: 'text',
      content: '近 90 天零销量商品共 **41 个**，占在售商品的 6.8%。其中 28 个为上架超过 180 天的长尾 SKU，建议优先列入下架评审清单。',
      tool_name: null,
      tool_status: null,
      task_id: null,
      attachments: [],
      created_at: agoIso(15 * MIN),
    },
  ],
}

const attachments: MockAttachment[] = [
  { attachment_id: 201, conversation_id: 1001, file_name: 'orders_2026Q3.csv', file_type: 'csv', file_size: 20480, parse_status: 'ready' },
]

const tasks: Record<number, TaskInfo> = {
  301: {
    task_id: 301,
    task_status: 'success',
    current_step: null,
    started_at: agoIso(6 * MIN),
    finished_at: agoIso(3 * MIN + 30_000),
    error_message: null,
  },
  302: {
    task_id: 302,
    task_status: 'success',
    current_step: null,
    started_at: agoIso(2 * MIN + 30_000),
    finished_at: agoIso(2 * MIN),
    error_message: null,
  },
}

const results: Record<number, AnalysisResult> = {
  301: buildRefundResult(),
}

const configs: ConfigItem[] = [
  { config_group: 'llm', config_key: 'llm.provider', config_value: 'openai', description: 'LLM 供应商（OpenAI 兼容协议）', updated_at: agoIso(2 * DAY) },
  { config_group: 'llm', config_key: 'llm.base_url', config_value: 'https://api.example.com/v1', description: 'LLM 网关地址', updated_at: agoIso(2 * DAY) },
  { config_group: 'llm', config_key: 'llm.model', config_value: 'gpt-4o-mini', description: '默认模型', updated_at: agoIso(5 * HOUR) },
  { config_group: 'llm', config_key: 'llm.temperature', config_value: '0.2', description: '采样温度', updated_at: agoIso(2 * DAY) },
  { config_group: 'agent', config_key: 'agent.task_timeout_seconds', config_value: '120', description: '任务超时时间（30~600 秒）', updated_at: agoIso(3 * DAY) },
  { config_group: 'agent', config_key: 'agent.max_tool_rounds', config_value: '20', description: '单任务最大工具调用轮数（5~50）', updated_at: agoIso(3 * DAY) },
  { config_group: 'agent', config_key: 'agent.context_rounds', config_value: '30', description: '上下文携带的最大对话轮数（5~100）', updated_at: agoIso(3 * DAY) },
  { config_group: 'datasource', config_key: 'datasource.duckdb_path', config_value: 'data/analytics.duckdb', description: 'DuckDB 分析库文件路径', updated_at: agoIso(10 * DAY) },
  { config_group: 'datasource', config_key: 'datasource.upload_dir', config_value: 'uploads', description: '附件存储根目录', updated_at: agoIso(10 * DAY) },
  { config_group: 'datasource', config_key: 'datasource.workspace_quota_mb', config_value: '50', description: '会话工作区空间上限（MB）', updated_at: agoIso(10 * DAY) },
  { config_group: 'feature', config_key: 'feature.attachment_enabled', config_value: 'true', description: '附件功能开关', updated_at: agoIso(10 * DAY) },
  { config_group: 'feature', config_key: 'feature.export_enabled', config_value: 'true', description: '结果导出功能开关', updated_at: agoIso(10 * DAY) },
]

// ============ Mock WebSocket ============

/** useWebSocket 使用的最小 socket 接口（与 WebSocket 子集对齐） */
export interface WsLike {
  send(data: string): void
  close(): void
  onopen: (() => void) | null
  onmessage: ((ev: { data: string }) => void) | null
  onclose: ((ev: { code: number }) => void) | null
  onerror: (() => void) | null
}

const openSockets = new Set<MockSocket>()

function broadcastAttachmentStatus(conversationId: number, attachmentId: number, status: ParseStatus): void {
  for (const s of openSockets) {
    if (s.conversationId === conversationId) {
      s.emit({ type: 'attachment_status', attachment_id: attachmentId, parse_status: status })
    }
  }
}

class MockSocket implements WsLike {
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: { code: number }) => void) | null = null
  onerror: (() => void) | null = null

  private timers: ReturnType<typeof setTimeout>[] = []
  private closed = false

  constructor(public conversationId: number) {
    openSockets.add(this)
    this.later(() => this.onopen?.(), 80)
  }

  later(fn: () => void, ms: number): void {
    const t = setTimeout(() => {
      if (!this.closed) fn()
    }, ms)
    this.timers.push(t)
  }

  emit(msg: WsDown): void {
    this.onmessage?.({ data: JSON.stringify(msg) })
  }

  send(data: string): void {
    let msg: WsUp
    try {
      msg = JSON.parse(data) as WsUp
    } catch {
      return
    }
    if (msg.type === 'ping') {
      this.later(() => this.emit({ type: 'pong' }), 40)
    } else if (msg.type === 'user_message') {
      this.replayAnalysis(msg.text, msg.attachment_ids)
    } else if (msg.type === 'cancel') {
      this.cancelRun(msg.task_id)
    }
  }

  close(): void {
    if (this.closed) return
    this.closed = true
    this.timers.forEach(clearTimeout)
    openSockets.delete(this)
    this.later0(() => this.onclose?.({ code: 1000 }))
  }

  private later0(fn: () => void): void {
    setTimeout(fn, 30)
  }

  /** 按 API 文档 §8.4 时序回放一轮完整分析 */
  private replayAnalysis(text: string, attachmentIds: number[]): void {
    const convId = this.conversationId
    const taskId = ++taskSeq
    const messageId = ++msgSeq
    const resultId = ++resultSeq
    const now = new Date()

    // 用户消息入历史（切换会话/刷新后可回放）
    const convAttachments = attachmentIds
      .map((id) => attachments.find((a) => a.attachment_id === id))
      .filter((a): a is MockAttachment => !!a)
      .map(({ attachment_id, file_name, file_type, file_size, parse_status }) => ({
        attachment_id,
        file_name,
        file_type,
        file_size,
        parse_status,
      }))
    ;(messagesByConv[convId] ??= []).push({
      message_id: messageId - 1,
      role: 'user',
      message_type: 'text',
      content: text,
      tool_name: null,
      tool_status: null,
      task_id: taskId,
      attachments: convAttachments,
      created_at: isoLocal(now),
    })
    tasks[taskId] = {
      task_id: taskId,
      task_status: 'queued',
      current_step: null,
      started_at: isoLocal(now),
      finished_at: null,
      error_message: null,
    }
    const conv = conversations.find((c) => c.conversation_id === convId)
    if (conv) conv.last_message_at = isoLocal(now)

    // 把长文本切成小片做流式回放
    const chunk = (s: string, size: number): string[] => {
      const out: string[] = []
      for (let i = 0; i < s.length; i += size) out.push(s.slice(i, i + size))
      return out
    }
    const part1 = chunk(ANSWER_PART_1, 12)
    const part2 = chunk(ANSWER_PART_2, 12)

    const steps: Array<[number, () => void]> = []
    let t = 200
    const at = (ms: number, fn: () => void) => {
      steps.push([ms, fn])
    }

    at(t, () => this.emit({ type: 'message_start', task_id: taskId, conversation_id: convId, message_id: messageId }))
    at((t += 300), () => {
      tasks[taskId]!.task_status = 'queued'
      this.emit({ type: 'task_status', task_id: taskId, task_status: 'queued', current_step: null })
    })
    at((t += 500), () => {
      tasks[taskId]!.task_status = 'running'
      tasks[taskId]!.current_step = 'planning'
      this.emit({ type: 'task_status', task_id: taskId, task_status: 'running', current_step: 'planning' })
    })
    for (const c of part1) {
      at((t += 90), () => this.emit({ type: 'message_delta', task_id: taskId, message_id: messageId, delta_text: c }))
    }
    at((t += 400), () => {
      tasks[taskId]!.current_step = 'querying'
      this.emit({ type: 'task_status', task_id: taskId, task_status: 'running', current_step: 'querying' })
      this.emit({ type: 'tool_start', task_id: taskId, tool_name: 'sql_query', tool_input_summary: REFUND_SQL })
    })
    at((t += 1600), () =>
      this.emit({
        type: 'tool_finish',
        task_id: taskId,
        tool_name: 'sql_query',
        tool_status: 'success',
        tool_result_summary: REFUND_SQL_SUMMARY,
      }),
    )
    for (const c of part2) {
      at((t += 90), () => this.emit({ type: 'message_delta', task_id: taskId, message_id: messageId, delta_text: c }))
    }
    at((t += 300), () => {
      tasks[taskId]!.current_step = 'summarizing'
      this.emit({ type: 'task_status', task_id: taskId, task_status: 'running', current_step: 'summarizing' })
    })
    at((t += 900), () => {
      results[taskId] = buildRefundResult()
      this.emit({ type: 'result_ready', task_id: taskId, result_id: resultId })
    })
    at((t += 300), () => {
      tasks[taskId]!.task_status = 'success'
      tasks[taskId]!.current_step = null
      this.emit({ type: 'task_status', task_id: taskId, task_status: 'success', current_step: null })
    })
    at((t += 200), () => {
      const finished = isoLocal(new Date())
      tasks[taskId]!.finished_at = finished
      // 落历史：assistant 正文 + 工具块 + 结果卡片
      ;(messagesByConv[convId] ??= []).push(
        {
          message_id: messageId,
          role: 'assistant',
          message_type: 'text',
          content: `${ANSWER_PART_1}\n\n${ANSWER_PART_2}`,
          tool_name: null,
          tool_status: null,
          task_id: taskId,
          attachments: [],
          created_at: finished,
        },
        {
          message_id: ++msgSeq,
          role: 'tool',
          message_type: 'tool_call',
          content: `${REFUND_SQL}\n\n${REFUND_SQL_SUMMARY}`,
          tool_name: 'sql_query',
          tool_status: 'success',
          task_id: taskId,
          attachments: [],
          created_at: finished,
        },
        {
          message_id: ++msgSeq,
          role: 'assistant',
          message_type: 'result',
          content: '归因分析报告已生成',
          tool_name: null,
          tool_status: null,
          task_id: taskId,
          attachments: [],
          created_at: finished,
        },
      )
      const c = conversations.find((x) => x.conversation_id === convId)
      if (c) c.last_message_at = finished
      this.emit({ type: 'done', task_id: taskId, finished_at: finished })
    })

    this.timers.push(...steps.map(([ms, fn]) => setTimeout(() => !this.closed && fn(), ms)))
  }

  private cancelRun(taskId: number): void {
    this.timers.forEach(clearTimeout)
    this.timers = []
    const task = tasks[taskId]
    if (task) {
      task.task_status = 'cancelled'
      task.current_step = null
      task.finished_at = isoLocal(new Date())
    }
    this.later(() => this.emit({ type: 'task_status', task_id: taskId, task_status: 'cancelled', current_step: null }), 150)
    this.later(() => this.emit({ type: 'done', task_id: taskId, finished_at: isoLocal(new Date()) }), 350)
  }
}

export function createMockSocket(conversationId: number): WsLike {
  return new MockSocket(conversationId)
}

// ============ Mock REST ============

/** 附件解析状态推进 + WS 广播 */
function scheduleParse(conversationId: number, attachmentId: number): void {
  const setStatus = (status: ParseStatus) => {
    const att = attachments.find((a) => a.attachment_id === attachmentId)
    if (att) att.parse_status = status
    // 同步消息里聚合的附件状态
    for (const m of messagesByConv[conversationId] ?? []) {
      const brief = m.attachments.find((b) => b.attachment_id === attachmentId)
      if (brief) brief.parse_status = status
    }
    broadcastAttachmentStatus(conversationId, attachmentId, status)
  }
  setTimeout(() => setStatus('parsing'), 800)
  setTimeout(() => setStatus('ready'), 2600)
}

export const mockApi = {
  // ---- 认证 ----
  async getMe(): Promise<UserInfo> {
    await sleep(120)
    return { user_id: 1, username: 'admin', display_name: '系统管理员', role: 'admin' }
  },

  async logout(): Promise<{ ok: boolean }> {
    await sleep(80)
    return { ok: true }
  },

  // ---- 会话 ----
  async listConversations(): Promise<ConversationItem[]> {
    await sleep(150)
    return [...conversations].sort((a, b) => (b.last_message_at ?? '').localeCompare(a.last_message_at ?? ''))
  },

  async createConversation(title?: string): Promise<CreateConversationResp> {
    await sleep(150)
    const id = ++convSeq
    const item: ConversationItem = {
      conversation_id: id,
      title: title?.trim() || '新分析',
      status: 'active',
      last_message_at: isoLocal(new Date()),
    }
    conversations.push(item)
    messagesByConv[id] = []
    return { conversation_id: id, title: item.title, status: item.status }
  },

  async deleteConversations(ids: number[]): Promise<{ deleted_count: number }> {
    await sleep(200)
    let count = 0
    for (const id of ids) {
      const i = conversations.findIndex((c) => c.conversation_id === id)
      if (i >= 0) {
        conversations.splice(i, 1)
        delete messagesByConv[id]
        count += 1
      }
    }
    return { deleted_count: count }
  },

  async renameConversation(id: number, title: string): Promise<{ conversation_id: number; title: string }> {
    await sleep(120)
    const conv = conversations.find((c) => c.conversation_id === id)
    if (!conv) throw new ApiError(40401, '会话不存在或已删除')
    if (!title.trim() || title.length > 200) throw new ApiError(40001, '标题不能为空且不超过 200 字')
    conv.title = title.trim()
    return { conversation_id: id, title: conv.title }
  },

  async listMessages(conversationId: number): Promise<HistoryMessage[]> {
    await sleep(200)
    const msgs = messagesByConv[conversationId]
    if (!msgs) throw new ApiError(40401, '会话不存在或已删除')
    // 已上传但尚未随消息发送的附件，聚合到最后一条用户消息上（轮询解析状态用）
    const sentIds = new Set(msgs.flatMap((m) => m.attachments.map((a) => a.attachment_id)))
    const pendingExtras = attachments
      .filter((a) => a.conversation_id === conversationId && !sentIds.has(a.attachment_id))
      .map(({ attachment_id, file_name, file_type, file_size, parse_status }) => ({
        attachment_id,
        file_name,
        file_type,
        file_size,
        parse_status,
      }))
    const cloned = msgs.map((m) => ({ ...m, attachments: m.attachments.map((a) => ({ ...a })) }))
    if (pendingExtras.length > 0) {
      const lastUser = [...cloned].reverse().find((m) => m.role === 'user')
      if (lastUser) {
        lastUser.attachments.push(...pendingExtras)
      } else {
        cloned.push({
          message_id: ++msgSeq,
          role: 'user',
          message_type: 'text',
          content: '',
          tool_name: null,
          tool_status: null,
          task_id: null,
          attachments: pendingExtras,
          created_at: isoLocal(new Date()),
        })
      }
    }
    return cloned
  },

  // ---- 附件 ----
  async uploadAttachment(
    conversationId: number,
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<UploadAttachmentResp> {
    // 模拟上传进度
    for (let p = 10; p <= 100; p += 15) {
      await sleep(80)
      onProgress?.(p)
    }
    const id = ++attachSeq
    const ext = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : ''
    attachments.push({
      attachment_id: id,
      conversation_id: conversationId,
      file_name: file.name,
      file_type: ext,
      file_size: file.size,
      parse_status: 'pending',
    })
    scheduleParse(conversationId, id)
    return { attachment_id: id, file_name: file.name, file_path: `uploads/1/${conversationId}/${file.name}`, parse_status: 'pending' }
  },

  async deleteAttachment(attachmentId: number): Promise<{ deleted: boolean }> {
    await sleep(120)
    const i = attachments.findIndex((a) => a.attachment_id === attachmentId)
    if (i < 0) throw new ApiError(40401, '附件不存在或已删除')
    if (attachments[i]!.parse_status === 'parsing') throw new ApiError(40001, '附件解析中，请稍后删除')
    attachments.splice(i, 1)
    for (const msgs of Object.values(messagesByConv)) {
      for (const m of msgs) {
        const j = m.attachments.findIndex((a) => a.attachment_id === attachmentId)
        if (j >= 0) m.attachments.splice(j, 1)
      }
    }
    return { deleted: true }
  },

  async downloadAttachment(attachmentId: number): Promise<{ blob: Blob; filename: string }> {
    await sleep(120)
    const att = attachments.find((a) => a.attachment_id === attachmentId)
    if (!att) throw new ApiError(40401, '附件不存在或已删除')
    const content = `Mock 附件内容：${att.file_name}\n（演示环境生成的占位文件）\n`
    return { blob: new Blob([content], { type: 'text/plain;charset=utf-8' }), filename: att.file_name }
  },

  // ---- WS 令牌 ----
  async getWsToken(conversationId: number): Promise<WsTokenResp> {
    await sleep(60)
    if (!conversations.find((c) => c.conversation_id === conversationId)) {
      throw new ApiError(40401, '会话不存在或已删除')
    }
    return { websocket_token: `mock-token-${conversationId}-${Date.now()}`, expires_in: 60 }
  },

  // ---- 任务与结果 ----
  async getTask(taskId: number): Promise<TaskInfo> {
    await sleep(100)
    const task = tasks[taskId]
    if (!task) throw new ApiError(40401, '任务不存在')
    return { ...task }
  },

  async getResult(taskId: number): Promise<AnalysisResult> {
    await sleep(150)
    const result = results[taskId]
    if (!result) throw new ApiError(40401, '任务未产生结果')
    return result
  },

  async downloadResult(taskId: number): Promise<{ blob: Blob; filename: string }> {
    await sleep(150)
    const result = results[taskId]
    if (!result) throw new ApiError(40401, '任务无结果')
    return {
      blob: new Blob([result.result_markdown], { type: 'text/markdown;charset=utf-8' }),
      filename: `result_${taskId}.md`,
    }
  },

  // ---- 管理 ----
  async listConfigs(): Promise<ConfigItem[]> {
    await sleep(150)
    return configs.map((c) => ({ ...c }))
  },

  async reloadConfigs(): Promise<ReloadResp> {
    await sleep(400)
    return { status: 'ok', message: `重载 ${configs.length} 项配置，LLM 客户端已重建` }
  },

  async getTaskLogs(taskId: number): Promise<TaskLogItem[]> {
    await sleep(150)
    const base = Date.now() - 95_000
    const at = (offsetMs: number) => isoLocal(new Date(base + offsetMs))
    return [
      { log_level: 'info', log_type: 'status', log_content: `task ${taskId} queued → running`, created_at: at(0) },
      { log_level: 'info', log_type: 'llm_call', log_content: 'agent_node 第 1 轮调用开始（model=gpt-4o-mini）', created_at: at(1200) },
      { log_level: 'info', log_type: 'tool_exec', log_content: 'sql_query 执行成功：返回 7 行，耗时 1.2s', created_at: at(5800) },
      { log_level: 'warn', log_type: 'tool_exec', log_content: 'sql_query 第 1 次被拒：未包裹 LIMIT，已自动追加 LIMIT 100', created_at: at(5900) },
      { log_level: 'info', log_type: 'llm_call', log_content: 'agent_node 第 2 轮调用开始', created_at: at(6400) },
      { log_level: 'info', log_type: 'status', log_content: 'current_step: planning → querying', created_at: at(9000) },
      { log_level: 'info', log_type: 'status', log_content: 'current_step: querying → summarizing', created_at: at(32000) },
      { log_level: 'info', log_type: 'output', log_content: '六段结构化输出校验通过，落库 analysis_results', created_at: at(40000) },
      { log_level: 'error', log_type: 'llm_call', log_content: '（示例）LLM 调用超时 1 次，已按退避策略重试成功', created_at: at(41000) },
      { log_level: 'info', log_type: 'status', log_content: `task ${taskId} running → success`, created_at: at(42000) },
    ]
  },
}
