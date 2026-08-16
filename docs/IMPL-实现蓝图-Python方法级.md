# 经营归因分析系统 实现蓝图（Python 方法级）

## 1. 文档信息

| 项 | 内容 |
| --- | --- |
| 文档名称 | 实现蓝图（文件 → 方法 → 中文实现思路/伪代码） |
| 文档版本 | v1.0 |
| 创建日期 | 2026-08-16 |
| 上游文档 | SPEC v1.0（功能点清单）、API 文档（接口契约）、DATA 文档（表结构） |
| 用途 | **VibeCoding 核对底稿**：每个 py 文件的每个方法给出签名、思路、伪代码；标注功能点 ID（对应 SPEC 第 3 章），完成后逐项打勾 |

阅读约定：

- `#### 方法签名` 下的伪代码为中文思路 + Python 风格骨架，**不是可直接运行的代码**；边界处理（错误码、事务）以伪代码中的注释为准；
- 【关联】标注对应 SPEC 功能点 ID，核对时以此索引；
- 字段定义不在本文档重复：模型字段看 DATA 文档 §3/§4/§5，DTO 字段看 API 文档；
- 每个方法核对完成后，可在行首 `####` 处打勾：`#### ✅ def xxx()`。

## 2. 后端文件树总览（backend/app）

```
app/
├── main.py                      # 应用入口：装配、启停恢复
├── core/
│   ├── config.py                # 配置单例与热更新           → CFG-1/2
│   ├── logging.py               # 结构化日志 + trace 上下文   → 非功能
│   └── security.py              # SQL 校验 / 路径守卫 / 命名规范化 → AGENT-3/4, ATT-1
├── db/
│   ├── mysql.py                 # 异步引擎与会话工厂
│   └── duckdb.py                # DuckDB 单例 + 读写锁        → AGENT-3, ATT-3
├── models/                      # SQLAlchemy 模型（10 表）    → DATA §3
│   ├── user.py  conversation.py  message.py  attachment.py
│   ├── task.py  result.py  summary.py
│   └── ws_token.py  config.py  task_log.py
├── schemas/                     # Pydantic DTO               → API 文档
│   ├── common.py  chat.py  attachment.py
│   ├── task.py  result.py  admin.py  ws.py
├── api/
│   ├── deps.py                  # 公共依赖（登录态/DB/admin） → AUTH-6, CFG-6
│   ├── auth.py                  # 登录/回调/登出             → AUTH-4~7
│   ├── chat.py                  # 会话 CRUD/列表/历史/归档    → CONV-1~5, MSG-1
│   ├── attachment.py            # 上传/删除/下载             → ATT-1/6/7
│   ├── results.py               # 任务/结果/下载             → TASK-7, RES-2/4
│   └── admin.py                 # reload/日志                → CFG-2/3
├── ws/
│   ├── manager.py               # 连接管理器 + 心跳巡检       → WS-3/4
│   └── router.py                # WS 端点 + 上行分发         → WS-2/5/6
├── services/
│   ├── conversation_service.py  # 会话业务 + 级联删除         → CONV-1~5
│   ├── message_service.py       # 消息落库 + seq_no          → MSG-1~3
│   ├── attachment_service.py    # 解析/导入/恢复             → ATT-2~5/8
│   ├── task_service.py          # 任务状态机/取消/超时/恢复   → TASK-1~6
│   ├── result_service.py        # 结果落库/渲染/导出          → RES-1~4
│   ├── summary_service.py       # 上下文摘要压缩             → CTX-1/2
│   └── llm_gateway.py           # 多供应商网关 + 重试         → AGENT-8
├── analysis/
│   ├── state.py                 # Agent 状态定义             → AGENT-1
│   ├── graph.py                 # LangGraph 图 + 流式映射     → AGENT-1/9
│   ├── context.py               # 上下文拼装                 → AGENT-2
│   ├── output.py                # 六段结构化输出             → AGENT-7
│   └── tools/
│       ├── sql_query.py         # 只读 SQL 工具              → AGENT-3
│       ├── file_tools.py        # file_read / file_write     → AGENT-4
│       ├── text_search.py       # 文本检索                   → AGENT-5
│       └── gen_result.py        # 结果文件生成               → AGENT-6
└── seeds/
    └── init_analytics.py        # DuckDB 建库灌数            → F10
```

---

## 3. app/main.py — 应用入口

【关联】TASK-5（僵尸恢复）、ATT-8（附件恢复）、非功能（优雅停机、健康检查）

#### create_app() -> FastAPI

- 思路：应用工厂。装配一切：日志 → 配置 → 路由 → 中间件 → 异常处理器 → 生命周期。保持 main.py 只做装配，业务零逻辑。

```python
def create_app() -> FastAPI:
    setup_logging()                       # core.logging：loguru JSON 输出
    app = FastAPI(lifespan=lifespan)      # 生命周期钩子见下
    app.include_router(auth.router)       # /auth/*
    app.include_router(chat.router)       # /api/chat/*
    app.include_router(attachment.router) # /api/attachment/*
    app.include_router(results.router)    # /api/tasks /api/results
    app.include_router(admin.router)      # /api/admin/*
    app.include_router(ws.router)         # /api/chat/ws/chat

    # 全局异常处理器：任何未捕获异常 → 统一响应包 {code:50000}
    # 日志带堆栈摘要 + trace_id；不向前端透出内部细节
    @app.exception_handler(Exception)
    async def unhandled(request, exc):
        log.error("unhandled", exc_info=exc)
        return json_response(code=50000, message="服务器内部错误")

    # 会话校验中间件：白名单（/auth/login /auth/callback /healthz /docs）
    # 外全部要求登录态，失败返回 40101
    app.add_middleware(AuthSessionMiddleware, whitelist=[...])
    return app
```

#### lifespan(app) -> AsyncContextManager

- 思路：启动时做三件恢复 + 两个后台协程；停机时优雅关闭。恢复逻辑放服务层，这里只编排。

```python
@asynccontextmanager
async def lifespan(app):
    cfg = load_configs()                       # CFG-1：读 system_configs 全量
    engine = init_mysql()                      # 建异步引擎（db.mysql）
    duck = DuckDBManager(cfg.duckdb_path)      # 打开单例（读写模式）
    await recover_zombie_tasks()               # TASK-5：queued/running → failed
    await recover_stuck_attachments()          # ATT-8：pending/parsing → failed
    task_cleaner = spawn(cleanup_expired_tokens_loop())   # websocket_tokens/auth_codes 每小时清理（DATA §7.3）
    hb = spawn(heartbeat_monitor())            # WS-4：60s 容限巡检
    yield
    # —— 优雅停机 ——
    stop_accepting_new_tasks()                 # 拒绝新的 user_message
    await wait_running_tasks(timeout=30)       # 等运行中任务
    force_fail_remaining()                     # 超时者置 failed（同僵尸逻辑）
    duck.close(); hb.cancel(); task_cleaner.cancel(); engine.dispose()
```

#### GET /healthz

- 思路：无鉴权探针。三项检查：MySQL ping、DuckDB ping、llm 配置存在。

```python
async def healthz():
    ok_mysql = await mysql_ping()          # SELECT 1
    ok_duck  = duckdb_ping()               # SELECT 1
    ok_llm   = get_config("llm.model") is not None
    return {"status": "ok" if all([ok_mysql, ok_duck, ok_llm]) else "degraded", ...}
```

---

## 4. app/core/config.py — 配置单例与热更新

【关联】CFG-1、CFG-2

#### DEFAULTS: dict

- 思路：全部 14 个配置项的缺省值与校验规则（与 DATA §6.5 一字不差），DB 缺行时兜底。

```python
DEFAULTS = {
  "llm.provider": ("zhipu", str, nonempty),
  "llm.base_url": ("https://open.bigmodel.cn/api/paas/v4", str, is_url),
  "llm.model":    ("glm-4.6", str, nonempty),
  "llm.api_key_ref": ("LLM_API_KEY", str, nonempty),      # 环境变量引用名
  "llm.temperature":  (0.2, float, range(0, 1)),
  "agent.max_tool_rounds": (15, int, range(5, 50)),
  "agent.task_timeout_seconds": (120, int, range(30, 600)),
  "agent.context_rounds": (20, int, range(5, 100)),
  "agent.context_token_budget": (8000, int, range(2000, 100000)),
  "agent.sql_row_limit": (1000, int, range(100, 10000)),
  "agent.sql_timeout_seconds": (10, int, range(1, 60)),
  "datasource.duckdb_path": ("/data/analytics/analytics.duckdb", str, nonempty),
  "feature.attachment_enabled": (True, bool, none),
  "feature.export_enabled": (True, bool, none),
}
```

#### class SystemConfig

- 思路：进程内配置快照对象。**不可变**：reload 时整体替换引用（写锁），读侧无锁。

```python
class SystemConfig:
    _instance: "SystemConfig | None" = None
    _lock = Lock()

    def __init__(self, raw: dict[str, str]):
        # 逐项按 DEFAULTS 的类型转换 + 校验；非法值 → 抛 ConfigError（启动即失败）
        # 敏感项 llm.api_key_ref 只存引用名，取真实 key 走 os.environ
        self._values = {k: cast_and_validate(k, v) for k, v in merged.items()}

    @property
    def sql_row_limit(self) -> int: ...        # 便捷访问器若干（每个配置项一个）
```

#### load_configs(session) -> SystemConfig

- 思路：DB 全量读 → 与 DEFAULTS 合并（DB 优先）→ 构造快照 → 替换单例。

```python
async def load_configs(session) -> SystemConfig:
    rows = await session.execute(select(SystemConfigModel))     # system_configs 全表
    raw = {r.config_key: r.config_value for r in rows}
    merged = {**{k: str(v[0]) for k, v in DEFAULTS.items()}, **raw}
    with _lock:
        SystemConfig._instance = SystemConfig(merged)
    return SystemConfig._instance
```

#### get_config() -> SystemConfig

- 思路：读侧入口。返回当前单例；未初始化时抛错（启动顺序保证不会发生）。

```python
def get_config() -> SystemConfig:
    if SystemConfig._instance is None:
        raise RuntimeError("config not loaded")   # 防御：lifespan 必先执行
    return SystemConfig._instance
```

#### reload_config(session) -> ReloadResult

- 思路：CFG-2 核心。**先校验后替换**：新值全部合法才切换；失败返回 error 且旧配置继续生效。成功后联动失效 LLM 客户端缓存。

