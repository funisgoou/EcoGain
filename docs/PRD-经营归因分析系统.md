# 经营归因分析系统 PRD（产品需求文档）

## 1. 文档信息

| 项 | 内容 |
| --- | --- |
| 文档名称 | 经营归因分析系统产品需求文档 |
| 文档版本 | v1.1 |
| 文档状态 | 已评审（基线版） |
| 创建日期 | 2026-08-16 |
| 关联文档 | `docs/经营归因分析系统.md`（原始需求输入） |
| 目标读者 | 产品、前后端开发、测试、交付 |

### 修订记录

| 版本 | 日期 | 修订人 | 修订说明 |
| --- | --- | --- | --- |
| v1.0 | 2026-08-16 | — | 基于原始需求文档经三轮需求评审（grilling）收敛，形成基线版本 |
| v1.1 | 2026-08-16 | — | 数据架构调整：分析数据层（4 场景示例数据 + 附件导入表）由 MySQL 迁至嵌入式 DuckDB；Agent 的 SQL 工具统一走 DuckDB 只读连接；MySQL 职责收敛为系统库 + 认证服务 |

### 与原始需求文档的关系与关键修正

本 PRD 承接《经营归因分析系统.md》的全部功能性要求（页面、模块、数据表、接口、实时消息协议、输出格式），并在评审后做以下**关键修正**，以本 PRD 为准：

1. **删除「命令执行」工具**。原始文档的分析能力包含"命令执行"，存在任意命令执行的服务器安全风险。修正为：Agent 的计算引擎统一收敛为 **只读 SQL 执行**（SELECT-only、强制 LIMIT、超时熔断），复杂计算（同环比、透视、漏斗、聚类统计）均由 SQL 完成；同时保留文件读写（目录白名单）、文本检索、结果文件生成三类工具。
2. **附件格式收敛为四件套**：`csv` / `xlsx` / `txt` / `md`（不含 pdf/docx）。
3. **示例场景从「至少 2 个」扩为「4 个全做」**，按 P0/P1 分级：商品目录优化（P0）、退款模式分析（P0）、客户行为分析（P1）、库存异常分析（P1）。
4. **补齐原始文档缺失的规则**：附件 `parse_status` 枚举与状态机、统一响应包与错误码、上下文摘要触发阈值、服务重启后运行中任务的恢复规则、SQL 工具安全约束、单文件大小上限。
5. **数据架构调整（v1.1）**：评审初版曾因误判 DuckDB 需独立部署数据库组件而选定「纯 MySQL」。经确认 DuckDB 为 Python 嵌入式库（`pip install duckdb`，进程内运行、零新增服务）后，调整为**双层架构**：MySQL 仅承载系统库（10 张 OLTP 表）与认证服务凭据；4 个场景示例数据与附件导入表统一进入 DuckDB 分析库，Agent 的 SQL 工具只连 DuckDB 只读连接——方言统一、业务数据与上传附件可直接 JOIN，且部署不增加任何服务进程。

## 2. 背景与问题定义

### 2.1 业务背景

经营团队在日常分析中面临典型痛点：

- **人工拉数效率低**：业务同学提出一个归因问题（如"为什么上周退款率上升"），需要数据同学手工写 SQL、导出 Excel、多次往返沟通，单次分析周期以小时甚至天计。
- **归因靠个人经验**：结论质量依赖分析师个人对业务的理解，缺乏系统化的「问题定义 → 指标核对 → 证据收集 → 结论沉淀」流程，结论难以复用和追溯。
- **证据与过程不留存**：分析过程中的中间查询、引用数据、被排除的假设没有沉淀，事后无法复核"这个结论是怎么得出的"。
- **追问链路断裂**：经营分析是持续追问的过程（"那再看看华东区呢？"），传统 BI 看板每次都是全新查询，无法在上一轮结论基础上继续深挖。

### 2.2 问题定义

本项目要解决的核心问题：**让业务用户围绕一个经营问题，通过多轮自然语言对话完成"查数—归因—追问—出报告"的完整分析闭环，且全过程证据可追溯、结论可导出。**

### 2.3 解决方案概述

构建一个单 Agent 多轮对话的分析系统：

- 用户在工作台以自然语言提出经营分析问题；
- Agent（LLM + 工具调用编排）自动理解问题、生成 SQL 查询业务数据库、读取会话内上传的附件、检索文本资料，逐步收集证据；
- 分析过程通过长连接实时流式返回（模型思考文本、工具执行过程、任务状态）；
- 每轮分析产出**六段结构化结果**（问题定义、关键指标、证据列表、归因结论、待补充数据、下一步建议）；
- 会话级上下文管理支持持续追问，历史结论自动摘要压缩，保证长对话不丢失主线。

## 3. 产品目标与非目标

### 3.1 产品目标

| 编号 | 目标 | 度量 |
| --- | --- | --- |
| G1 | 单轮常见归因问题端到端出结论 | P0 场景单轮分析 ≤ 120 秒（含 LLM 推理与 SQL 执行） |
| G2 | 结论证据可追溯 | 每条归因结论至少关联 1 条带 `confidence` 的证据 |
| G3 | 多轮追问不丢上下文 | 同一会话 ≥ 20 轮对话后仍能正确引用早期结论（摘要压缩保障） |
| G4 | 分析结果可交付 | 六段结构化结果一键复制、导出 Markdown 文件并可重复下载 |
| G5 | 一键可演示 | docker-compose 一键拉起全部服务，含 4 个业务场景示例数据与完整演示链路 |

### 3.2 非目标（本期明确不做）

- **不做 BI 可视化看板**：结果以结构化文本 + Markdown 呈现，不做图表组件。
- **不做实时数仓 / 数据同步**：业务示例库为预置静态数据，不接实时数据源。
- **不做多租户**：单组织内部使用，用户体系对接自建认证中心。
- **不做任意代码执行**：Agent 无 shell / python 执行能力（安全红线，见 7.3）。
- **不做生产级高可用**：POC 演示级规模（并发 ≤ 5，单机单实例），不做多实例横向扩展与分布式任务队列。

### 3.3 成功指标（验收口径）

