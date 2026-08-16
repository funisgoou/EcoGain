# 经营归因分析系统 API 接口设计文档

## 1. 文档信息

| 项 | 内容 |
| --- | --- |
| 文档名称 | API 接口设计文档（前后端对接契约） |
| 文档版本 | v1.0 |
| 创建日期 | 2026-08-16 |
| 上游文档 | PRD v1.1（附录 C/D 为需求级基线）、SPEC v1.0（实现级补充） |
| 定位 | **前后端接口唯一契约源**：字段类型、必填、示例、错误场景以本文档为准；PRD 附录 C/D 与本文档冲突时以本文档为准 |
| 数据 companion | `docs/DATA-数据设计文档.md`（表结构与存储对象） |

本文档整合并细化三处既有接口约定：PRD 附录 C（REST 清单）、PRD 附录 D（WS 协议）、SPEC 的实现扩展（下载接口、日志接口、attachment_status 消息）。

## 2. 通用约定

### 2.1 基础信息

| 项 | 约定 |
| --- | --- |
| Base URL | 同源部署经 nginx 反代（生产 `/`）；本地联调 `http://localhost:8000` |
| Content-Type | `application/json; charset=utf-8`（上传接口为 `multipart/form-data`，下载接口为文件流） |
| 认证方式 | Cookie 会话：`ecogain_session`（HttpOnly、SameSite=Lax、24h 有效）；除标注「无需认证」外，所有接口需携带 |
| 跨域联调 | 后端开发模式开启 CORS 允许 `http://localhost:5173`，前端 axios 需 `withCredentials: true` |
| 时间格式 | ISO 8601 带毫秒本地时间：`2026-08-16T10:30:00.123` |
| ID 类型 | 全部 number（BIGINT，JS 安全整数范围内） |
| 字段命名 | JSON 一律 `snake_case` |

### 2.2 统一响应包

```json
// 成功
{ "code": 0, "message": "ok", "data": { } }
// 失败（HTTP 状态码与 code 前三位一致）
{ "code": 40101, "message": "登录态无效", "data": null }
```

### 2.3 错误码表

| code | HTTP | 含义 | 典型触发 |
| --- | --- | --- | --- |
| 0 | 200/302 | 成功 | — |
| 40001 | 400 | 参数缺失/格式错误 | title 超长、conversation_id 非数字 |
| 40002 | 400 | 附件格式或大小不合规 | 非 csv/xlsx/txt/md、>10MB |
| 40101 | 401 | 未登录 / OAuth state 校验失败 | 会话过期、state 不匹配 |
| 40301 | 403 | 无权限 | 访问他人会话资源、非 admin 调管理接口、功能开关关闭 |
| 40401 | 404 | 资源不存在 | 会话/附件/任务/结果不存在或已删除 |
| 40901 | 409 | 会话已有运行中任务 | queued/running 任务存在时再发送 |
| 40902 | — | WS 令牌无效/过期/已消费（经 WS 关闭码 4401 表达，不走 HTTP） | — |
| 42901 | 429 | 并发任务超过上限（>5） | 全局 queued+running ≥ 5 |
| 50001 | 500 | LLM 调用失败 | 供应商超时/限流，重试 2 次后仍失败 |
| 50002 | 500 | 工具执行被安全策略拒绝 | SQL 非 SELECT、路径穿越、空间超限 |
| 50003 | 500 | 任务超时 | 超过 task_timeout_seconds（默认 120s） |
| 50000 | 500 | 服务器内部错误 | 未预期异常（不透出细节） |

## 3. 认证接口

### 3.1 发起授权登录

| 项 | 值 |
| --- | --- |
| `GET /auth/login` | **无需认证** |

- 行为：生成 state（60s 有效）→ `302` 跳转认证中心 `GET :8001/authorize?client_id=ecogain-web&redirect_uri={PUBLIC_BASE_URL}/auth/callback&response_type=code&state=...`
- 响应：无 JSON body，纯 302 重定向。

### 3.2 授权回调

| 项 | 值 |
| --- | --- |
| `GET /auth/callback` | **无需认证** |

**Query 参数**：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| code | string | 与 error 二选一 | 授权码 |
| state | string | 是 | CSRF 校验（携带 code 时） |
| error | string | 否 | 失败错误码（认证中心重定向回来时） |

- 成功：校验 state → code 换 token → upsert users → 设会话 Cookie → `302` 至前端 `/workbench`；
- 失败：`302` 至前端 `/auth/callback?error={code}&message={urlencoded 原因}`（由登录回调页展示 + 提供重试按钮）。