```python
async def reload_config(session) -> ReloadResult:
    try:
        new_cfg = await load_configs(session)     # 内部已整体替换单例
    except ConfigError as e:
        return ReloadResult(status="error", message=f"配置校验失败：{e}")
    llm_gateway.invalidate()                      # 下次调用重建 client
    return ReloadResult(status="ok", message=f"重载 {len(...)} 项配置，LLM 客户端已重建")
```

---

## 5. app/core/logging.py — 结构化日志

【关联】非功能（SPEC §7）

#### setup_logging()

- 思路：loguru 配置为 JSON 行式输出 stdout。自定义 sink 展平字段（loguru 原生 `serialize=True` 会把上下文藏在 `record.extra` 里，不满足 SPEC 的平铺字段约定）；同时装 InterceptHandler 把 uvicorn/sqlalchemy 标准库日志接管进同一管道。

```python
def _json_sink(message):                        # 平铺 JSON sink
    r = message.record
    entry = {
        "ts": r["time"].isoformat(timespec="milliseconds"),
        "level": r["level"].name,
        "msg": r["message"],
        **r["extra"],                           # trace_id/task_id/name 等平铺到顶层
    }
    sys.stdout.write(json.dumps(entry, ensure_ascii=False) + "\n")  # 中文原样输出

def setup_logging():
    logger.remove()                             # 去掉默认 stderr handler
    logger.add(_json_sink, level="INFO")
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    # InterceptHandler：标准库 logging.Record → loguru，uvicorn access/error 同管道输出
```

#### get_logger(name: str)

- 思路：薄封装，统一入口。`log = get_logger(__name__)`；name 经 bind 进 extra，由 patcher 注入每条日志。

```python
def get_logger(name): return logger.bind(name=name)
```

#### class TraceCtx

- 思路：基于 contextvars 的链路上下文（纯 ContextVar，不依赖日志库）。WS user_message 生成 trace_id 后 set；loguru patcher 每条日志自动把 contextvars 合入 extra，同协程所有日志自动携带。

```python
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_task_id: ContextVar[int] = ContextVar("task_id", default=0)

logger.configure(patcher=lambda r: r["extra"].update(
    trace_id=_trace_id.get(), task_id=_task_id.get(),
    conversation_id=_conv_id.get(), user_id=_user_id.get(),
))

class TraceCtx:
    @staticmethod
    def start() -> str:
        tid = uuid4().hex[:12]                   # trace_id 生成规则（SPEC §7）
        _trace_id.set(tid)
        return tid
    @staticmethod
    def bind_task(task_id: int):
        _task_id.set(task_id)
```

---

## 6. app/core/security.py — 安全工具集

【关联】AGENT-3（SQL 校验）、AGENT-4（路径守卫）、ATT-1（文件名规范化）、ATT-3（列名规范化）

#### SQL_ALLOWED_STARTERS / SQL_BLACKLIST

- 思路：两份静态词表，安全约束的唯一定义点（与 SPEC 4.6 一致）。

```python
SQL_ALLOWED_STARTERS = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC"}
SQL_BLACKLIST = {  # 词边界匹配、大小写不敏感
  "INSERT","UPDATE","DELETE","MERGE","CREATE","ALTER","DROP","TRUNCATE","REPLACE",
  "GRANT","REVOKE","ATTACH","DETACH","COPY","EXPORT","IMPORT","CALL","PRAGMA","INSTALL","LOAD",
}
```

#### strip_sql_comments(sql: str) -> str

- 思路：去掉 `-- 行注释` 与 `/* 块注释 */`，防止用注释绕过黑名单（如 `DELE/**/TE`）。

```python
def strip_sql_comments(sql: str) -> str:
    # 正则先删 /* ... */（非贪婪），再删 -- 至行尾
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.S).replace("--", " /*")  # 简化示意：
    # 实际实现：re.sub(r"--[^\n]*", " ", ...) 后再压缩空白
```

#### validate_sql(sql: str) -> str | SqlRejected

- 思路：AGENT-3 核心。四道闸门：注释剥离 → 分号检测（禁多语句）→ 首词白名单 → 黑名单词边界扫描。被拒返回结构化原因（供 Agent 自我修正）。

```python
def validate_sql(sql: str):
    s = strip_sql_comments(sql).strip()
    s = re.sub(r"\s+", " ", s)
    if ";" in s.rstrip(";"):                       # 仅允许最末一个分号
        return SqlRejected("检测到多条语句，仅允许单条查询")
    first = s.split(" ", 1)[0].upper()
    if first not in SQL_ALLOWED_STARTERS:
        return SqlRejected(f"仅允许 SELECT/WITH/SHOW/DESCRIBE 开头，当前：{first}")
    for word in SQL_BLACKLIST:
        if re.search(rf"\b{word}\b", s, re.IGNORECASE):
            return SqlRejected(f"语句包含被禁止的关键词：{word}")
    return s                                        # 返回清洗后的 SQL
```

#### wrap_limit(sql: str, max_rows: int) -> str

- 思路：外层包裹 LIMIT。已带合规 LIMIT 的原样放行（正则识别结尾 `LIMIT n`）。

```python
def wrap_limit(sql: str, max_rows: int) -> str:
    if m := re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.IGNORECASE):
        if int(m.group(1)) <= max_rows:
            return sql                              # 自带且不超限
    return f"SELECT * FROM ({sql}) AS __limited__ LIMIT {max_rows}"
```

#### safe_path(user_id, conversation_id, relative, roots=("uploads","workspace")) -> Path | None

- 思路：AGENT-4/ATT-7 路径守卫。join + resolve 后必须落在 `root/{uid}/{cid}/` 前缀内；否则返回 None（调用方报 50002）。

```python
def safe_path(uid, cid, relative, roots) -> Path | None:
    for root in roots:
        base = (DATA_DIR / root / str(uid) / str(cid)).resolve()
        target = (base / relative).resolve()
        # Windows 下 casefold 比较，防盘符大小写差异；resolve 已消解 ../ 与符号链接
        if os.path.commonpath([str(base), str(target)]).casefold() == str(base).casefold():
            return target
    return None
```

#### secure_filename(name: str) -> str

- 思路：ATT-1。去路径分隔符/`..`/控制字符，空则给 `file`；保留中文与常见安全字符。

```python
def secure_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]          # 只留文件名部分
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "", name)       # 控制符与 Windows 非法字符
    return name.strip(". ") or "file"                      # 防 ".gitignore" 类陷阱兜底
```

#### normalize_column_name(raw: str, index: int, used: set) -> str

- 思路：ATT-3 列名规范化。小写、空白→下划线、非法剔除、空名 `col_{i}`、重名追加 `_2`。

```python
def normalize_column_name(raw, index, used):
    col = re.sub(r"[^\w\u4e00-\u9fff]+", "_", str(raw).strip().lower()).strip("_")
    col = col or f"col_{index}"
    if col in used:                                # 重名：name → name_2 → name_3 …
        n = 2
        while f"{col}_{n}" in used: n += 1
        col = f"{col}_{n}"
    used.add(col)
    return col
```

---

## 7. app/db/mysql.py — MySQL 异步引擎

【关联】基础设施

#### init_mysql() -> AsyncEngine

- 思路：进程级单例引擎。连接串来自环境变量（不在 system_configs——DB 连接本身不能存 DB 里）。pool_size 按 POC 并发 ≤5 设 10。

```python
_engine: AsyncEngine | None = None

def init_mysql() -> AsyncEngine:
    global _engine
    url = f"mysql+asyncmy://{env.MYSQL_USER}:{env.MYSQL_PASSWORD}@{env.MYSQL_HOST}:3306/ecogain?charset=utf8mb4"
    _engine = create_async_engine(url, pool_size=10, pool_pre_ping=True, echo=False)
    return _engine
```

#### get_session() -> AsyncSession（FastAPI 依赖）

- 思路：请求级会话，自动提交/回滚。所有路由 `session: AsyncSession = Depends(get_session)`。

```python
async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSession(_engine, expire_on_commit=False) as s:
        async with s.begin():          # 请求成功自动 COMMIT，异常自动 ROLLBACK
            yield s
```

#### mysql_ping() -> bool

- 思路：健康检查。`SELECT 1` 包异常返回 False。

---

## 8. app/db/duckdb.py — DuckDB 单例与读写锁

【关联】AGENT-3（查询）、ATT-3/6（导入/删表）。实现决策见 SPEC 4.6：**单 Database 实例（读写模式）+ 全局 asyncio.Lock 串行写 + 查询走语句级校验**。

#### class DuckDBManager

- 思路：进程内唯一实例。打开 `analytics.duckdb`（读写）。DuckDB Python API 是同步的，全部调用丢进 `asyncio.to_thread` 防阻塞事件循环。

```python
class DuckDBManager:
    def __init__(self, db_path: str):
        self._write_lock = asyncio.Lock()                  # 全局写锁（附件导入/删表）
        self._conn = duckdb.connect(db_path)               # 唯一读写连接

    # —— 查询（Agent sql_query 专用）——
    async def execute_query(self, sql: str, timeout_s: int) -> QueryResult:
        # 语句级安全已由 core.security.validate_sql 在调用方完成
        # to_thread 执行 + asyncio.wait_for 超时；超时不可真正 kill duckdb 线程，
        # 记 warn 日志并返回超时错误（POC 接受；SELECT 只读无副作用）
        try:
            rel = await asyncio.wait_for(asyncio.to_thread(self._conn.sql, sql), timeout_s)
            columns, rows = rel.columns, rel.fetchall()
            return QueryResult(columns=columns, rows=rows[:row_limit], truncated=len(rows) > row_limit)
        except asyncio.TimeoutError:
            return QueryResult(error=f"SQL 执行超过 {timeout_s}s 超时")

    # —— 写（附件导入/DROP 表，后台链路专用）——
    @asynccontextmanager
    async def write_txn(self):
        async with self._write_lock:                       # 串行化所有写
            yield self._conn                               # 调用方在 to_thread 中执行 DDL/DML

    def close(self): self._conn.close()
```

#### duckdb_ping() -> bool

- 思路：`SELECT 1`；健康检查用。

#### list_attachment_tables() -> list[str]

- 思路：遍历 `information_schema.tables` where table_schema='attachments'，供会话删除时批量 DROP。


---

## 9. app/models/ — SQLAlchemy 模型（10 个文件）

【关联】DATA 文档 §3（字段以该文档为准，此处只列文件、类名与特有方法）