以第 11 章验收标准全量通过为准； additionally：

- 4 个示例场景各跑通一条完整演示链路（提问 → 工具执行 → 结构化结果 → 导出）；
- 演示环境中连续 8 小时无人工干预正常可用。

## 4. 用户角色与权限矩阵

### 4.1 角色定义

| 角色 | 说明 | 典型使用者 |
| --- | --- | --- |
| 分析用户（analyst） | 使用工作台完成经营归因分析的业务/数据同学 | 运营、品类经理、数据分析师 |
| 系统管理员（admin） | 维护系统配置、数据源、查看运行日志 | 平台运维 |

### 4.2 权限矩阵

| 能力 | 分析用户 | 系统管理员 |
| --- | --- | --- |
| 授权登录 | ✅ | ✅ |
| 创建/删除/重命名/切换自己的会话 | ✅ | ✅ |
| 发送分析问题、取消分析 | ✅ | ✅ |
| 上传/删除/下载会话附件 | ✅（仅自己的会话） | ✅ |
| 查看结构化结果、复制、导出 | ✅（仅自己的会话） | ✅ |
| 配置热更新（`POST /api/admin/reload`） | ❌ | ✅ |
| 查看系统运行日志 | ❌ | ✅ |
| 管理数据源连接 | ❌ | ✅ |
| 功能开关启停 | ❌ | ✅ |

数据隔离规则：分析用户只能访问**自己创建**的会话及其下属消息、附件、任务、结果；越权访问返回统一错误码 `40301`。

## 5. 核心用户故事

| 编号 | 角色 | 用户故事 |
| --- | --- | --- |
| US-01 | 分析用户 | 作为分析用户，我想通过认证中心一键授权登录，以便无需在本系统单独注册账号。 |
| US-02 | 分析用户 | 作为分析用户，我想创建一个分析会话并命名（如"8 月退款率异常归因"），以便按经营问题隔离上下文。 |
| US-03 | 分析用户 | 作为分析用户，我想在会话里上传 csv/xlsx 数据文件和 txt/md 资料，以便 Agent 能结合我提供的私有数据做归因。 |
| US-04 | 分析用户 | 作为分析用户，我想输入"为什么上周护肤品类的退款率明显上升？"并看到 Agent 逐步执行 SQL、读取附件的过程，以便知道结论不是凭空生成的。 |
| US-05 | 分析用户 | 作为分析用户，我想在结果区看到六段结构化结果（问题定义/关键指标/证据/结论/待补充数据/建议），以便直接用于经营汇报。 |
| US-06 | 分析用户 | 作为分析用户，我想基于上一轮结论继续追问"那主要集中在哪些 SKU？"，系统应记住前文，以便深挖而不必重复背景。 |
| US-07 | 分析用户 | 作为分析用户，我想随时取消一个跑偏的分析任务，以便立即重新提问。 |
| US-08 | 分析用户 | 作为分析用户，我想导出某轮分析结果为 Markdown 文件并在之后重复下载，以便归档和分享。 |
| US-09 | 分析用户 | 作为分析用户，我想切换回历史会话查看完整消息和分析结果，以便延续上周的分析。 |
| US-10 | 分析用户 | 作为分析用户，我想删除废弃的会话，其下属消息、附件、任务、结果应一并清除，以便不留垃圾数据。 |
| US-11 | 系统管理员 | 作为系统管理员，我想修改 LLM 供应商/模型等配置后调用重载接口即时生效，以便不停机切换模型。 |
| US-12 | 系统管理员 | 作为系统管理员，我想查看任务运行日志与错误详情，以便定位失败原因。 |
| US-13 | 系统管理员 | 作为系统管理员，我想维护业务数据源连接并启停功能开关，以便控制系统能力边界。 |

## 6. 功能需求

> 需求编号规则：`F{n}` 功能域，验收标准可直接转化为测试用例。

### F1 认证登录（授权登录入口页 + 登录回调页）

**描述**：系统自身不维护登录表单，通过自建轻量 OAuth2 认证中心以**授权码模式（Authorization Code）**完成登录。

**认证时序**：

1. 用户访问前端，检测到无登录态 → 展示**授权登录入口页**（品牌名 + 「授权登录」按钮）；
2. 点击按钮请求 `GET /auth/login` → 后端生成 `state`（防 CSRF，暂存于服务端会话）并 302 跳转认证中心 `GET /authorize?client_id=...&redirect_uri=...&response_type=code&state=...`；
3. 认证中心展示账号密码登录页，用户提交凭据；
4. 认证中心 302 回跳 `GET /auth/callback?code=...&state=...`；
5. 后端校验 `state`，用 `code` 向认证中心 `POST /token` 换取 `access_token`，再调 `/userinfo` 获取用户信息；
6. 后端按 `external_user_id` upsert `users` 表，签发本系统会话（HttpOnly Cookie），302 跳转聊天工作台；
7. 登录回调页在跳转前完成登录态保存与校验，失败时展示错误原因与「重试登录」入口。

**认证中心交付要求**（自建轻量认证服务，独立交付物）：

- 实现 OAuth2 授权码模式最小闭环：`GET /authorize`、`POST /token`、`GET /userinfo`；
- 内置演示账号 seed：`analyst / EcoGain@2026`（分析用户）、`admin / EcoGain@2026`（系统管理员）；
- access_token 采用签名 JWT，含 `sub`（external_user_id）、`username`、`display_name`、`role`；
- 独立进程部署，与业务后端共用 MySQL（自有凭据表）。

**验收标准**：

- [ ] 未登录访问工作台被引导至授权登录入口页；
- [ ] 完整授权码流程走通，登录后自动进入聊天工作台且刷新不丢登录态；
- [ ] `state` 不匹配时回调拒绝并报 `40101`；
- [ ] 认证中心账密错误在登录页提示，不进入回调。

### F2 会话管理

**描述**：会话是归因分析的基本单元，隔离上下文、附件、任务与结果。

**状态机**：

```
active ──archive──▶ archived
active ──delete───▶ deleted（软删除）
archived ─delete──▶ deleted（软删除）
```

