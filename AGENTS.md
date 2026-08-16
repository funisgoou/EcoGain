# EcoGain 经营归因分析系统 — 工作区说明

## 项目现状

**frontend/（Vue3 + Vite + TS，含 Mock 模式，见 frontend/README.md）与 backend / auth-server 均已实现**（后端 2026-08-16 完成核心代码，尚未连库联调）。全部设计以 `docs/` 为唯一依据，不要偏离文档自行发挥。

- 产品：单 Agent 多轮对话经营归因分析系统（查数 → 归因 → 追问 → 六段结构化报告）。
- 定位：POC 演示级（并发 ≤ 5、单机单实例），不过度设计。

## 目录结构

```
docs/
├── PRD-经营归因分析系统.md      # 需求基线 v1.1（含关键修正：无命令执行工具、附件四件套、双层存储）
├── SPEC-功能规格说明.md         # ~60 个功能点清单（P0/P1）+ 模块实现设计，功能点 ID 前缀 AUTH/CONV/MSG/ATT/WS/TASK/AGENT/RES/CTX/CFG/FE
├── API-接口设计文档.md          # 前后端接口唯一契约源（与 PRD 附录 C/D 冲突时以本文档为准）
├── DATA-数据设计文档.md         # 全部表结构 DDL、DTO、WS 消息、配置项清单
├── IMPL-实现蓝图-Python方法级.md # 每个文件每个方法的签名+伪代码，VibeCoding 核对底稿，完成后逐方法打勾 ✅
└── diagrams/                   # 系统架构图（excalidraw 源文件 + png）
designs/                        # 登录页/工作台设计稿（.pen 源文件 + png）
frontend/                       # 前端工程（已实现）：Vue3+Vite+TS+Pinia，Mock 模式 VITE_USE_MOCK=true 可无后端演示
```

**阅读顺序**：改任何敏感区域前，先读 IMPL 对应章节（它链接了 SPEC 功能点 ID），字段细节查 DATA，接口契约查 API 文档。

## 规划中的技术栈与架构（尚未落地）

- **backend**：Python 3.12 + FastAPI（:8000）+ LangGraph 1.x + SQLAlchemy 异步 + loguru
- **Python 包管理**：统一用 uv —— 加依赖 `uv add <pkg>`（锁死版本）、装环境 `uv sync`、运行走 `uv run`（如 `uv run uvicorn app.main:app`、`uv run pytest`）；禁止裸 `pip install`
- **auth-server**：独立 FastAPI 进程（:8001），OAuth2 授权码（/authorize /token /userinfo）
- **frontend**（已落地）：Vue3 + Vite（dev :5173，代理 /api、/auth → :8000）+ Pinia + axios（`withCredentials: true`）+ marked/dompurify；`VITE_USE_MOCK=true` 走内置 Mock
- **双层存储**：MySQL 系统库（10 张 OLTP 表）+ MySQL auth 库（3 表）；DuckDB 嵌入式分析库（4 schema 17 张表 + 附件动态表 `attachment_data_{id}`）
- **部署**：docker-compose 一键拉起（G5 验收目标）

## 硬性约定（实现时不可违背）

- **DuckDB 连接策略**：单 Database 实例（读写模式）+ 全局 asyncio.Lock 串行写。同进程不能混用 read_only 实例，"只读"靠 sql_query 工具的语句级约束落实：语句白名单（SELECT/WITH/SHOW/DESCRIBE）+ 关键词黑名单 + 强制 LIMIT 包裹 + 10s 超时。
- **安全红线**：Agent 无 shell/命令执行能力；文件工具仅目录白名单内读写；附件格式仅 csv/xlsx/txt/md。
- **消息 seq_no**：`conversations.next_seq_no` 计数器 + FOR UPDATE 原子分配，唯一索引兜底。
- **统一响应包**：`{code, message, data}`，code 前三位与 HTTP 状态一致（如 40101 登录态无效、50000 内部错误）；JSON 一律 snake_case；时间为 ISO 8601 毫秒本地时间。
- **认证**：Cookie 会话 `ecogain_session`（HttpOnly、SameSite=Lax、24h）；WS 用一次性令牌。
- **消息上行走 WS 上行通道**（不走 REST）；任务调度为单实例 asyncio，不引消息队列。
- **日志**：loguru 自定义 JSON sink（平铺字段）+ InterceptHandler 接管 uvicorn 日志 + trace_id 走 contextvars，禁止裸 print。

## 实现时的推进方式

- 按 IMPL 蓝图的文件树顺序实现（`backend/app` 结构已在 IMPL §2 完整规划），每完成一个方法在 `####` 行首打勾。
- 文档间冲突的优先级：API 文档 > PRD 附录；表结构以 DATA 文档为准；发现文档自身矛盾时先提出，不要静默改文档。

## Git 提交规范

- **每完成一个功能 commit 一次**：以功能点/功能模块为粒度（对应 SPEC 的功能点 ID 更佳），不要攒一大坨才提交，也不要把多个不相关功能混进同一个 commit。
- **commit message 用中文**，写清楚本次实现了哪些要点，格式约定：
  - 首行：`<类型>: <一句话概括>`（类型沿用 conventional commits：feat / fix / refactor / docs / chore / test）
  - 正文：列出具体实现要点（做了什么、关键决策、关联的功能点 ID），逐条写明，不写空话。
- 示例：

  ```
  feat: 实现附件上传与异步解析（ATT-1~3）

  - 上传接口落库 attachments 表，mimetype 双校验，文件名规范化
  - asyncio.create_task 异步解析，编码探测 + 列名规范化
  - 解析失败置 failed 并记录错误信息
  ```