| 文件 | 类（表） | 特有方法/说明 |
| --- | --- | --- |
| models/user.py | `User`（users） | `upsert_from_oauth(external_id, username, display_name, role)`：类方法，按 external_user_id upsert（AUTH-5 用） |
| models/conversation.py | `Conversation`（conversations） | 含 `next_seq_no` 计数器；无方法，逻辑在 service |
| models/message.py | `Message`（messages） | 无方法；`task_id` 为实现扩展字段 |
| models/attachment.py | `Attachment`（attachments） | 无方法；`duckdb_table`、`error_message` 为实现扩展字段 |
| models/task.py | `AnalysisTask`（analysis_tasks） | 常量类属性：`ACTIVE_STATUSES = ("queued","running")`（并发检查用，TASK-2） |
| models/result.py | `AnalysisResult`（analysis_results） | 无方法；一任务一行（UK task_id） |
| models/summary.py | `ContextSummary`（context_summaries） | 无方法 |
| models/ws_token.py | `WsToken`（websocket_tokens） | 无方法；原子消费 SQL 在 service 层（WS-2） |
| models/config.py | `SystemConfigModel`（system_configs） | 无方法 |
| models/task_log.py | `TaskLog`（task_logs） | 无方法 |

> 全部模型统一：`id` 主键、`DATETIME(3)` 映射 `DateTime(3)`、枚举用 `String(length)` + 应用层校验（与 DDL 的 CHECK 双保险）。Alembic 迁移基线 `0001_initial` + `0002_seed_configs`（DATA §3.11）。

## 10. app/schemas/ — Pydantic DTO（7 个文件）

【关联】API 文档（字段以该文档为准，此处只列文件与关键模型）

| 文件 | 模型 | 说明 |
| --- | --- | --- |
| schemas/common.py | `ApiResponse[T]`、`PageParams` | 统一响应包构造器 `ok(data)` / `err(code, msg)` |
| schemas/chat.py | `CreateChatReq/Resp`、`UpdateChatReq`、`DeleteChatReq/Resp`、`ChatListItem`、`MessageItem` | MessageItem 含扩展字段 message_type/tool_name/tool_status/task_id |
| schemas/attachment.py | `AttachmentItem`、`UploadResp` | parse_status 枚举校验 |
| schemas/task.py | `TaskItem` | 五态枚举 |
| schemas/result.py | `ResultItem`、`KeyMetric`、`Evidence` | 六段结构（与 analysis/output.py 共享定义，从此处 import） |
| schemas/admin.py | `ReloadResp`、`TaskLogItem` | — |
| schemas/ws.py | `WsDown`/`WsUp` 判别联合（pydantic discriminated union by `type`） | 上行解析失败 → 忽略该帧并 warn（协议健壮性） |

#### schemas/common.py — ok() / err()

- 思路：统一响应包的两个快捷构造，路由层只用这两个出口。

```python
def ok(data=None): return {"code": 0, "message": "ok", "data": data}
def err(code, msg): return {"code": code, "message": msg, "data": None}
```


---

## 11. app/api/deps.py — 公共依赖

【关联】AUTH-6、CFG-6

#### get_current_user(request, session) -> User

- 思路：登录态依赖。从 Cookie `ecogain_session` 查内存会话表（lifespan 维护的 dict，24h 过期），回查 users。disabled 用户即时踢出。

```python
async def get_current_user(request, session) -> User:
    token = request.cookies.get("ecogain_session")
    sess = SESSION_STORE.get(token)                       # 内存会话表
    if not sess or sess.expired():
        raise BizError(40101, "登录态无效")
    user = await session.get(User, sess.user_id)
    if not user or user.status == "disabled":
        SESSION_STORE.pop(token, None); raise BizError(40101, "用户不可用")
    return user
```

#### require_admin(user=Depends(get_current_user)) -> User

- 思路：管理接口守卫。role != admin → 40301。

```python
async def require_admin(user) -> User:
    if user.role != "admin": raise BizError(40301, "需要管理员权限")
    return user
```

#### assert_conversation_owned(session, user, conversation_id) -> Conversation

- 思路：**所有会话级资源的统一前置校验**（PRD 4.2 数据隔离）。不存在/已删除 → 40401；非本人 → 40301。

```python
async def assert_conversation_owned(session, user, cid) -> Conversation:
    conv = await session.get(Conversation, cid)
    if not conv or conv.status == "deleted": raise BizError(40401, "会话不存在")
    if conv.user_id != user.id: raise BizError(40301, "无权访问该会话")
    return conv
```

#### BizError(code, message) — 业务异常类

- 思路：路由/服务层抛出，全局异常处理器翻译为统一响应包（HTTP 状态 = code 前三位）。

---

## 12. app/api/auth.py — 登录/回调/登出

【关联】AUTH-4~7

#### GET /auth/login — route_login(request)

- 思路：生成 state（60s TTL 存内存 dict）→ 302 跳认证中心 /authorize。

```python
async def route_login(request):
    state = secrets.token_urlsafe(16)
    PENDING_STATES[state] = now + 60                  # 内存暂存（单实例）
    url = f"{AUTH_BASE}/authorize?client_id=ecogain-web&redirect_uri={PUBLIC_BASE}/auth/callback&response_type=code&state={state}"
    return RedirectResponse(url)
```

#### GET /auth/callback — route_callback(code, state, error)

- 思路：五步链路（SPEC 4.1）。任何一步失败 302 到前端错误页带 error 参数。

```python
async def route_callback(code=None, state=None, error=None):
    if error: return redirect_frontend(f"/auth/callback?error={error}")
    if state not in PENDING_STATES or PENDING_STATES[state] < now:
        return redirect_frontend("/auth/callback?error=40101")     # state 校验失败
    PENDING_STATES.pop(state)                                        # 一次性
    token = await exchange_code(code)                                # POST auth-server /token
    info = await fetch_userinfo(token)                               # GET /userinfo
    user = await User.upsert_from_oauth(session, info)               # 进系统库
    if user.status == "disabled": return redirect_frontend("/auth/callback?error=40301")
    session_token = SESSION_STORE.create(user_id=user.id, ttl=24h)   # 内存会话
    resp = RedirectResponse(f"{FRONTEND_BASE}/workbench")
    resp.set_cookie("ecogain_session", session_token, httponly=True, samesite="lax")
    return resp
```

#### exchange_code(code) -> str | fetch_userinfo(token) -> dict

- 思路：httpx 调认证服务两接口；异常透传给 callback 的错误分支。

#### POST /auth/logout — route_logout(request)

- 思路：删内存会话 + 清 Cookie；返回 ok。

---

## 13. app/api/chat.py — 会话与消息路由

【关联】CONV-1~5、MSG-1、WS-1

#### POST /api/chat/create — route_create(body, user, session)

```python
async def route_create(body, user, session):
    title = (body.title or "新分析")[:200]              # 缺省与截断（40001 兜底）
    conv = await conversation_service.create(user, title)
    return ok(CreateChatResp(conversation_id=conv.id, title=conv.title, status=conv.status))
```

#### POST /api/chat/delete — route_delete(body, user, session)

```python
async def route_delete(body, user, session):
    if not 1 <= len(body.conversation_ids) <= 50: raise BizError(40001, "conversation_ids 需 1~50 个")
    await conversation_service.delete_many(user, body.conversation_ids)   # 级联逻辑全在 service
    return ok({"deleted_count": len(body.conversation_ids)})
```

#### POST /api/chat/update — route_update(body, user, session)

```python
async def route_update(body, user, session):
    conv = await assert_conversation_owned(session, user, body.conversation_id)
    # title 与可选 status 一并更新（status 仅允许 active↔archived 切换 → CONV-5 归档/恢复）
    # ⚠ 实现扩展：API 文档 4.3 仅定义 title；status 为归档功能补充字段，需同步更新 API 文档
    return ok({"conversation_id": conv.id, "title": conv.title})
```

#### GET /api/chat/ls — route_list(include_archived, user, session)

```python
async def route_list(include_archived=False, ...):
    statuses = ("active","archived") if include_archived else ("active",)
    rows = await conversation_service.list_by_user(user, statuses)      # last_message_at 倒序
    return ok([ChatListItem(...) for r in rows])
```

#### GET /api/chat/ls/{conversation_id} — route_history(cid, user, session)

```python
async def route_history(cid, user, session):
    await assert_conversation_owned(session, user, cid)
    msgs = await message_service.list_messages(cid)                     # seq_no 升序
    # 聚合每条 user 消息的 attachments（attachment.message_id 关联）
    return ok([MessageItem(...) for m in msgs])
```

#### POST /api/chat/ws-token — route_ws_token(body, user, session)

```python
async def route_ws_token(body, user, session):
    await assert_conversation_owned(session, user, body.conversation_id)
    token, expires_in = await ws_service.issue_token(user, body.conversation_id)   # 60s 一次性
    return ok({"websocket_token": token, "expires_in": expires_in})
```

---

## 14. app/api/attachment.py — 附件路由

【关联】ATT-1、ATT-6、ATT-7

#### POST /api/attachment/upload — route_upload(conversation_id, file, user, session)

```python
async def route_upload(conversation_id: int = Form(...), file: UploadFile = File(...)):
    if not get_config().attachment_enabled: raise BizError(40301, "附件功能已关闭")   # CFG-5
    await assert_conversation_owned(session, user, conversation_id)
    att = await attachment_service.save_upload(user, conversation_id, file)          # 校验+落盘+建行+触发解析
    return ok(UploadResp(att.id, att.file_name, att.file_path, att.parse_status))
```

#### POST /api/attachment/delete — route_delete(body, user, session)

```python
async def route_delete(body, user, session):
    att = await attachment_service.get_owned(user, body.attachment_id)     # 40401/40301 内部处理
    if att.parse_status == "parsing": raise BizError(40001, "解析中的附件暂不可删除")
    await attachment_service.delete_attachment(att)                        # DB+文件+DuckDB 表级联
    return ok({"deleted": True})
```

#### GET /api/attachment/get — route_download(attachment_id, user, session)

```python
async def route_download(attachment_id, user, session):
    att = await attachment_service.get_owned(user, attachment_id)
    path = safe_path(att.user_id, att.conversation_id, att.file_path, roots=("uploads",))
    if not path or not path.exists(): raise BizError(40401, "附件文件不存在")        # 路径穿越在此拦截
    return FileResponse(path, filename=att.file_name)                    # 自动 Content-Disposition
```

---

## 15. app/api/results.py — 任务与结果路由

【关联】TASK-7、RES-2、RES-4

#### GET /api/tasks/{task_id} — route_get_task(task_id, user, session)