- `active`：正常使用；
- `archived`：归档（不出现在默认会话列表，可恢复为 active）；
- `deleted`：软删除，不再对用户可见。

**规则**：

- R1 删除会话（置 `deleted`）时，**同时物理删除**该会话下的：消息记录、附件记录（含 `uploads/{user_id}/{conversation_id}/` 目录文件）、任务记录（含 `task_logs`）、结果记录（含 `exports/{user_id}/{conversation_id}/` 目录文件）、上下文摘要记录、临时目录 `workspace/{user_id}/{conversation_id}/`；
- R2 会话列表按 `last_message_at` 倒序；
- R3 重命名仅修改 `title`，不产生其他副作用；
- R4 会话数据按 `user_id` 隔离（见第 4.2 节）。

**验收标准**：

- [ ] 创建、重命名、归档、删除会话均生效且列表实时刷新；
- [ ] 删除会话后，其消息/附件/任务/结果/摘要在数据库与磁盘目录中均已清除；
- [ ] 访问已删除会话的任意下属资源返回 `40401`。

### F3 聊天工作台（消息与多轮分析）

**描述**：三栏布局——左侧会话列表，中间当前会话对话区（底部输入框 + 发送按钮），右侧本轮分析结果区（见 F7）。

**规则**：

- R1 **一条用户消息对应一次分析任务**：用户发送问题 → 创建 `analysis_tasks` 记录 → 驱动 Agent 执行；
- R2 **单会话串行**：同一时间一个会话只允许存在一个运行中（`queued`/`running`）任务；违反时拒绝发送并提示错误码 `40901`；
- R3 消息按 `seq_no`（会话内单调递增）排序，历史回放与实时渲染共用同一渲染逻辑；
- R4 发送消息时可携带本轮已就绪（`parse_status = ready`）的附件引用；
- R5 支持取消运行中分析（见 F5）；
- R6 消息类型（`message_type`）至少包含：`text`（用户/模型文本）、`tool_call`（工具调用展示）、`result`（结果卡片引用）。

**验收标准**：

- [ ] 发送问题后对话区实时流式渲染模型文本（`message_delta`）；
- [ ] 工具调用以独立消息块展示工具名与结果摘要；
- [ ] 任务运行中再次发送被拦截并提示；
- [ ] 切换会话后历史消息完整回放，顺序正确；
- [ ] 刷新页面后当前会话历史与结果不丢失。

### F4 附件管理（附件侧栏）

**描述**：会话级附件侧栏展示附件列表（文件名、文件类型、文件大小、上传时间、解析状态），支持上传、删除、下载。

**格式与解析规则**：

- R1 仅支持 `csv` / `xlsx` / `txt` / `md` 四种格式，单文件 ≤ 10MB，超出拒绝（错误码 `40002`）；
- R2 `parse_status` 状态机：

```
pending ──解析中──▶ parsing ──成功──▶ ready
                         └──失败──▶ failed（可删除后重传）
```

- R3 **结构化文件（csv/xlsx）**：解析成功后导入 DuckDB 分析库，落表命名 `attachment_data_{attachment_id}`（列名规范化：小写、下划线），首行作为表头；
- R4 **文本文件（txt/md）**：不入库，注册为文件路径供「文本检索工具」检索；
- R5 解析为异步任务，上传接口立即返回 `attachment_id` 与 `pending` 状态，前端轮询或经 WS 感知状态变化；
- R6 删除附件同时删除数据库记录、`uploads` 目录源文件与（如已导入的）`attachment_data_{id}` 表；
- R7 上传路径固定为 `uploads/{user_id}/{conversation_id}/`，文件名做安全规范化（去路径分隔符），存储与下载均做**路径穿越校验**。

**验收标准**：

- [ ] 四种格式均可上传并正确展示解析状态流转；
- [ ] csv/xlsx 解析 ready 后，Agent 的 SQL 工具可查询到对应数据（见 F5 工具清单）；
- [ ] txt/md 解析 ready 后，Agent 的文本检索工具可检索到内容；
- [ ] 超限格式与超大文件被拒绝并有明确提示；
- [ ] 附件可下载且内容与上传一致；删除后不可再下载。

### F5 分析任务与分析引擎（核心）

**任务状态机**：

```
queued ──调度──▶ running ──成功──▶ success
                   ├──失败──▶ failed
queued/running ──取消──▶ cancelled
```

**任务规则**：

- R1 创建任务即签发**一次性 WebSocket 临时令牌**（见 F6），并通过长连接推送全流程事件；
- R2 任务取消：用户触发取消 → 置 `cancelled`，中断 LangGraph 执行图，已产生的中间消息保留；
- R3 **僵尸任务恢复**：服务启动时扫描 `queued`/`running` 的任务，统一置 `failed`，`error_message = "服务重启导致任务中断"`；
- R4 任务全生命周期日志写入 `task_logs`（含 LLM 调用、工具执行、状态流转），供管理员查看；
- R5 单任务硬超时 **120 秒**，超时置 `failed`（`error_message` 注明超时）。

**分析引擎（LangGraph Agent）**：

- 上下文拼装 = 系统提示词 + 会话摘要（`context_summaries`，见 F8）+ 最近 N 轮消息 + 本轮问题与附件清单（含附件表 schema 描述，供 LLM 生成 SQL）；
- Agent 以工具调用循环推进分析，工具执行结果与模型文本经 WS 实时推送；
- 一轮分析收敛后，按附录 E 的六段结构化格式产出最终结果。

**Agent 工具清单（安全约束为强制项）**：