### 3.3 登出

| 项 | 值 |
| --- | --- |
| `POST /auth/logout` | 需认证 |

- 请求：无 body；
- 响应 data：`{ "ok": true }`；行为：清 Cookie + 删服务端会话。前端收到后跳 `/login`。

## 4. 会话接口

### 4.1 创建会话

| 项 | 值 |
| --- | --- |
| `POST /api/chat/create` | 需认证 |

**请求**：

```json
{ "title": "8 月退款率异常归因" }
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| title | string | 否 | ≤200 字；缺省「新分析」 |

**响应 data**：

```json
{ "conversation_id": 1001, "title": "8 月退款率异常归因", "status": "active" }
```

**错误场景**：40001（title 超 200 字）。

### 4.2 删除会话

| 项 | 值 |
| --- | --- |
| `POST /api/chat/delete` | 需认证 |

**请求**：

```json
{ "conversation_ids": [1001, 1002] }
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- |
| conversation_ids | number[] | 是 | 1~50 个 |

**响应 data**：`{ "deleted_count": 2 }`

**行为**：若会话存在 queued/running 任务，先取消再删；级联删除消息/附件/任务/结果/摘要/磁盘目录（SPEC 4.2）。

**错误场景**：40001（空数组/超 50）；40301（含非本人会话，**整批拒绝不部分执行**）。

### 4.3 重命名会话

| 项 | 值 |
| --- | --- |
| `POST /api/chat/update` | 需认证 |

**请求**：`{ "conversation_id": 1001, "title": "新标题" }`（title 必填，≤200 字）

**响应 data**：`{ "conversation_id": 1001, "title": "新标题" }`

**错误场景**：40001；40301；40401（会话不存在或已删除）。

### 4.4 会话列表

| 项 | 值 |
| --- | --- |
| `GET /api/chat/ls` | 需认证 |

**Query 参数**：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| include_archived | boolean | 否 | 默认 false；true 时附带 archived 会话（分组展示用） |

**响应 data**（数组，按 last_message_at 倒序）：

```json
[
  { "conversation_id": 1001, "title": "8 月退款率异常归因", "status": "active",
    "last_message_at": "2026-08-16T09:12:33.001" }
]
```

### 4.5 历史消息查询

| 项 | 值 |
| --- | --- |
| `GET /api/chat/ls/{conversation_id}` | 需认证 |

**响应 data**（数组，按 seq_no 升序）：

```json
[
  {
    "message_id": 5001,
    "role": "user",
    "message_type": "text",
    "content": "为什么上周护肤品类的退款率明显上升？",
    "tool_name": null,
    "tool_status": null,
    "task_id": 301,
    "attachments": [
      { "attachment_id": 201, "file_name": "refund_extra.csv", "file_type": "csv",
        "file_size": 20480, "parse_status": "ready" }
    ],
    "created_at": "2026-08-16T09:10:00.123"
  },
  {
    "message_id": 5002,
    "role": "tool",
    "message_type": "tool_call",
    "content": "SELECT category_id, COUNT(*) ... （结果摘要 23 行）",
    "tool_name": "sql_query",
    "tool_status": "success",
    "task_id": 301,
    "attachments": [],
    "created_at": "2026-08-16T09:10:05.456"
  }
]
```

> `message_type` / `tool_name` / `tool_status` / `task_id` 为工程级扩展字段（PRD 附录 C 之上），前端据此渲染工具块与结果卡片。

**错误场景**：40301；40401。

## 5. 附件接口

### 5.1 上传附件

| 项 | 值 |
| --- | --- |
| `POST /api/attachment/upload` | 需认证，`multipart/form-data` |

**Form 字段**：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| conversation_id | number | 是 | 目标会话 |
| file | File | 是 | csv/xlsx/txt/md，≤10MB |

**响应 data**：

```json
{ "attachment_id": 201, "file_name": "refund_extra.csv",
  "file_path": "uploads/1/1001/refund_extra.csv", "parse_status": "pending" }
```

- 行为：立即返回，解析异步进行；状态经 `GET /api/chat/ls/{cid}`（附件聚合）或 WS `attachment_status` 感知，前端轮询兜底（5s 间隔）。

**错误场景**：40002（格式/大小）；40301（他人会话或附件开关关闭）；40401。

### 5.2 删除附件

| 项 | 值 |
| --- | --- |
| `POST /api/attachment/delete` | 需认证 |

**请求**：`{ "attachment_id": 201 }`

**响应 data**：`{ "deleted": true }`（级联删源文件、DuckDB 表、检索缓存）