```python
async def route_get_task(task_id, user, session):
    task = await task_service.get_owned(user, task_id)            # 非本人 40301 / 不存在 40401
    return ok(TaskItem(...))
```

#### GET /api/results/{task_id} — route_get_result(task_id, user, session)

```python
async def route_get_result(task_id, user, session):
    result = await result_service.get_by_task(user, task_id)      # 无结果 → 40401"任务未产生结果"
    return ok(ResultItem(..., exported=result.result_file_path is not None))
```

#### GET /api/results/{task_id}/download — route_download(task_id, user, session)

```python
async def route_download(task_id, user, session):
    if not get_config().export_enabled: raise BizError(40301, "导出功能已关闭")      # CFG-5
    path = await result_service.ensure_export_file(user, task_id)  # 已有直接返回；无则补渲染落盘
    return FileResponse(path, filename=f"result_{task_id}.md", media_type="text/markdown")
```

---

## 16. app/api/admin.py — 管理路由

【关联】CFG-2、CFG-3

#### POST /api/admin/reload — route_reload(user=Depends(require_admin), session)

```python
async def route_reload(user, session):
    result = await reload_config(session)              # core.config 热更新（先校验后替换）
    return ok(ReloadResp(status=result.status, message=result.message))
```

#### GET /api/admin/tasks/{task_id}/logs — route_task_logs(task_id, user, session)

```python
async def route_task_logs(task_id, user, session):
    logs = await task_service.get_logs(task_id)        # created_at 升序
    return ok([TaskLogItem(...) for l in logs])
```


---

## 17. app/ws/manager.py — 连接管理器

【关联】WS-3、WS-4

#### class ConnectionManager

- 思路：`dict[conversation_id, dict[user_id, WebSocket]]` 内存注册表 + 每连接一把发送锁。POC 单实例内存版（SPEC 4.4）。

```python
class ConnectionManager:
    def __init__(self):
        self._conns: dict[int, dict[int, WebSocket]] = {}
        self._meta: dict[tuple[int,int], ConnMeta] = {}     # last_active、send_lock

    async def connect(self, cid, uid, ws) -> bool:
        # 同 (cid,uid) 已有连接 → 关旧留新（多标签页）
        old = self._conns.get(cid, {}).get(uid)
        if old: await old.close(code=1000)
        self._conns.setdefault(cid, {})[uid] = ws
        self._meta[(cid, uid)] = ConnMeta(last_active=now(), send_lock=Lock())

    def disconnect(self, cid, uid):
        self._conns.get(cid, {}).pop(uid, None); self._meta.pop((cid, uid), None)

    async def broadcast(self, cid, message: dict):
        # 对该会话所有连接推送；send 前取该连接的锁串行化（防两协程交织半帧 JSON）
        for uid, ws in list(self._conns.get(cid, {}).items()):
            try:
                async with self._meta[(cid,uid)].send_lock:
                    await ws.send_json(message)
            except Exception:
                self.disconnect(cid, uid)                   # 死连接静默摘除

    def touch(self, cid, uid): self._meta[(cid,uid)].last_active = now()
```

#### heartbeat_monitor() — 后台协程（lifespan 启动）

- 思路：WS-4。每 15s 扫描全部连接 meta，last_active 距今 > 60s → close(4408)。

```python
async def heartbeat_monitor():
    while True:
        await asyncio.sleep(15)
        for (cid, uid), meta in list(MANAGER._meta.items()):
            if now() - meta.last_active > timedelta(seconds=60):
                await MANAGER._conns[cid][uid].close(code=4408)   # 前端见 4408 立即重连
```

---

## 18. app/ws/router.py — WS 端点与上行分发

【关联】WS-2、WS-5、WS-6、MSG-3、TASK-1/2

#### issue_token(user, conversation_id) -> (token, expires_in)

- 思路：WS-1。token_urlsafe(32) 插 websocket_tokens（expires_at=now+60s）。

```python
async def issue_token(user, cid):
    token = secrets.token_urlsafe(32)
    session.add(WsToken(user_id=user.id, conversation_id=cid, token=token,
                        expires_at=now() + timedelta(seconds=60)))
    return token, 60
```

#### consume_token(token, cid, uid) -> bool

- 思路：WS-2。**原子消费**——单条 UPDATE 的 WHERE 同时校验四件事（存在/未消费/未过期/归属），affected==1 才放行。

```python
async def consume_token(token, cid, uid) -> bool:
    result = await session.execute(text("""
        UPDATE websocket_tokens SET consumed_at = NOW(3)
        WHERE token = :t AND conversation_id = :cid AND user_id = :uid
          AND expires_at > NOW(3) AND consumed_at IS NULL
    """), {"t": token, "cid": cid, "uid": uid})
    return result.rowcount == 1
```

#### websocket_endpoint(websocket, websocket_token, conversation_id)

- 思路：WS 主入口。鉴权 → 注册 → 收发循环（任何帧都 touch 心跳）→ finally 摘除。

```python
async def websocket_endpoint(ws, websocket_token, conversation_id):
    user = await try_get_user_from_cookie(ws)                 # 升级请求带同一会话 Cookie
    if not user or not await consume_token(websocket_token, conversation_id, user.id):
        await ws.close(code=4401); return                     # 令牌无效/过期/已消费
    await ws.accept(); await MANAGER.connect(conversation_id, user.id, ws)
    try:
        while True:
            raw = await ws.receive_json(); MANAGER.touch(cid, uid)
            msg = WsUp.model_validate(raw)                    # 非法帧 warn 后忽略
            match msg.type:
                case "ping":       await ws.send_json({"type": "pong"})
                case "user_message": await handle_user_message(user, cid, msg)   # ↓
                case "cancel":      await task_service.cancel_task(user, cid, msg.task_id)
    except WebSocketDisconnect:
        pass
    finally:
        MANAGER.disconnect(cid, uid)
```

#### handle_user_message(user, cid, msg)

- 思路：三道前置检查后进任务链路。检查失败经 WS 下发 error（task_id=0，API 文档 8.3 约定）。

```python
async def handle_user_message(user, cid, msg):
    TraceCtx.start()                                          # 生成本轮 trace_id
    async def reject(code, text): await MANAGER.broadcast(cid, {"type":"error","task_id":0,"error_code":code,"error_message":text})
    if len(msg.text or "") > 4000:                  return await reject(40001, "问题长度超限")
    # 附件归属 + 就绪校验（ATT：未 ready 的附件整条拒绝）
    atts = await attachment_service.get_ready_attachments(cid, user.id, msg.attachment_ids)
    if atts is None:                               return await reject(40002, "附件不存在或未就绪")
    if await task_service.has_active_task(cid):    return await reject(40901, "当前会话已有运行中的任务")   # MSG-3
    if await task_service.count_active_global() >= 5: return await reject(42901, "并发任务已达上限")        # TASK-2
    await task_service.start_task(user, cid, msg.text, msg.attachment_ids)   # → 后续事件全走 broadcast
```

---

## 19. app/services/conversation_service.py — 会话业务

【关联】CONV-1~5

#### create(user, title) -> Conversation

```python
async def create(user, title):
    conv = Conversation(user_id=user.id, title=title, status="active", next_seq_no=0)
    session.add(conv); await flush()
    return conv
```

#### list_by_user(user, statuses) -> list[Conversation]

```python
async def list_by_user(user, statuses):
    # WHERE user_id=:uid AND status IN :statuses ORDER BY COALESCE(last_message_at, created_at) DESC
    return await session.execute(select(Conversation).where(...).order_by(desc(...)))
```

#### delete_many(user, conversation_ids)

- 思路：CONV-4 核心，SPEC 4.2 的级联实现。**逐会话事务**，DB 成功后才清磁盘。

```python
async def delete_many(user, ids):
    convs = await session.execute(select(Conversation).where(Conversation.id.in_(ids)))
    if any(c.user_id != user.id for c in convs): raise BizError(40301, "包含无权限的会话")   # 整批拒绝
    for conv in convs:
        # 0) 进行中任务先取消等待终态（≤5s）
        await task_service.cancel_if_active(conv.id, wait=True)
        # 1) 收集附件元数据（磁盘/DuckDB 清理用）
        atts = await session.execute(select(Attachment.file_path, Attachment.duckdb_table).where(...))
        # 2) DB 物理删除（顺序：日志→结果→任务→摘要→附件→消息），会话行软删 status='deleted'
        await session.execute(delete(TaskLog).where(TaskLog.task_id.in_(select(AnalysisTask.id).where(...))))
        await session.execute(delete(AnalysisResult).where(AnalysisResult.conversation_id == conv.id))
        await session.execute(delete(AnalysisTask).where(AnalysisTask.conversation_id == conv.id))
        await session.execute(delete(ContextSummary).where(ContextSummary.conversation_id == conv.id))
        await session.execute(delete(Attachment).where(Attachment.conversation_id == conv.id))
        await session.execute(delete(Message).where(Message.conversation_id == conv.id))
        conv.status = "deleted"; conv.updated_at = now()
    await session.commit()                                    # 每会话一个事务（由 get_session begin 包裹）
    # 3) 磁盘清理（提交后执行；失败仅 error 日志不回滚——DATA §7.1）
    for conv in convs:
        for d in ("uploads", "exports", "workspace"):
            shutil.rmtree(DATA_DIR / d / str(conv.user_id) / str(conv.id), ignore_errors=True)
    # 4) DuckDB 附件表 DROP
    async with duck.write_txn():
        for _, table in atts:
            if table: await to_thread(duck._conn.execute, f'DROP TABLE IF EXISTS "{table}"')
```

---

## 20. app/services/message_service.py — 消息业务

【关联】MSG-1、MSG-2

#### allocate_seq_no(session, conversation_id) -> int

- 思路：MSG-2。锁定读防并发重号；唯一索引兜底 + 一次重试。

```python
async def allocate_seq_no(session, cid) -> int:
    for attempt in range(2):
        try:
            cur = (await session.execute(
                text("SELECT next_seq_no FROM conversations WHERE id=:cid FOR UPDATE"),
                {"cid": cid})).scalar_one()
            await session.execute(text("UPDATE conversations SET next_seq_no=:n WHERE id=:cid"),
                                  {"n": cur + 1, "cid": cid})
            await session.flush(); return cur + 1
        except IntegrityError:                                # uk_conv_seq 冲突（理论罕见）
            await session.rollback(); continue
    raise BizError(50000, "消息序号分配失败")
```

#### append_message(session, conversation_id, role, message_type, content, tool_name=None, tool_status=None, task_id=None, attachment_ids=None) -> Message