| 工具 | 说明 | 安全约束 |
| --- | --- | --- |
| `sql_query` | 对 DuckDB 分析库（4 场景示例数据 + 附件导入表）执行 LLM 生成的 SQL | 仅 `SELECT` / `SHOW COLUMNS` / `DESCRIBE`；以只读模式（`read_only=True`）打开连接；强制包裹 `LIMIT`（默认 ≤ 1000 行）；单语句执行超时 10 秒；禁止多语句 |
| `file_read` | 读取会话白名单目录内文件 | 目录白名单：`uploads/{user_id}/{conversation_id}/`、`workspace/{user_id}/{conversation_id}/`；路径穿越校验；单次读取 ≤ 1MB |
| `file_write` | 写中间文件至会话工作目录 | 仅允许写 `workspace/{user_id}/{conversation_id}/`；路径穿越校验；总用量 ≤ 50MB/会话 |
| `text_search` | 在 txt/md 附件与工作目录文本中检索关键词/短语 | 仅检索当前会话白名单文件；返回命中片段与位置 |
| `generate_result_file` | 将六段结构化结果渲染为 Markdown 并落盘 | 仅写 `exports/{user_id}/{conversation_id}/`；文件名由系统生成（含 task_id） |

> 明确约束：**不存在任何 shell / 任意代码执行工具**。所有数值计算由 `sql_query` 以 SQL 表达（聚合、窗口函数、CASE 透视等）。

**验收标准**：

- [ ] 任务状态流转经 `task_status` 消息实时可见（queued → running → success/failed/cancelled）；
- [ ] 工具开始/结束均有 `tool_start` / `tool_finish` 推送；
- [ ] 非 SELECT 语句（含 `INSERT`/`UPDATE`/`DELETE`/`DDL`/多语句）被工具层拒绝并作为错误反馈给 Agent；
- [ ] 越权路径（`../` 等）被拒绝；
- [ ] 取消立即生效，任务终态为 `cancelled`；
- [ ] 服务重启后原 running 任务被置 failed 并可查询到原因。

### F6 实时通道（长连接模块 + 实时任务区）

**描述**：会话级 WebSocket 长连接，负责中间消息与最终结果推送。前端**实时任务区**（对话区上方/内嵌）基于该通道展示：当前分析轮状态、当前步骤（`current_step`）、错误信息、工具执行过程（`tool_start`/`tool_finish`）和结果文件生成状态。

**规则**：

- R1 建连流程：前端先 `POST /api/chat/ws-token` 获取一次性临时令牌（`websocket_tokens` 表，有效期 60 秒，`consumed_at` 标记一次性消费）→ 携带 `websocket_token` 与 `conversation_id` 连接 `WS /api/chat/ws/chat`；
- R2 连接鉴权：令牌无效/过期/已消费、用户与会话不匹配，均拒绝建连（关闭码 `4401`）；
- R3 一个连接绑定一个会话；切换会话需重新获取令牌并重建连接；
- R4 客户端心跳（ping/pong）30 秒，超时无心跳服务端主动关闭；
- R5 断线重连后：历史消息走 REST 拉取补齐，进行中任务的后续事件经重连后继续接收；
- R6 任务结束时推送 `done` 后，服务端可主动关闭空闲连接。

**消息类型总览**（完整字段见附录 D）：`message_start`、`message_delta`、`tool_start`、`tool_finish`、`task_status`、`result_ready`、`error`、`done`。

**验收标准**：

- [ ] 令牌一次性生效，重放被拒绝；
- [ ] 全部 8 类消息按场景正确推送；
- [ ] 断线重连后消息不重复、不丢失。

### F7 结构化结果（结果展示区 + 导出）

**描述**：右侧结果展示区呈现本轮六段结构化输出，支持复制与导出。

**六段输出定义**：

1. **问题定义**：当前分析要回答的业务问题（自然语言）；
2. **关键指标**：数组，每项含 `metric_name`、`metric_value`、`metric_unit`、`metric_period`；
3. **证据列表**：数组，每项含 `source_type`（sql/file/text）、`source_name`、`evidence_text`、`related_metric`、`confidence`（high/medium/low）；
4. **归因结论**：自然语言输出主要原因和影响范围；
5. **待补充数据**：当前分析仍缺失的数据项清单；
6. **下一步建议**：至少 2 条后续动作建议。

**规则**：

- R1 结果落库 `analysis_results`（结构化字段 + 完整 Markdown 双存储），`result_ready` 推送后前端渲染；
- R2 复制：六段内容以 Markdown 形式复制到剪贴板；
- R3 导出：`generate_result_file` 工具生成 Markdown 文件至 `exports/{user_id}/{conversation_id}/`，此后可重复下载（本期内 **Markdown 单格式**）；
- R4 历史任务结果可通过 `GET /api/results/{task_id}` 随时回看。

**验收标准**：

- [ ] 每轮成功分析后结果区展示完整六段内容；
- [ ] 一键复制内容与结果区一致；
- [ ] 导出成功后可下载，重新进入会话后仍可再次下载同一文件；
- [ ] 下一步建议恒 ≥ 2 条，缺失时结果生成失败并计入 `task_logs`。

### F8 上下文摘要压缩

**描述**：长会话自动压缩历史上下文，保障多轮追问主线不丢、token 可控。

**规则**：

- R1 触发阈值（任一满足）：会话超过 **20 轮**对话；或拼装上下文估算超过 **8k tokens**；
- R2 触发后，将已被覆盖的最早一段消息（`start_seq_no` ~ `end_seq_no`）交由 LLM 生成摘要，写入 `context_summaries`；
- R3 上下文拼装 = 摘要（按时间序）+ 最近 N 轮原始消息 + 本轮输入；
- R4 摘要需保留：已完成的分析结论、关键指标数值、用户侧的业务约束与偏好表述；
- R5 摘要生成失败不阻断主流程（退化为直接截断最旧消息，并记录 `task_logs` 告警）。

**验收标准**：

- [ ] 20 轮以上对话后 `context_summaries` 出现记录且 `seq_no` 区间无重叠；
- [ ] 长会话第 25 轮追问仍能正确引用第 1~5 轮的关键结论；
- [ ] 摘要失败时任务不受阻断。

### F9 系统管理（配置 / 日志 / 数据源 / 开关）

**描述**：面向系统管理员的运维能力。

- R1 **配置热更新**：`system_configs` 按 `config_key/config_group` 存储；`POST /api/admin/reload` 触发后端重新加载配置并即时生效（无需重启）；关键配置组：
  - `llm`：`llm.provider`、`llm.base_url`、`llm.model`、`llm.api_key_ref`、`llm.temperature`；
  - `agent`：`agent.max_tool_rounds`（默认 15）、`agent.task_timeout_seconds`（默认 120）、`agent.context_rounds`（默认 20）、`agent.context_token_budget`（默认 8000）；
  - `datasource`：DuckDB 分析库文件路径（数据卷挂载点）、只读连接参数；
  - `feature`：功能开关（附件、导出等）。