**错误场景**：40301；40401；40001（解析中 parsing 状态不可删，提示稍后）。

### 5.3 下载附件

| 项 | 值 |
| --- | --- |
| `GET /api/attachment/get?attachment_id=201` | 需认证 |

**响应**：文件流，`Content-Type` 按扩展名，`Content-Disposition: attachment; filename="refund_extra.csv"`。

**错误场景**：40301；40401（含磁盘文件缺失）。

## 6. 任务与结果接口

### 6.1 查询任务

| 项 | 值 |
| --- | --- |
| `GET /api/tasks/{task_id}` | 需认证 |

**响应 data**：

```json
{
  "task_id": 301,
  "task_status": "success",
  "current_step": null,
  "started_at": "2026-08-16T09:10:00.500",
  "finished_at": "2026-08-16T09:11:42.100",
  "error_message": null
}
```

**错误场景**：40301（非本人任务）；40401。

### 6.2 查询结果

| 项 | 值 |
| --- | --- |
| `GET /api/results/{task_id}` | 需认证 |

**响应 data**：

```json
{
  "problem_definition": "定位最近一周护肤品类退款率上升的主要 SKU、原因与影响范围",
  "key_metrics": [
    { "metric_name": "护肤品类退款率", "metric_value": 8.7, "metric_unit": "%",
      "metric_period": "2026-08-09 ~ 2026-08-15（周同比）" }
  ],
  "evidence_list": [
    { "source_type": "sql", "source_name": "s2_refund.refund_applications 按 sku 聚合",
      "evidence_text": "SKU-A1023 周退款 47 单，占类目 31%，环比 +22pp",
      "related_metric": "护肤品类退款率", "confidence": "high" }
  ],
  "conclusion_text": "本轮退款率上升主要由 SKU-A1023（描述不符类投诉）驱动，贡献 6.1pp…",
  "missing_data_text": "缺少物流时效数据，无法排除物流因素",
  "next_action_text": "1. 下架复核 SKU-A1023 详情页描述；2. 对近 30 天购买该 SKU 的用户发起主动关怀",
  "result_markdown": "# 经营归因分析报告\n…（完整 Markdown，复制功能直接使用）",
  "exported": true
}
```

> `result_markdown`、`exported` 为工程级扩展字段：前者供前端一键复制，后者标识是否已生成导出文件。

**错误场景**：40301；40401（任务无成功结果时也返回 40401，message 注明「任务未产生结果」）。

### 6.3 下载结果文件

| 项 | 值 |
| --- | --- |
| `GET /api/results/{task_id}/download` | 需认证 |

- 行为：已导出（result_file_path 存在且文件在）→ 直接返回文件流；未导出 → 后端即时渲染 Markdown 落盘后返回（不经过 Agent）。
- 响应：`text/markdown; charset=utf-8`，`Content-Disposition: attachment; filename="result_301.md"`。

**错误场景**：40301；40401（任务无结果）；40301（feature.export_enabled=false 时提示导出功能已关闭）。

## 7. 管理接口（仅 admin）

### 7.1 配置热更新

| 项 | 值 |
| --- | --- |
| `POST /api/admin/reload` | 需认证 + admin |

**请求**：无 body（重载 system_configs 全量）。

**响应 data**：

```json
{ "status": "ok", "message": "重载 14 项配置，LLM 客户端已重建" }
```

- status=error 时旧配置继续生效，message 给出校验失败原因。

**错误场景**：40301（非 admin）。

### 7.2 任务日志查询

| 项 | 值 |
| --- | --- |
| `GET /api/admin/tasks/{task_id}/logs` | 需认证 + admin |

**响应 data**（数组，created_at 升序）：

```json
[
  { "log_level": "info", "log_type": "status",
    "log_content": "task 301 queued → running", "created_at": "2026-08-16T09:10:00.600" },
  { "log_level": "warn", "log_type": "tool_exec",
    "log_content": "sql_query 第 1 次被拒：非 SELECT 语句，Agent 已修正重试", "created_at": "2026-08-16T09:10:12.300" }
]
```

**错误场景**：40301；40401。

## 8. WebSocket 协议

### 8.1 建连流程

```
1. POST /api/chat/ws-token  body: { "conversation_id": 1001 }
   → data: { "websocket_token": "tKj8…", "expires_in": 60 }
2. WS GET /api/chat/ws/chat?websocket_token=…&conversation_id=1001
   （经 nginx 时为 wss://，升级请求需携带同一 Cookie 会话）
3. 鉴权：令牌一次性 + 60s 有效 + 归属校验；失败 → 关闭码 4401
```