- 思路：消息落库统一出口。user 消息同时回填 attachment.message_id + 刷新会话 last_message_at。

```python
async def append_message(...):
    seq = await allocate_seq_no(session, conversation_id)
    msg = Message(conversation_id=..., role=..., message_type=..., content=..., seq_no=seq, ...)
    session.add(msg); await session.flush()
    if attachment_ids:                                        # 附件挂到这条 user 消息
        await session.execute(update(Attachment).where(Attachment.id.in_(attachment_ids))
                              .values(message_id=msg.id))
    await session.execute(update(Conversation).where(Conversation.id == conversation_id)
                          .values(last_message_at=now()))
    return msg
```

#### list_messages(conversation_id) -> list[Message]

```python
async def list_messages(cid):
    return await session.execute(select(Message).where(Message.conversation_id == cid)
                                  .order_by(Message.seq_no.asc()))
```

---

## 21. app/services/attachment_service.py — 附件业务

【关联】ATT-1~8

#### save_upload(user, conversation_id, file) -> Attachment

- 思路：ATT-1。扩展名+mimetype 双校验、10MB 上限、secure_filename、落盘、建行、fire-and-forget 触发解析。

```python
async def save_upload(user, cid, file):
    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in {"csv","xlsx","txt","md"} or file.content_type not in ALLOWED_MIME[ext]:
        raise BizError(40002, "仅支持 csv/xlsx/txt/md")                       # 双校验
    size = await file.seek(0, 2) and await file.tell()                        # 流式取大小（或 Content-Length）
    if size > 10 * 1024 * 1024: raise BizError(40002, "文件超过 10MB 上限")
    name = secure_filename(file.filename)
    dest = DATA_DIR / "uploads" / str(user.id) / str(cid) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists(): name = f"{dest.stem}_{token_hex(3)}{dest.suffix}"; dest = dest.with_name(name)  # 冲突加后缀
    async with aiofiles.open(dest, "wb") as f: await f.write(await file.read())
    att = Attachment(conversation_id=cid, file_name=name, file_path=f"{user.id}/{cid}/{name}",
                     file_type=ext, file_size=size, parse_status="pending")
    session.add(att); await session.flush()
    spawn(parse_attachment(att.id))                           # ATT-2 异步解析，立即返回
    return att
```

#### parse_attachment(attachment_id)

- 思路：ATT-2~4 主链路。parsing →（结构化：导入 DuckDB / 文本：提取缓存）→ ready；任何异常 failed。

```python
async def parse_attachment(att_id):
    att = await get(att_id); att.parse_status = "parsing"; await commit()
    try:
        src = DATA_DIR / "uploads" / att.file_path
        if att.file_type in ("csv", "xlsx"):
            rows, columns, skipped = await to_thread(read_sheet, src, att.file_type)   # pandas，编码 utf-8→gbk，脏行跳过计数
            table = f"attachment_data_{att.id}"
            await import_to_duckdb(table, columns, rows)                               # ↓
            att.duckdb_table = table
        else:                                                                          # txt / md
            text = await to_thread(read_text_lenient, src)                             # 编码探测读取
            cache = DATA_DIR / "workspace" / uid / cid / f"attachment_text_{att.id}.txt"
            cache.write_text(text, encoding="utf-8")                                   # 供 text_search
        att.parse_status = "ready"
    except Exception as e:
        att.parse_status, att.error_message = "failed", str(e)[:1000]
    finally:
        await commit()
        await MANAGER.broadcast(att.conversation_id, {"type":"attachment_status",
            "attachment_id": att.id, "parse_status": att.parse_status})                # 协议扩展位
```

#### import_to_duckdb(table, columns, rows)

- 思路：ATT-3。写锁内建表分批插入；类型推断失败整列降 VARCHAR；附 `__row_no`。

```python
async def import_to_duckdb(table, columns, rows):
    col_defs = [f'"{normalize_column_name(c, i, used)}" {infer_type(rows, i)}' for i, c in enumerate(columns)]
    col_defs.append('"__row_no" BIGINT')
    async with duck.write_txn():
        await to_thread(conn.execute, f'CREATE SCHEMA IF NOT EXISTS attachments')
        await to_thread(conn.execute, f'CREATE TABLE attachments."{table}" ({", ".join(col_defs)})')
        await to_thread(batch_insert, conn, f'attachments."{table}"', rows)   # executemany 5000/批，带行号
```

#### get_owned(user, attachment_id) / get_ready_attachments(cid, uid, ids) / delete_attachment(att) / get_attachment_file(att) / recover_stuck_attachments()

```python
async def get_owned(user, att_id):
    att = await session.get(Attachment, att_id)
    conv = await session.get(Conversation, att.conversation_id)
    if not att or conv.status == "deleted": raise BizError(40401, "附件不存在")
    if conv.user_id != user.id: raise BizError(40301, "无权访问该附件")
    return att

async def get_ready_attachments(cid, uid, ids):
    # 返回 None 表示存在不合规附件（不属于本会话 / parse_status != ready）
    atts = 查询 WHERE id IN ids AND conversation_id=cid
    if len(atts) != len(ids) or any(a.parse_status != "ready" for a in atts): return None
    return atts

async def delete_attachment(att):                    # ATT-6 级联
    await session.delete(att); await commit()        # DB 行
    (DATA_DIR/"uploads"/att.file_path).unlink(missing_ok=True)                     # 源文件
    (workspace/…/f"attachment_text_{att.id}.txt").unlink(missing_ok=True)          # 检索缓存
    if att.duckdb_table:
        async with duck.write_txn():
            await to_thread(conn.execute, f'DROP TABLE IF EXISTS attachments."{att.duckdb_table}"')

async def recover_stuck_attachments():               # ATT-8 启动恢复
    await session.execute(text("""UPDATE attachments SET parse_status='failed',
        error_message='服务重启导致解析中断' WHERE parse_status IN ('pending','parsing')"""))
    await commit()
```

---

## 22. app/services/task_service.py — 任务业务

【关联】TASK-1~7

#### start_task(user, cid, text, attachment_ids)

- 思路：TASK-1。建任务 → 落 user 消息 → push message_start/queued → spawn run_task。**运行中任务表**（task_id → asyncio.Task）供取消。

```python
RUNNING: dict[int, asyncio.Task] = {}

async def start_task(user, cid, text, attachment_ids):
    task = AnalysisTask(conversation_id=cid, user_id=user.id, input_text=text,
                        attachment_ids=",".join(map(str, attachment_ids)) if attachment_ids else None,
                        task_status="queued", trace_id=TraceCtx.start())
    session.add(task); await flush()
    msg = await message_service.append_message(session, cid, "user", "text", text,
                                               task_id=task.id, attachment_ids=attachment_ids)
    await commit()
    await MANAGER.broadcast(cid, {"type":"message_start","task_id":task.id,"conversation_id":cid,"message_id":msg.id})
    await MANAGER.broadcast(cid, {"type":"task_status","task_id":task.id,"task_status":"queued","current_step":None})
    RUNNING[task.id] = spawn(run_task(task.id))
```

#### run_task(task_id)

- 思路：TASK-1 状态机 + TASK-4 超时 + TASK-6 日志。`asyncio.wait_for` 包整体；每步推送 + 落 task_logs。

```python
async def run_task(task_id):
    task = await get(task_id); TraceCtx.bind_task(task_id)
    try:
        task.task_status, task.started_at = "running", now(); await commit()
        await push_status(task, "running", "planning")
        await log(task_id, "info", "status", "queued → running")
        result = await asyncio.wait_for(execute_analysis(task), timeout=get_config().task_timeout_seconds)
        # ↑ analysis.graph 入口：返回 AnalysisResultModel（内部已推完所有过程事件并落库结果 RES-1）
        task.task_status, task.finished_at = "success", now(); await commit()
        await push_status(task, "success", None)
    except asyncio.TimeoutError:
        RUNNING[task_id].cancel()                                       # 掐内部协程
        await finish_failed(task, 50003, "任务执行超时")
    except asyncio.CancelledError:
        task.task_status, task.finished_at = "cancelled", now(); await commit()        # TASK-3
        await push_status(task, "cancelled", None); await log(task_id, "info", "status", "task cancelled")
        RUNNING.pop(task_id, None); raise
    except BizError as e:                                               # 如结构化输出不合规（AGENT-7）
        await finish_failed(task, e.code, e.message)
    except Exception as e:
        await finish_failed(task, 50000, f"任务执行失败：{e}")
    finally:
        RUNNING.pop(task_id, None)
        await MANAGER.broadcast(cid, {"type":"done","task_id":task_id,"finished_at": iso(now())})

async def finish_failed(task, code, msg):
    task.task_status, task.finished_at, task.error_message = "failed", now(), msg
    await commit()
    await MANAGER.broadcast(cid, {"type":"error","task_id":task.id,"error_code":code,"error_message":msg})
    await push_status(task, "failed", None)
    await log(task.id, "error", "status", f"task failed: {msg}")
```

#### cancel_task(user, cid, task_id) / cancel_if_active(cid, wait=False)

```python
async def cancel_task(user, cid, task_id):            # WS cancel 上行
    task = await get_owned(user, task_id)             # 归属校验
    aio_task = RUNNING.get(task_id)
    if task.task_status in ("queued","running") and aio_task:
        aio_task.cancel()                              # CancelledError 在 await 点中断执行链
    # 已终态的任务忽略（幂等）

async def cancel_if_active(cid, wait):                # 会话删除前调用（CONV-4 步骤 0）
    for tid, t in list(RUNNING.items()):
        if t属于cid: t.cancel()
    if wait: await asyncio.sleep(min(5, …))           # 等终态（简化：固定小睡后继续）
```

#### has_active_task(cid) -> bool / count_active_global() -> int / recover_zombie_tasks() / get_owned(user, task_id) / get_logs(task_id) / log(task_id, level, log_type, content)

```python
async def has_active_task(cid):
    return exists(AnalysisTask WHERE conversation_id=cid AND task_status IN ('queued','running'))

async def count_active_global():
    return count(AnalysisTask WHERE task_status IN ('queued','running'))       # TASK-2：≥5 → 42901

async def recover_zombie_tasks():                    # TASK-5 启动恢复
    await session.execute(text("""UPDATE analysis_tasks SET task_status='failed',
        error_message='服务重启导致任务中断', finished_at=NOW(3)
        WHERE task_status IN ('queued','running')""")); await commit()

async def log(task_id, level, log_type, content):    # TASK-6：内容截 2000 字
    session.add(TaskLog(task_id=task_id, log_level=level, log_type=log_type,
                        log_content=str(content)[:2000])); await commit()
```