- R2 **多供应商 LLM 网关**：后端经 OpenAI 兼容协议（`base_url` + `api_key`）访问任意供应商（GLM / GPT / Claude 兼容网关等），切换供应商仅需改配置 + 重载，不改代码；
- R3 **运行日志**：管理员可按任务查询 `task_logs`（`log_level`、`log_type`、`log_content`、时间）；
- R4 **数据源管理**：维护业务库连接信息；
- R5 管理接口仅 `admin` 角色可调用（`40301` 拦截）。

**验收标准**：

- [ ] 修改 `llm.model` 后调用 reload，下一轮分析即使用新模型；
- [ ] reload 接口返回 `{status, message}`，失败原因明确；
- [ ] 非管理员调用管理接口被拒绝。

### F10 示例业务场景（4 个全做）

**描述**：预置 4 个场景的业务示例库（MySQL）与演示链路，作为验收演示与提示词调优基线。P0 场景优先保障，P1 场景在 M3 里程碑内完成。

#### S1 商品目录优化（P0）

- **数据表**：商品表、类目表、搜索曝光表、点击表、转化表；
- **示例问题**：「本月哪些商品曝光高但转化低？给出优化类目结构的建议」；
- **期望归因链路**：曝光→点击→转化分层漏斗 → 定位高曝光低转化商品 → 归因（主图/价格带/类目归属）→ 输出类目优化建议。

#### S2 退款模式分析（P0）

- **数据表**：退款申请表、退款原因表、订单表、用户表；
- **示例问题**：「为什么最近一周护肤品类的退款率明显上升？主要集中在哪些 SKU 和原因？」；
- **期望归因链路**：退款率同环比 → 按类目/SKU/原因下钻 → 交叉用户画像（新老客）→ 输出主要原因与影响范围 → 待补充数据（如物流时效）与建议。

#### S3 客户行为分析（P1）

- **数据表**：用户表、访问事件表、加购事件表、下单事件表；
- **示例问题**：「访问到下单的转化漏斗在哪里流失最严重？哪类用户群体流失最多？」；
- **期望归因链路**：访问→加购→下单漏斗 → 分层对比（渠道/新老客）→ 定位最大流失环节 → 建议干预动作。

#### S4 库存异常分析（P1）

- **数据表**：库存表、入库表、出库表、销量表；
- **示例问题**：「哪些商品出现账实不符（期初+入库−出库 ≠ 期末）？异常的可能原因是什么？」；
- **期望归因链路**：按 SKU 核对库存平衡公式 → 圈定异常商品 → 关联销量波动/出入库记录 → 归因（错记漏记/异常出库）→ 建议盘点清单。

**共同要求**：

- R1 每个场景在 DuckDB 分析库中提供独立 schema 与 seed 脚本（含合理脏数据以演示容错）；
- R2 每个场景提供至少 2 组预设追问链（首轮问题 + 2 条追问）用于演示；
- R3 seed 数据时间跨度覆盖近 90 天，支持同环比类问题。

## 7. 非功能需求

### 7.1 性能（POC 演示级）

| 指标 | 目标值 |
| --- | --- |
| 并发分析任务 | ≤ 5（单机单实例） |
| 页面首屏 | ≤ 2 秒（局域网） |
| 发送到首条 `message_delta` | ≤ 5 秒（含 LLM 首包） |
| 单任务硬超时 | 120 秒（可配） |
| 单条 SQL 执行超时 | 10 秒 |
| SQL 返回行数上限 | 1000 行（强制 LIMIT） |
| WS 临时令牌有效期 | 60 秒，一次性 |

### 7.2 可靠性

- 服务重启自动恢复：僵尸任务置 failed（F5-R3）；WS 断线重连补齐（F6-R5）；
- 附件解析失败不阻断会话其他能力；
- LLM 供应商调用失败：单任务内重试 2 次（指数退避），仍失败则任务 failed 并透出错误信息。

### 7.3 安全红线（强制）

- **无任意命令执行**：Agent 工具层不存在 shell/代码执行能力；
- **SQL 只读**：Agent 查询统一经 DuckDB 只读连接（`read_only=True`）；工具层语句白名单校验 + 强制 LIMIT + 超时 + 禁多语句；附件导入等写操作仅出现在后台解析链路，不暴露给 Agent；
- **文件系统白名单**：读写仅限第 6 章工具清单指定目录，一律路径穿越校验；
- **传输与凭据**：HTTPS/WSS（演示环境可自签证书）；`llm.api_key` 等敏感配置不以明文出现在前端与日志；
- **会话隔离**：所有资源按 `user_id` 鉴权（4.2 节）；
- **CSRF**：OAuth `state` 强校验；管理接口仅 admin。

### 7.4 日志规范

- 后端统一结构化日志（JSON），携带 `trace_id`、`task_id`、`conversation_id`、`user_id` 结构化字段；
- 业务关键节点（任务状态流转、工具执行、配置重载）Info 级；错误捕获 Error 级并带堆栈摘要；
- 标准输出仅允许结构化日志流，禁止遗留裸 `print` 调试输出；
- 任务维度日志同步落 `task_logs` 供前端查询。

### 7.5 兼容性

- 浏览器：Chrome / Edge 最近两个大版本；
- 分辨率：≥ 1366×768（工作台三栏布局的自适应下限）。

## 8. 风险与对策