**ws-token 错误场景**：40301（他人会话）；40401。

**关闭码约定**：

| code | 含义 | 前端动作 |
| --- | --- | --- |
| 4401 | 令牌无效/过期/已消费 | 重新取 token 再连 |
| 4408 | 心跳超时（60s 无帧） | 立即重连 |
| 1000 | 服务端正常关闭（任务 done 后空闲） | 按需重连 |

### 8.2 上行消息（客户端 → 服务端）

```typescript
type WsUp =
  | { type: 'user_message'; text: string; attachment_ids: number[] }  // 发起一轮分析
  | { type: 'cancel'; task_id: number }                                // 取消运行中任务
  | { type: 'ping' }                                                   // 心跳，30s 一次
```

`user_message` 约定：text 必填 ≤4000 字；attachment_ids 中的附件必须属于该会话且 parse_status=ready，否则整条拒绝（error 下发 40001/40002）。

### 8.3 下行消息（服务端 → 客户端）

```typescript
type WsDown =
  | { type: 'message_start'; task_id: number; conversation_id: number; message_id: number }
  | { type: 'message_delta'; task_id: number; message_id: number; delta_text: string }
  | { type: 'tool_start';    task_id: number; tool_name: string; tool_input_summary: string }
  | { type: 'tool_finish';   task_id: number; tool_name: string;
      tool_status: 'success' | 'failed'; tool_result_summary: string }
  | { type: 'task_status';   task_id: number;
      task_status: 'queued'|'running'|'success'|'failed'|'cancelled'; current_step: string | null }
  | { type: 'result_ready';  task_id: number; result_id: number }
  | { type: 'error';         task_id: number; error_code: number; error_message: string }
  | { type: 'done';          task_id: number; finished_at: string }
  | { type: 'attachment_status'; attachment_id: number;
      parse_status: 'pending'|'parsing'|'ready'|'failed' }              // 协议扩展位
  | { type: 'pong' }
```

`current_step` 枚举：`planning`（规划分析路径）/ `querying`（查询取证）/ `summarizing`（归纳结论）。

**发送被拒**（未产生任务）时 error 形态：`{ type: 'error', task_id: 0, error_code: 40901, error_message: '当前会话已有运行中的任务' }`。

### 8.4 时序示例

**成功一轮**：

```
C→S user_message {text}
S→C message_start {task_id, message_id}
S→C task_status {queued} → task_status {running, planning}
S→C message_delta …（若干）
S→C tool_start {sql_query} → tool_finish {sql_query, success}
S→C message_delta …（多轮工具循环）
S→C task_status {running, summarizing}
S→C result_ready {task_id, result_id}
S→C task_status {success} → done {finished_at}
```

**失败**：`… task_status{running} → error{50001} → done`（终态 failed）。

**取消**：`C→S cancel{task_id} → S→C task_status{cancelled} → done`。

## 9. 前后端联调指南

### 9.1 建议联调顺序（与里程碑对齐）

1. **M1**：3.x 认证三接口 → 4.x 会话五接口 → 5.1/5.2 附件（上传后轮询状态）→ WS 建连 + ping/pong；
2. **M2**：WS user_message 全链路（mock LLM 可先回放固定 delta 序列）→ 6.1/6.2 任务与结果 → 6.3 下载；
3. **M3**：7.x 管理接口（admin 账号）。

### 9.2 前端 mock 约定

联调前前端可按本文档 JSON 示例 mock；重点边界：统一响应包包裹（真实数据在 data 字段内）、时间带毫秒、error 消息为用户可读中文。

### 9.3 curl 速查（登录后携带 Cookie）

```bash
# 创建会话
curl -X POST http://localhost:8000/api/chat/create \
  -H 'Content-Type: application/json' -b cookies.txt \
  -d '{"title":"退款归因演示"}'

# 上传附件
curl -X POST http://localhost:8000/api/attachment/upload \
  -b cookies.txt -F conversation_id=1001 -F file=@refund_extra.csv

# 获取 WS 令牌
curl -X POST http://localhost:8000/api/chat/ws-token \
  -H 'Content-Type: application/json' -b cookies.txt -d '{"conversation_id":1001}'

# 查询结果
curl -b cookies.txt http://localhost:8000/api/results/301
```

WebSocket 联调用 `wscat`：`wscat -c "ws://localhost:8000/api/chat/ws/chat?websocket_token=…&conversation_id=1001"`（需先带 Cookie 获取令牌，随后上行 `{"type":"ping"}` 验证连通）。