---

## 23. app/services/result_service.py — 结果业务

【关联】RES-1、RES-2、RES-4

#### save_result(session, task, result: AnalysisResultModel) -> AnalysisResult

- 思路：RES-1。六段落库（JSON 字段序列化）+ 同步渲染 result_markdown 存 MEDIUMTEXT。

```python
async def save_result(session, task, result):
    row = AnalysisResult(task_id=task.id, conversation_id=task.conversation_id,
        problem_definition=result.problem_definition,
        key_metrics_json=[m.model_dump() for m in result.key_metrics],        # JSON 数组
        evidence_list_json=[e.model_dump() for e in result.evidence_list],
        conclusion_text=result.conclusion_text,
        missing_data_text=result.missing_data_text,
        next_action_text="\n".join(f"{i+1}. {a}" for i, a in enumerate(result.next_actions)),
        result_markdown=render_markdown(result, task))                        # ↓ 渲染复用
    session.add(row); await flush()
    await message_service.append_message(session, task.conversation_id, "assistant",
                                         "result", f"result:{row.id}", task_id=task.id)  # result 卡片消息
    await MANAGER.broadcast(task.conversation_id, {"type":"result_ready","task_id":task.id,"result_id":row.id})
    return row
```

#### render_markdown(result, task) -> str

- 思路：RES-1/4 共用渲染。按 DATA §6.3 模板（六段 + 两个表格）。

```python
def render_markdown(r, task):
    # 标题 + 元信息；关键指标表 / 证据表逐行拼 Markdown 表格；结论/待补充/建议按序输出
    # 建议列表：next_actions ≥2 条编号输出（AGENT-7 已保证）
    return MARKDOWN_TEMPLATE.format(...)
```

#### get_by_task(user, task_id) -> AnalysisResult

```python
async def get_by_task(user, task_id):
    # 先校验任务归属（task.user_id != user.id → 40301）
    row = session.scalar(select(AnalysisResult).where(task_id=task_id))
    if not row: raise BizError(40401, "任务未产生结果")
    return row
```

#### ensure_export_file(user, task_id) -> Path

- 思路：RES-4。幂等导出：已有且文件在 → 直接返回；否则**补渲染落盘**（不经过 Agent）。

```python
async def ensure_export_file(user, task_id):
    row = await get_by_task(user, task_id)
    dest = DATA_DIR / "exports" / str(user.id) / str(row.conversation_id) / f"result_{task_id}.md"
    if not (row.result_file_path and dest.exists()):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(row.result_markdown, encoding="utf-8")            # 复用落库时渲染的 md
        row.result_file_path = f"{user.id}/{row.conversation_id}/result_{task_id}.md"
        await commit()
    return dest
```

---

## 24. app/services/summary_service.py — 上下文摘要

【关联】CTX-1、CTX-2

#### check_compaction_needed(conversation_id) -> bool

- 思路：CTX-1。任务结束时调用：轮数（user 消息计数）> context_rounds 或拼装上下文估算 token（字符数/3）> context_token_budget。

```python
async def check_compaction_needed(cid) -> bool:
    rounds = count(Message WHERE conversation_id=cid AND role='user')
    if rounds > get_config().context_rounds: return True
    est_tokens = len(build_context(cid)) // 3                           # 复用 analysis.context 拼装
    return est_tokens > get_config().context_token_budget
```

#### summarize_range(conversation_id)

- 思路：CTX-2。取未被摘要覆盖的最早连续区间（≤10 轮）→ LLM 压缩 → 写 context_summaries。失败降级截断 + task_logs warn（PRD F8-R5）。

```python
async def summarize_range(cid):
    covered = SELECT start_seq_no, end_seq_no FROM context_summaries WHERE cid      # 已覆盖区间
    first_uncovered = 最小 seq_no 的未被覆盖消息
    batch = 取 [first_uncovered, first_uncovered+20) 内的 ≤10 轮消息（role in user/assistant，截 content ≤2000 字/条）
    prompt = SUMMARY_PROMPT.format(messages=batch)
    try:
        text = await llm_gateway.complete(prompt)                       # 无工具、低温调用
        session.add(ContextSummary(conversation_id=cid, start_seq_no=batch[0].seq_no,
                                   end_seq_no=batch[-1].seq_no, summary_text=text)); await commit()
        await log(task_id, "info", "summary", f"已压缩区间 [{start},{end}]")
    except Exception as e:
        # 降级：不写摘要，后续拼装时直接截断最旧消息（get_effective_context 内处理）
        await log(task_id, "warn", "summary", f"摘要生成失败，降级截断：{e}")
```

#### get_effective_context(conversation_id) -> list[Message]

- 思路：拼装视角的"有效消息"= 未被任何摘要覆盖的消息（按 seq_no 升序）；给 analysis.context 用。

---

## 25. app/services/llm_gateway.py — LLM 网关

【关联】AGENT-8

#### class LLMGateway

- 思路：配置驱动的惰性 client 缓存；reload 失效重建；重试 2 次。

```python
class LLMGateway:
    _client_cache: tuple[dict, AsyncClient] | None = None      # (配置指纹, client)

    def get_client(self) -> AsyncClient:
        cfg = get_config()
        fp = (cfg.llm_base_url, cfg.llm_api_key_ref, cfg.llm_model)
        if self._client_cache and self._client_cache[0] == fp:
            return self._client_cache[1]                        # 配置未变，复用
        client = AsyncOpenAI(base_url=cfg.llm_base_url,
                             api_key=os.environ[cfg.llm_api_key_ref])   # key 走环境变量引用
        self._client_cache = (fp, client); return client

    def invalidate(self): self._client_cache = None             # reload 后调用（CFG-2 联动）

    async def chat(self, messages, tools=None, stream=True, **kw):
        # 统一重试：超时/5xx/限流 → 退避 1s、4s 重试 2 次；每次重试记 task_logs warn
        for attempt, backoff in enumerate((0, 1, 4), 1):
            if backoff: await asyncio.sleep(backoff)
            try:
                return await self.get_client().chat.completions.create(
                    model=get_config().llm_model, messages=messages,
                    tools=tools, temperature=get_config().llm_temperature, stream=stream, **kw)
            except (APITimeoutError, APIStatusError) as e:
                if attempt == 3: raise BizError(50001, f"LLM 调用失败：{e}")
                await task_service.log(current_task, "warn", "llm_call", f"第 {attempt} 次失败重试：{e}")

    async def structured_output(self, messages, schema: type[BaseModel]):
        # with_structured_output 语义：非流式一次调用 + JSON 解析为 Pydantic（output.py 用）
        ...
```

---

## 26. app/analysis/state.py — Agent 状态

【关联】AGENT-1（结构定义与 DATA §6.4 一致）

#### AnalysisState(TypedDict)

```python
class AnalysisState(TypedDict):
    messages: list[AnyMessage]                  # 含 SystemMessage / HumanMessage / AIMessage / ToolMessage
    task_id: int; conversation_id: int; user_id: int; trace_id: str
    attachment_schemas: list[dict]              # [{table, columns:[{name,type}], row_count}]
    text_attachments: list[dict]                # [{file_name, preview}]
    tool_rounds: int                            # 已执行轮次（上限 max_tool_rounds）
    final_result: AnalysisResultModel | None    # output_node 产出
```

---

## 27. app/analysis/graph.py — LangGraph 图与流式映射

【关联】AGENT-1、AGENT-9

#### build_graph() -> CompiledGraph

- 思路：三节点循环图（SPEC 4.6 图）。条件边：有 tool_calls 且未超轮次 → tool_node；否则 → output_node。

```python
def build_graph():
    g = StateGraph(AnalysisState)
    g.add_node("agent",  agent_node)
    g.add_node("tools",  tool_node)
    g.add_node("output", output_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", route_after_agent,
        {"tools": "tools", "output": "output"})
    g.add_edge("tools", "agent")                        # 工具结果回填后回到 agent
    g.add_edge("output", END)
    return g.compile()

def route_after_agent(state) -> str:
    last = state["messages"][-1]
    if last.tool_calls and state["tool_rounds"] < get_config().max_tool_rounds:
        return "tools"
    return "output"
```

#### agent_node(state) -> dict

- 思路：单步 LLM 调用（绑定 5 工具）；文本增量事件由外层 astream_events 捕获，这里只返回 messages 追加。

```python
async def agent_node(state):
    resp = await llm.chat(state["messages"], tools=ALL_TOOLS, stream=False)   # 流式在外层统一处理
    return {"messages": [resp_message]}                      # AIMessage（可能含 tool_calls）
```

#### tool_node(state) -> dict

- 思路：执行上一条 AIMessage 的全部 tool_calls，结果作为 ToolMessage 回填；轮次 +1；每步事件外层推送。

```python
async def tool_node(state):
    last = state["messages"][-1]; results = []
    for call in last.tool_calls:
        fn = TOOL_REGISTRY[call["name"]]
        try: output = await fn(state, **call["args"])
        except BizError as e: output = f"工具执行被拒：[{e.code}] {e.message}"   # 拒绝原因回传 Agent 供修正
        results.append(ToolMessage(tool_call_id=call["id"], content=output))
    return {"messages": results, "tool_rounds": state["tool_rounds"] + 1}
```

#### output_node(state) -> dict

- 思路：达到收敛（或超轮次强制收敛）→ 调 output.generate_structured_output；超轮次先注入收敛指令。

```python
async def output_node(state):
    if state["tool_rounds"] >= get_config().max_tool_rounds:
        state["messages"].append(SystemMessage("已达工具轮次上限，请基于已收集的证据直接输出最终结论，不再调用工具。"))
    result = await generate_structured_output(state)          # → output.py（AGENT-7）
    return {"final_result": result}
```

#### execute_analysis(task) -> AnalysisResultModel

- 思路：任务执行总入口（task_service.run_task 调用）。拼上下文 → astream_events 驱动 → 事件映射推送（AGENT-9）→ 结果落库。