| 风险 | 等级 | 对策 |
| --- | --- | --- |
| LLM 幻觉导致错误归因 | 高 | 六段输出强制证据溯源（`evidence_list` + `confidence`）；提示词要求结论必须引用已执行 SQL 的结果；`待补充数据` 段显式暴露数据缺口 |
| Prompt 注入诱导危险操作 | 高 | 工具层独立于 LLM 做白名单校验（语句类型、目录、行数、超时），注入不改变服务端约束 |
| SQL 慢查询拖垮任务 | 中 | 单语句 10 秒超时 + 强制 LIMIT + DuckDB 只读连接；慢 SQL 记入 `task_logs` |
| 长任务占用通道 | 中 | 任务 120 秒硬超时 + 用户可取消 + 单会话单任务 |
| 附件解析失败影响体验 | 中 | 异步解析 + 状态机可视 + 失败可重传；脏数据行容错跳过并计数 |
| LLM 供应商不稳定 | 中 | OpenAI 兼容多供应商网关，配置热切换；调用重试 2 次 |
| 上下文超限 / 长对话退化 | 中 | F8 摘要压缩 + token 预算控制 |
| DuckDB 单写者并发限制 | 低 | 附件导入（写）经后台串行队列执行；Agent 查询一律只读连接（多读无锁冲突）；POC 并发 ≤ 5 场景安全；预留按会话拆分库文件的扩展点 |
| 数据规模增长后 POC 架构不足 | 低（本期接受） | 明确非目标；预留配置化扩展点（任务队列、多实例）不在本期实现 |

## 9. 里程碑

| 里程碑 | 内容 | 出口标准 |
| --- | --- | --- |
| M1 基础框架 | docker-compose 骨架；认证中心 + OAuth2 登录链路；会话/消息/附件 CRUD；WS 通道与令牌鉴权 | 验收标准 1、2（登录、会话/附件/消息）通过 |
| M2 分析链路 | LangGraph Agent + 5 个安全工具；任务状态机与取消；六段结构化结果 + 导出；上下文摘要 | 验收标准 3、6、7 通过（含 SQL 安全约束用例） |
| M3 场景演示 | 4 场景 schema + seed；演示链路调优（提示词、追问链）；历史回放与继续追问 | 验收标准 4、8 通过 |
| M4 打磨交付 | compose 一键起收敛、接口文档、README 与演示脚本、日志清理与安全自查 | 第 11 章全量验收通过 |

## 10. 交付物清单

1. 前端源码（Vue3 + Vite，含构建产物与 nginx 配置）；
2. 后端源码（FastAPI + LangGraph，含 Alembic 迁移与系统库初始化脚本）；
3. 认证服务源码（轻量 OAuth2 授权码服务，含演示账号 seed）；
4. DuckDB 分析库初始化脚本（4 场景 schema + seed + 演示附件样本，含脏数据）；
5. docker-compose 编排（前端、后端、认证服务、MySQL；DuckDB 为后端嵌入式依赖，数据库文件经卷持久化，不新增服务进程）；
6. 接口说明文档（对齐附录 C/D）；
7. 至少 4 组完整分析演示示例（每场景 1 组：首轮问题 + 追问 + 结果导出件）。

## 11. 验收标准（承接原始文档，全量保留）

- [ ] 能通过授权登录进入聊天工作台；
- [ ] 能创建会话、上传附件、发送消息并查看历史记录；
- [ ] 能通过实时连接看到分析过程中的状态变化、工具执行和最终结果；
- [ ] 能查询历史消息、切换旧会话并继续追问；
- [ ] 能在结果区看到六部分结构化输出；
- [ ] 能导出分析结果文件并重新下载；
- [ ] 能通过配置重载接口更新配置并即时生效；
- [ ] 能完成至少两个业务场景的完整演示（本期目标：4 个全通过）。

---

## 附录 A：技术选型与部署拓扑

### A.1 选型结论

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 后端 | Python 3.12 + FastAPI + LangGraph | Agent 编排、流式输出、异步栈成熟 |
| ORM | SQLAlchemy 2.x（async）+ Alembic | 系统库建模与迁移 |
| 前端 | Vue3 + Vite + TypeScript + Pinia | 三栏工作台、WS 流式渲染 |
| 系统数据库 | MySQL 8 | 系统库 `ecogain`（10 张 OLTP 表）+ 认证服务凭据表 |
| 分析数据层 | DuckDB（Python 嵌入式，`pip install duckdb`） | 承载 4 场景示例数据 + 附件导入表；Agent SQL 工具只读连接；业务数据与附件数据可直接 JOIN；零新增部署服务 |
| LLM 接入 | OpenAI 兼容协议多供应商网关 | base_url/model/api_key 配置化热切换 |
| 认证 | 自建轻量 OAuth2 授权码服务（FastAPI） | 独立交付物，演示零外部依赖 |
| 部署 | docker-compose | 前端 nginx、backend、auth-server、mysql（自动 seed） |

### A.2 部署拓扑

```
浏览器
  │ HTTPS
  ▼
nginx（前端静态资源 + /api、/auth、/ws 反代）
  ├──▶ auth-server :8001   （OAuth2：/authorize /token /userinfo）
  └──▶ backend :8000       （业务 API + WebSocket）
          │
          ├──▶ MySQL :3306
          │      └── ecogain（系统库：10 张 OLTP 表 + 认证服务凭据表）
          │
          └──▶ DuckDB（backend 进程内嵌入式，无独立服务进程）
                 └── 数据卷 analytics/analytics.duckdb
                        ├── s1_catalog    （S1 商品目录优化）
                        ├── s2_refund     （S2 退款模式分析）
                        ├── s3_behavior   （S3 客户行为分析）
                        ├── s4_inventory  （S4 库存异常分析）
                        └── attachment_data_{id}（附件导入表）
```

文件存储卷（容器挂载）：`uploads/`、`exports/`、`workspace/`（均按 `{user_id}/{conversation_id}/` 二级隔离）与 `analytics/`（DuckDB 数据库文件及 WAL，随容器重启持久化）。

## 附录 B：数据模型

> 双层边界：**系统库（MySQL `ecogain`）** 承载下列 10 张 OLTP 表，走 Alembic 迁移；**分析层（DuckDB）** 承载 4 个场景的示例表（schema：`s1_catalog` / `s2_refund` / `s3_behavior` / `s4_inventory`）与附件导入表（`attachment_data_{id}`），由初始化脚本建表灌数，不经过 Alembic。

### B.1 表清单与字段（系统库 `ecogain`）