```python
async def execute_analysis(task):
    state0 = await build_initial_state(task)                  # → context.py
    graph = build_graph()
    assistant_msg_id = None
    async for ev in graph.astream_events(state0, version="v2"):
        match ev["event"]:
            case "on_chat_model_stream" if is_text_chunk(ev):
                if not assistant_msg_id:                      # 首个文本块：分配 seq_no 落空行（SPEC 4.6 落库策略）
                    assistant_msg_id = (await message_service.append_message(
                        session, cid, "assistant", "text", "", task_id=task.id)).id
                buffer += ev_text(ev)
                await MANAGER.broadcast(cid, {"type":"message_delta","task_id":task.id,
                                              "message_id":assistant_msg_id,"delta_text":ev_text(ev)})
            case "on_tool_start":
                await push_tool(task, "tool_start", ev)       # tool_name + 输入摘要（截 200 字）
                await message_service.append_tool_message(..., "running")
            case "on_tool_end":
                await push_tool(task, "tool_finish", ev)      # 状态 + 结果摘要（截 500 字）
                await update_tool_message(..., ev 状态, 摘要)
        # 节点进入 → task_status.current_step：agent=planning/querying、output=summarizing
    if assistant_msg_id: await finalize_assistant_text(assistant_msg_id, buffer)   # 终态一次 UPDATE 全文
    result = final_state["final_result"]
    row = await result_service.save_result(session, task, result)                 # RES-1（含 result_ready 推送）
    await ensure_export_file(user, task.id)                                       # AGENT-6 产物兜底
    if await summary_service.check_compaction_needed(cid):                        # CTX-1
        await summary_service.summarize_range(cid)                                # CTX-2
    return result
```

---

## 28. app/analysis/context.py — 上下文拼装

【关联】AGENT-2

#### build_initial_state(task) -> AnalysisState

- 思路：五段拼装（SPEC 4.6）：system prompt → 会话摘要 → 近 N 轮 → 本轮输入+附件 → 数据源说明。

```python
async def build_initial_state(task):
    msgs = [SystemMessage(AGENT_SYSTEM_PROMPT)]                          # 角色+工具规范+六段契约+安全声明
    for s in summaries(cid): msgs.append(SystemMessage(f"[历史摘要] {s.summary_text}"))
    for m in summary_service.get_effective_context(cid)[-N*2:]:          # 近 N 轮原始消息
        msgs.append(to_lc_message(m))                                    # user→HumanMessage, assistant→AIMessage
    # 本轮输入：问题 + 附件清单
    struct_atts, text_atts = await load_ready_attachments(task)
    att_desc = "\n".join(f"- 结构化附件 {a.table}（{a.row_count} 行）：{a.columns}" for a in struct_atts)
    att_desc += "\n".join(f"- 文本附件 {t.file_name}：{t.preview}" for t in text_atts)
    msgs.append(HumanMessage(content=f"{task.input_text}\n\n[本轮附件]\n{att_desc}"))
    msgs.append(SystemMessage(SCENARIO_DATA_DICTIONARY))                 # 4 场景 schema 表清单（静态）
    return AnalysisState(messages=msgs, task_id=task.id, ..., attachment_schemas=..., tool_rounds=0)
```

#### SCENARIO_DATA_DICTIONARY: str

- 思路：静态注册的 4 场景数据字典（每表一行：schema.表(关键列)），从 seeds 元数据生成，供 LLM 写 SQL。

---

## 29. app/analysis/output.py — 六段结构化输出

【关联】AGENT-7

#### generate_structured_output(state) -> AnalysisResultModel

- 思路：结构化生成 + 强校验 + 一次重试。校验规则：metrics≥1、evidence≥1、confidence 枚举、next_actions≥2。

```python
async def generate_structured_output(state):
    for attempt in (1, 2):
        try:
            result = await llm.structured_output(state["messages"] + [OUTPUT_INSTRUCTION], AnalysisResultModel)
            validate_result(result)                       # 不合规抛 ValueError
            await log(task_id, "info", "llm_call", "结构化输出校验通过")
            return result
        except (ValidationError, ValueError) as e:
            if attempt == 2: raise BizError(50000, f"结构化输出不合规：{e}")
            state["messages"].append(SystemMessage(       # 附错误说明再试一次
                f"上次输出不合规：{e}。请严格按 schema 重新输出。"))
```

#### validate_result(result)

```python
def validate_result(r):
    if len(r.key_metrics) < 1: raise ValueError("key_metrics 至少 1 条")
    if len(r.evidence_list) < 1: raise ValueError("evidence_list 至少 1 条")
    if len(r.next_actions) < 2: raise ValueError("next_actions 至少 2 条")
    # confidence 枚举已由 Pydantic Literal 保证
```

---

## 30. app/analysis/tools/ — 五个工具

【关联】AGENT-3、AGENT-4、AGENT-5、AGENT-6。全部注册进 `TOOL_REGISTRY` 并生成 OpenAI tool schema（名称/描述/参数 JSON Schema，描述里写清用法与限制，帮助 LLM 正确调用）。

#### tools/sql_query.py — sql_query_tool(state, sql: str) -> str

```python
TOOL_DESC = "对 DuckDB 分析库执行只读查询（业务数据+附件导入表）。仅 SELECT/WITH/SHOW/DESCRIBE；返回列名+行数据。"

async def sql_query_tool(state, sql):
    validated = validate_sql(sql)                          # core.security → AGENT-3 闸门
    if isinstance(validated, SqlRejected):
        return f"[50002] {validated.reason}。请修改后重试。"          # 拒绝原因回传（不抛异常）
    final_sql = wrap_limit(validated, get_config().sql_row_limit)
    t0 = now()
    qr = await duck.execute_query(final_sql, get_config().sql_timeout_seconds)
    elapsed = (now() - t0).ms
    await log(task_id, "info" if not qr.error else "warn", "tool_exec",
              f"sql_query {elapsed}ms rows={len(qr.rows)} sql={sql[:200]}")
    if qr.error: return f"执行失败：{qr.error}"                       # 超时/报错同样回传 Agent
    # 紧凑文本序列化：列名行 + 每行数据（截 1000 行标记 truncated）
    return format_rows_compact(qr)
```

#### tools/file_tools.py — file_read_tool / file_write_tool

```python
async def file_read_tool(state, path: str):
    # 守卫：safe_path(roots=("uploads","workspace"))，None → "[50002] 路径越权"
    data = target.read_bytes()[:1MB]                       # 超出截断并注明
    return data.decode("utf-8", errors="replace") + (截断标记)

async def file_write_tool(state, path: str, content: str):
    # 守卫：safe_path(roots=("workspace",)) 仅工作目录；会话用量检查（遍历 ≤50MB）
    target.parent.mkdir(...); target.write_text(content, encoding="utf-8")
    return f"已写入 {path}（{len(content)} 字符）"
```

#### tools/text_search.py — text_search_tool(state, keyword: str)

```python
async def text_search_tool(state, keyword):
    files = [workspace/…/attachment_text_{id}.txt（就绪 txt/md 附件）] + workspace 内 .txt/.md（深度≤2，单文件≤5MB）
    hits = []
    for f in files:
        for line_no, line in enumerate(f 逐行, 1):
            if keyword.lower() in line.lower():
                hits.append({"file": f.name, "line_no": line_no,
                             "snippet": line[max(0,pos-120):pos+120].strip()})   # ±120 字片段
            if 本文件命中 ≥50: break
    return format_hits(hits) if hits else "未检索到匹配内容"
```

#### tools/gen_result.py — generate_result_file_tool(state)

- 思路：AGENT-6。输出节点产物已在 state.final_result；此工具把它渲染落盘（正常链路 result_service 已做，工具作为 Agent 显式确认出口，幂等）。

```python
async def generate_result_file_tool(state):
    r = state.get("final_result")
    if not r: return "[40001] 结果尚未生成"
    dest = exports/{uid}/{cid}/result_{task_id}.md
    dest.write_text(render_markdown(r, task), encoding="utf-8")
    await result_service.mark_exported(task_id, dest)      # 回填 result_file_path
    return f"结果文件已生成：{dest.name}"
```

---

## 31. app/seeds/init_analytics.py — DuckDB 建库灌数

【关联】F10（4 场景 + 脏数据，规模见 DATA §8.1）

#### main(db_path)

- 思路：幂等入口（存在即 DROP 重建），按 schema 顺序建表灌数。

```python
def main(db_path):
    conn = duckdb.connect(db_path)
    for fn in (seed_s1_catalog, seed_s2_refund, seed_s3_behavior, seed_s4_inventory):
        fn(conn)                                            # 每场景：DROP SCHEMA CASCADE → CREATE → 灌数
    conn.close()

def seed_s2_refund(conn):
    conn.execute("CREATE SCHEMA s2_refund")
    conn.execute(DDL_S2)                                    # DATA §5.2 四表 DDL
    rows = gen_refund_rows()                                # 90 天、5 万订单、3000 退款
    # 关键注入：护肤品类(SKU-A1023 等)退款异常聚集 —— 让示例问题有明确归因答案
    # 脏数据：~3% 行 NULL/超范围/重复（演示容错）
    conn.executemany("INSERT INTO s2_refund.orders VALUES (?,...)", rows)
```

#### 各 seed 的"归因剧本"注释

- 思路：每个场景 seed 函数头部写死该场景的**预期归因答案**（如"S2：SKU-A1023 贡献 6.1pp 退款率上升"），演示与提示词调优的对照标准（M3 验收用）。


---

## 32. auth-server/ — 轻量 OAuth2 认证服务

【关联】AUTH-1~3。独立 FastAPI 进程 :8001，三个端点 + 登录页。表结构见 DATA §4。

#### app/main.py — GET/POST /authorize

- 思路：GET 渲染账密页（Jinja2）；POST 校验账密 → 发一次性 code → 302 回 redirect_uri。参数四校验任一不符返回 400 页。

```python
async def authorize(request, client_id, redirect_uri, response_type, state):
    if request.method == "GET":
        client = await get_client(client_id)
        if not client or client.redirect_uri != redirect_uri or response_type != "code":
            return HTMLResponse(error_page(400), status_code=400)     # 校验失败：错误页（不回跳）
        return templates.TemplateResponse("login.html", {"client_name": client.client_name, "state": state})
    # POST：账密校验
    user = await verify_credentials(form.username, form.password)     # bcrypt 校验（auth_users）
    if not user:
        return templates.TemplateResponse("login.html", {"error": "账号或密码错误"})
    code = secrets.token_urlsafe(32)
    session.add(AuthCode(code=code, client_id=client_id, user_id=user.id,
                         redirect_uri=redirect_uri, expires_at=now()+300s))
    await commit()
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}")
```

#### app/main.py — POST /token

- 思路：AUTH-2。授权码换 JWT。**原子消费**（同 WS 令牌套路）。

```python
async def token(grant_type, code, client_id, client_secret):
    if grant_type != "authorization_code": return oauth_error("unsupported_grant_type")
    if not await verify_client(client_id, client_secret): return oauth_error("invalid_client")
    r = await session.execute(text("""
        UPDATE auth_codes SET consumed_at = NOW(3)
        WHERE code=:c AND client_id=:cid AND consumed_at IS NULL AND expires_at > NOW(3)"""), ...)
    if r.rowcount != 1: return oauth_error("invalid_grant")           # 已用/过期/不存在
    user = 通过 code 行取 auth_users
    jwt = issue_jwt(sub=str(user.id), username=..., display_name=..., role=user.role, exp=now()+8h)
    return {"access_token": jwt, "token_type": "Bearer", "expires_in": 28800}
```

#### app/main.py — GET /userinfo

```python
async def userinfo(Authorization: str):
    payload = verify_jwt(Authorization.removeprefix("Bearer "))       # 验签+过期检查
    if not payload: return oauth_error(401, "invalid_token")
    return {"sub": payload["sub"], "username": payload["username"],
            "display_name": payload["display_name"], "role": payload["role"]}
```

#### app/jwt_utils.py — issue_jwt() / verify_jwt()

- 思路：HS256，密钥来自环境变量 `AUTH_JWT_SECRET`（两服务共享或仅 auth-server 持有——backend 只调 /userinfo 不自验，故仅 auth-server 需要）。

#### app/seed.py — seed()

- 思路：建两演示账号 + 一个 client（client_id=ecogain-web，secret 走环境变量）。

---

## 33. 前端关键文件（中等粒度）

【关联】FE-1~10。完整路由/布局见 SPEC §5；此处列文件与方法级职责供核对。

| 文件 | 关键函数/方法 | 思路 |
| --- | --- | --- |
| src/api/client.ts | `request()`、拦截器 | axios 封装：withCredentials、code!=0 统一抛错、40101 跳登录 |
| src/api/chat.ts | `createChat/deleteChats/renameChat/listChats/listMessages/getWsToken` | 对应 API 文档 §4 |
| src/api/attachment.ts | `upload(onProgress)/remove/download` | upload 用 FormData + 进度回调（FE-7） |
| src/api/results.ts | `getTask/getResult/downloadResult` | 对应 API 文档 §6 |
| src/api/admin.ts | `reload/getTaskLogs` | 对应 API 文档 §7 |
| src/composables/useWebSocket.ts | `connect(cid)/send(msg)/close()/reconnect()` | 状态机 idle→connecting→open→reconnecting；4401 重取令牌、其他指数退避 1/2/4/8/30s；30s ping；onmessage 按 type 分发到各 store（FE-9） |
| src/stores/auth.ts | `login()/logout()/fetchMe()` | login 即 `location.href='/auth/login'`（FE-1） |
| src/stores/conversation.ts | `load/create/rename/remove/archive/switch` | 切换时断开旧 WS 连新（FE-3） |
| src/stores/chat.ts | `send()/applyDelta/applyTool/applyError` | send 乐观渲染 user 气泡；delta 累积；运行态锁输入切取消（FE-4/6） |
| src/stores/task.ts | `applyStatus/applyStep` | 五态徽标 + current_step 文案映射（FE-5） |
| src/stores/attachment.ts | `uploadAndTrack/remove/download/pollStatus` | 5s 轮询 parse_status 至终态，WS attachment_status 提前止轮（FE-7） |
| src/stores/result.ts | `load(taskId)/copy/export` | 六段渲染数据 + clipboard 复制 result_markdown（FE-8） |
| src/views/Login.vue | — | 入口页：授权登录按钮（FE-1） |
| src/views/Callback.vue | — | loading / error+重试（FE-2） |
| src/views/Workbench.vue | — | 三栏布局装配 + <1366px 结果区抽屉（FE-3~8） |
| src/views/Admin.vue | — | 配置分组表单 + reload + 日志查看器（FE-10） |
| src/components/ResultPanel.vue | — | 六段渲染：指标/证据表格（confidence 色点）+ marked/DOMPurify 正文 |

---

## 34. 功能点 → 方法 索引表（核对清单）

> 核对完一项在行首打勾。格式：`功能点 → 文件.方法`。

### 认证（AUTH）
- [ ] AUTH-1 → auth-server/main.py `authorize(GET)`
- [ ] AUTH-2 → auth-server/main.py `token()` + `issue_jwt()`
- [ ] AUTH-3 → auth-server/main.py `userinfo()` + `verify_jwt()`
- [ ] AUTH-4 → api/auth.py `route_login()`
- [ ] AUTH-5 → api/auth.py `route_callback()` + `exchange_code()` + `fetch_userinfo()` + models/user.py `upsert_from_oauth()`
- [ ] AUTH-6 → api/deps.py `get_current_user()` + main.py `AuthSessionMiddleware`
- [ ] AUTH-7 → api/auth.py `route_logout()`

### 会话与消息（CONV/MSG）
- [ ] CONV-1 → api/chat.py `route_create()` + services/conversation_service.py `create()`
- [ ] CONV-2 → `list_by_user()`
- [ ] CONV-3 → api/chat.py `route_update()`
- [ ] CONV-4 → `delete_many()`（级联：任务取消→DB 删除→磁盘→DuckDB DROP）
- [ ] CONV-5 → `route_update()` 的 status 扩展（⚠ 需同步 API 文档）
- [ ] MSG-1 → api/chat.py `route_history()` + services/message_service.py `list_messages()`
- [ ] MSG-2 → `allocate_seq_no()`
- [ ] MSG-3 → ws/router.py `handle_user_message()` 的 40901 分支

### 附件（ATT）
- [ ] ATT-1 → api/attachment.py `route_upload()` + `save_upload()`
- [ ] ATT-2 → `parse_attachment()`
- [ ] ATT-3 → `import_to_duckdb()` + core/security.py `normalize_column_name()`
- [ ] ATT-4 → `parse_attachment()` 文本分支
- [ ] ATT-5 → `attachment_status` 广播 + stores/attachment.ts `pollStatus()`
- [ ] ATT-6 → `delete_attachment()` + api `route_delete()`
- [ ] ATT-7 → api `route_download()` + `safe_path()`
- [ ] ATT-8 → `recover_stuck_attachments()`

### 实时通道（WS）
- [ ] WS-1 → ws/router.py `issue_token()` + api/chat.py `route_ws_token()`
- [ ] WS-2 → `consume_token()`（原子 UPDATE）
- [ ] WS-3 → ws/manager.py `ConnectionManager` 全部方法
- [ ] WS-4 → `heartbeat_monitor()` + `touch()`
- [ ] WS-5 → `broadcast()` 的 8 类消息调用点（graph.py / task_service.py / attachment_service.py）
- [ ] WS-6 → `websocket_endpoint()` 收发循环
- [ ] WS-7 → 前端 `useWebSocket.reconnect()` + REST 补齐（SPEC 5.2）

### 任务（TASK）
- [ ] TASK-1 → task_service.py `start_task()` + `run_task()`
- [ ] TASK-2 → `count_active_global()`（42901）
- [ ] TASK-3 → `cancel_task()` / `cancel_if_active()`
- [ ] TASK-4 → `run_task()` 的 wait_for 超时分支（50003）
- [ ] TASK-5 → `recover_zombie_tasks()`
- [ ] TASK-6 → `log()` 全路径埋点
- [ ] TASK-7 → api/results.py `route_get_task()`

### 分析引擎（AGENT）
- [ ] AGENT-1 → analysis/graph.py `build_graph()/agent_node()/tool_node()/output_node()`
- [ ] AGENT-2 → analysis/context.py `build_initial_state()`
- [ ] AGENT-3 → tools/sql_query.py + core/security.py `validate_sql()/wrap_limit()`
- [ ] AGENT-4 → tools/file_tools.py + `safe_path()`
- [ ] AGENT-5 → tools/text_search.py
- [ ] AGENT-6 → tools/gen_result.py + result_service.py `ensure_export_file()`
- [ ] AGENT-7 → analysis/output.py `generate_structured_output()/validate_result()`
- [ ] AGENT-8 → services/llm_gateway.py 全部
- [ ] AGENT-9 → analysis/graph.py `execute_analysis()` 事件映射

### 结果与摘要（RES/CTX）
- [ ] RES-1 → result_service.py `save_result()`
- [ ] RES-2 → `get_by_task()`
- [ ] RES-3 → 前端 stores/result.ts `copy()`
- [ ] RES-4 → `ensure_export_file()` + api `route_download()`
- [ ] CTX-1 → summary_service.py `check_compaction_needed()`
- [ ] CTX-2 → `summarize_range()` + `get_effective_context()`

### 配置与管理（CFG）
- [ ] CFG-1 → core/config.py `load_configs()` + main.py lifespan
- [ ] CFG-2 → `reload_config()` + api/admin.py `route_reload()`
- [ ] CFG-3 → `route_task_logs()`
- [ ] CFG-4 → system_configs 的 datasource 组维护（复用 reload 链路）
- [ ] CFG-5 → feature 组开关在 `route_upload()`/`route_download()` 的检查点
- [ ] CFG-6 → api/deps.py `require_admin()`

### 前端（FE）
- [ ] FE-1~2 → views/Login.vue / Callback.vue
- [ ] FE-3 → stores/conversation.ts + Workbench 左栏
- [ ] FE-4 → stores/chat.ts（流式渲染/工具块/历史回放）
- [ ] FE-6 → stores/chat.ts（send/运行态锁输入切取消）
- [ ] FE-5 → stores/task.ts + 实时任务区组件
- [ ] FE-7 → stores/attachment.ts + 附件侧栏组件
- [ ] FE-8 → stores/result.ts + components/ResultPanel.vue
- [ ] FE-9 → composables/useWebSocket.ts
- [ ] FE-10 → views/Admin.vue + stores/admin.ts

### 场景数据（F10）
- [ ] S1~S4 → seeds/init_analytics.py 四个 seed 函数（含归因剧本注释）

## 35. 遗留待办（实现时需回写上游文档）

1. **CONV-5 归档接口**：本蓝图将归档实现为 `POST /api/chat/update` 的可选 `status` 字段，需同步补充到 API 文档 §4.3；
2. **attachment 上限**：`route_upload` 的 10MB 校验读的是流式大小，若前端传了 Content-Length 可优先用之，注意代理场景可能缺失；
3. **DuckDB 超时语义**：`execute_query` 的 wait_for 超时无法真正终止底层线程（SELECT 只读无副作用，POC 接受）；如需强杀可演进为连接级 interrupt；
4. **summary 失败降级**：`get_effective_context` 需实现"无摘要时截断最旧消息"分支（CTX-2 降级路径），首次实现易遗漏。