> 类型为约定建议，实现以 Alembic 迁移为准；所有主键 `id` 为 BIGINT 自增；时间字段 DATETIME(3)。

**users** — 平台用户（认证中心同步）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| external_user_id | VARCHAR(64) UK | 认证中心用户唯一标识 |
| username | VARCHAR(64) | 登录名 |
| display_name | VARCHAR(128) | 显示名 |
| role | VARCHAR(16) | `analyst` / `admin` |
| status | VARCHAR(16) | `active` / `disabled` |
| created_at / updated_at | DATETIME | |

**conversations** — 会话

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| user_id | BIGINT FK→users.id | 归属用户 |
| title | VARCHAR(200) | 默认「新分析」或截取首问 |
| status | VARCHAR(16) | `active` / `archived` / `deleted` |
| last_message_at | DATETIME | 列表排序键 |
| created_at / updated_at | DATETIME | |

**messages** — 消息

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| conversation_id | BIGINT FK | 级联删除 |
| role | VARCHAR(16) | `user` / `assistant` / `tool` |
| message_type | VARCHAR(16) | `text` / `tool_call` / `result` |
| content | TEXT | 正文（工具消息存参数/结果摘要） |
| tool_name | VARCHAR(64) | 工具消息专用 |
| tool_status | VARCHAR(16) | `running` / `success` / `failed` |
| seq_no | INT | 会话内单调递增（唯一索引 conversation_id+seq_no） |
| created_at | DATETIME | |

**attachments** — 附件

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| conversation_id | BIGINT FK | 级联删除 |
| message_id | BIGINT NULL | 关联的发送消息 |
| file_name | VARCHAR(255) | 原始文件名（规范化后） |
| file_path | VARCHAR(512) | 相对 uploads 的路径 |
| file_type | VARCHAR(16) | `csv`/`xlsx`/`txt`/`md` |
| file_size | BIGINT | 字节 |
| parse_status | VARCHAR(16) | `pending`/`parsing`/`ready`/`failed` |
| created_at | DATETIME | |

**analysis_tasks** — 分析任务

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| conversation_id / user_id | BIGINT FK | 级联删除 |
| input_text | TEXT | 本轮问题 |
| task_status | VARCHAR(16) | `queued`/`running`/`success`/`failed`/`cancelled` |
| current_step | VARCHAR(64) | 如 `planning` / `querying` / `summarizing` |
| started_at / finished_at | DATETIME | |
| error_message | TEXT | failed 时填写 |

**analysis_results** — 结构化结果

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| task_id | BIGINT FK UK | 一任务一结果 |
| conversation_id | BIGINT FK | 级联删除 |
| problem_definition | TEXT | 六段-1 |
| key_metrics_json | JSON | 六段-2（附录 E） |
| evidence_list_json | JSON | 六段-3（附录 E） |
| conclusion_text | TEXT | 六段-4 |
| missing_data_text | TEXT | 六段-5 |
| next_action_text | TEXT | 六段-6 |
| result_markdown | MEDIUMTEXT | 完整 Markdown 渲染 |
| result_file_path | VARCHAR(512) | exports 相对路径，可空 |
| created_at | DATETIME | |

**context_summaries** — 上下文摘要

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| conversation_id | BIGINT FK | 级联删除 |
| start_seq_no / end_seq_no | INT | 覆盖的消息区间（区间不重叠） |
| summary_text | TEXT | |
| created_at | DATETIME | |

**websocket_tokens** — WS 一次性令牌

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| user_id / conversation_id | BIGINT | |
| token | VARCHAR(128) UK | 随机不可猜测 |
| expires_at | DATETIME | 60 秒 |
| consumed_at | DATETIME NULL | 一次性消费标记 |
| created_at | DATETIME | |

**system_configs** — 系统配置

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| config_key | VARCHAR(128) UK | 如 `llm.model` |
| config_value | TEXT | 敏感值为引用（key_ref），不明文 |
| config_group | VARCHAR(32) | `llm`/`agent`/`datasource`/`feature` |
| updated_at | DATETIME | |

**task_logs** — 任务日志

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | BIGINT PK | |
| task_id | BIGINT FK | 级联删除 |
| log_level | VARCHAR(16) | `info`/`warn`/`error` |
| log_type | VARCHAR(32) | `llm_call`/`tool_exec`/`status`/`summary` |
| log_content | TEXT | |
| created_at | DATETIME(3) | |

### B.2 枚举汇总

| 枚举 | 取值 |
| --- | --- |
| users.role | analyst、admin |
| conversations.status | active、archived、deleted |
| messages.role | user、assistant、tool |
| messages.message_type | text、tool_call、result |
| attachments.file_type | csv、xlsx、txt、md |
| attachments.parse_status | pending、parsing、ready、failed |
| analysis_tasks.task_status | queued、running、success、failed、cancelled |
| evidence.source_type | sql、file、text |
| evidence.confidence | high、medium、low |
| task_logs.log_level | info、warn、error |

## 附录 C：API 约定

### C.1 统一响应包

```json
// 成功
{ "code": 0, "message": "ok", "data": { } }
// 失败
{ "code": 40901, "message": "当前会话已有运行中的任务", "data": null }
```

### C.2 错误码表

| 错误码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 40001 | 参数缺失/格式错误 |
| 40002 | 附件格式或大小不合规 |
| 40101 | 未登录 / OAuth state 校验失败 / 令牌无效 |
| 40301 | 无权限（非本人资源或非管理员） |
| 40401 | 资源不存在（含已删除会话） |
| 40901 | 会话已有运行中任务 |
| 40902 | WS 令牌无效/过期/已消费 |
| 42901 | 并发任务超过上限（>5） |
| 50001 | LLM 调用失败（重试后仍失败） |
| 50002 | 工具执行被安全策略拒绝 |
| 50003 | 任务超时 |

### C.3 接口清单

| 接口 | 方法 | 请求 | 响应 data 字段 |
| --- | --- | --- | --- |
| `/auth/login` | GET | — | 302 跳转认证中心 |
| `/auth/callback` | GET | `code`、`state`（query） | 302 至工作台，设会话 Cookie |
| `/api/chat/create` | POST | `title` | `conversation_id`、`title`、`status` |
| `/api/chat/delete` | POST | `conversation_ids: []` | `deleted_count` |
| `/api/chat/update` | POST | `conversation_id`、`title` | `conversation_id`、`title` |
| `/api/chat/ls` | GET | — | 数组：`conversation_id`、`title`、`status`、`last_message_at` |
| `/api/chat/ls/{conversation_id}` | GET | — | 数组：`message_id`、`role`、`content`、`attachments`、`created_at` |
| `/api/attachment/upload` | POST | `conversation_id` + multipart `file` | `attachment_id`、`file_name`、`file_path`、`parse_status` |
| `/api/attachment/delete` | POST | `attachment_id` | `deleted: true` |
| `/api/attachment/get` | GET | `attachment_id` | 文件流（Content-Disposition 附件下载） |
| `/api/chat/ws-token` | POST | `conversation_id` | `websocket_token`、`expires_in`（秒） |
| `/api/chat/ws/chat` | WS | query：`websocket_token`、`conversation_id` | 见附录 D |
| `/api/admin/reload` | POST | — | `status`、`message` |
| `/api/tasks/{task_id}` | GET | — | `task_status`、`current_step`、`started_at`、`finished_at`、`error_message` |
| `/api/results/{task_id}` | GET | — | `problem_definition`、`key_metrics`、`evidence_list`、`conclusion_text`、`missing_data_text`、`next_action_text` |

补充约定：

- 发送分析问题经 **WS 上行消息**（`{"type": "user_message", "text": "...", "attachment_ids": []}`）而非 REST，保证任务事件与消息流同通道有序；
- 取消分析经 WS 上行 `{"type": "cancel", "task_id": ...}`；
- 管理端日志查询：`GET /api/admin/tasks/{task_id}/logs`（返回 `task_logs` 数组）。

## 附录 D：WebSocket 消息协议

### D.1 建连

`WS /api/chat/ws/chat?websocket_token=...&conversation_id=...`；鉴权失败关闭码 `4401`；心跳 ping/pong 30 秒。

### D.2 下行消息类型（服务端 → 客户端）

| type | 触发时机 | 字段 |
| --- | --- | --- |
| `message_start` | 本轮分析开始 | `task_id`、`conversation_id`、`message_id` |
| `message_delta` | 模型增量文本 | `task_id`、`message_id`、`delta_text` |
| `tool_start` | 工具开始执行 | `task_id`、`tool_name`、`tool_input_summary` |
| `tool_finish` | 工具执行完成 | `task_id`、`tool_name`、`tool_status`、`tool_result_summary` |
| `task_status` | 任务状态变化 | `task_id`、`task_status`、`current_step` |
| `result_ready` | 结构化结果已生成 | `task_id`、`result_id` |
| `error` | 本轮分析失败 | `task_id`、`error_code`、`error_message` |
| `done` | 本轮分析结束（终态） | `task_id`、`finished_at` |

### D.3 上行消息类型（客户端 → 服务端）

| type | 字段 | 说明 |
| --- | --- | --- |
| `user_message` | `text`、`attachment_ids: []` | 发起一轮分析（触发任务创建） |
| `cancel` | `task_id` | 取消运行中任务 |
| `ping` | — | 心跳（服务端回 `pong`） |

### D.4 时序示例（一轮成功分析）

```
client: user_message{text}
server: message_start → task_status{queued→running}
      → message_delta…（模型文本若干）
      → tool_start{sql_query} → tool_finish{sql_query}
      → message_delta…（可能多轮工具循环）
      → result_ready → task_status{success} → done
```

## 附录 E：分析输出 JSON Schema（六段结构）

`analysis_results.key_metrics_json` 与 `evidence_list_json` 的元素结构：

```json
// key_metrics_json: [...]
{
  "metric_name": "护肤品类退款率",
  "metric_value": 8.7,
  "metric_unit": "%",
  "metric_period": "2026-08-09 ~ 2026-08-15（周同比）"
}

// evidence_list_json: [...]
{
  "source_type": "sql",              // sql | file | text
  "source_name": "s2_refund.refund_orders 按 sku 聚合",
  "evidence_text": "SKU-A1023 周退款 47 单，占类目 31%，环比 +22pp",
  "related_metric": "护肤品类退款率",
  "confidence": "high"               // high | medium | low
}
```

Markdown 导出模板（`result_markdown` 的渲染骨架）：

```markdown
# 经营归因分析报告

## 1. 问题定义
{problem_definition}

## 2. 关键指标
| 指标 | 数值 | 单位 | 统计口径 |
| --- | --- | --- | --- |

## 3. 证据列表
| 来源类型 | 来源 | 证据 | 关联指标 | 置信度 |
| --- | --- | --- | --- | --- |

## 4. 归因结论
{conclusion_text}

## 5. 待补充数据
{missing_data_text}

## 6. 下一步建议
{next_action_text}
```

校验规则：`key_metrics` ≥ 1 条；`evidence_list` ≥ 1 条；`next_action` ≥ 2 条；不满足时结果生成按失败处理并写 `task_logs`。

## 附录 F：术语表

| 术语 | 定义 |
| --- | --- |
| 会话（Conversation） | 围绕一个经营问题的多轮分析单元，隔离上下文/附件/任务/结果 |
| 分析任务（Task） | 一条用户消息触发的一次 Agent 执行，五态状态机 |
| Agent | LLM + 工具调用编排（LangGraph）的分析执行体 |
| 工具（Tool） | Agent 可调用的受控能力：sql_query / file_read / file_write / text_search / generate_result_file |
| 六段结构化结果 | 问题定义、关键指标、证据列表、归因结论、待补充数据、下一步建议 |
| 上下文摘要（Context Summary） | 长会话历史消息的 LLM 压缩表示，用于控制 token 与保持主线 |
| WS 临时令牌 | 一次性、60 秒有效期的 WebSocket 建连凭证 |
| 认证中心 | 自建轻量 OAuth2 授权码服务，统一登录入口 |
| P0/P1 | 优先级分级：P0 为里程碑内必须完成，P1 为同期完成但可后置调优 |
