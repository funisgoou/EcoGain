# 经营归因分析系统 数据设计文档（DATA）

## 1. 文档信息

| 项 | 内容 |
| --- | --- |
| 文档名称 | 数据设计文档（对象数据结构 + 表结构设计） |
| 文档版本 | v1.0 |
| 创建日期 | 2026-08-16 |
| 上游文档 | `docs/PRD-经营归因分析系统.md`（v1.1，附录 B 为本表设计的基线） |
| 功能 companion | `docs/SPEC-功能规格说明.md` |
| 接口 companion | `docs/API-接口设计文档.md`（接口 DTO 与 WS 消息对象的唯一契约源） |

## 2. 存储总览

系统共四层存储，职责与边界如下：

| 存储层 | 载体 | 职责 | 不承载 |
| --- | --- | --- | --- |
| 系统库 | MySQL 8 `ecogain` | 10 张 OLTP 表：用户、会话、消息、附件、任务、结果、摘要、WS 令牌、配置、任务日志 | 分析数据 |
| 认证库 | MySQL 8 `ecogain_auth` | OAuth2 授权码服务：凭据、客户端注册、授权码 | 业务数据 |
| 分析库 | DuckDB `analytics/analytics.duckdb`（backend 进程内嵌入式） | 4 个场景 schema 的示例数据 + 附件导入动态表 | 高频小事务 |
| 文件存储 | 数据卷 `uploads/ exports/ workspace/` | 附件源文件、导出报告、中间产物与文本检索缓存 | — |

三层库的写入方约束：系统库与认证库走 SQLAlchemy 异步；分析库由 backend 独占进程内打开（单 Database 实例 + 全局写锁），Alembic 只管理系统库，分析库由 seeds 脚本建表灌数（见 SPEC 4.6 连接策略）。

## 3. MySQL 系统库（ecogain）

通用约定：`utf8mb4 / utf8mb4_0900_ai_ci`，InnoDB；主键 `id BIGINT UNSIGNED AUTO_INCREMENT`；时间 `DATETIME(3)`（存 UTC+8 本地时间，与应用层一致）；枚举一律 VARCHAR + CHECK 约束（MySQL 8.0.16+ 强制）；所有表不使用外键约束（级联删除由应用层事务控制，见 SPEC 4.2），但保留索引。

### 3.1 users — 平台用户

```sql
CREATE TABLE users (
  id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  external_user_id VARCHAR(64)  NOT NULL COMMENT '认证中心用户唯一标识（auth_users.id）',
  username         VARCHAR(64)  NOT NULL,
  display_name     VARCHAR(128) NOT NULL DEFAULT '',
  role             VARCHAR(16)  NOT NULL DEFAULT 'analyst' COMMENT 'analyst | admin',
  status           VARCHAR(16)  NOT NULL DEFAULT 'active'  COMMENT 'active | disabled',
  created_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_external_user_id (external_user_id),
  KEY idx_username (username),
  CONSTRAINT chk_users_role   CHECK (role   IN ('analyst','admin')),
  CONSTRAINT chk_users_status CHECK (status IN ('active','disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='平台用户（登录回调时 upsert）';
```

### 3.2 conversations — 会话

```sql
CREATE TABLE conversations (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id         BIGINT UNSIGNED NOT NULL,
  title           VARCHAR(200)    NOT NULL DEFAULT '新分析',
  status          VARCHAR(16)     NOT NULL DEFAULT 'active' COMMENT 'active | archived | deleted',
  next_seq_no     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '消息序号分配计数器（实现扩展，PRD 附录 B 之外补充）',
  last_message_at DATETIME(3)     NULL,
  created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY idx_user_status_last (user_id, status, last_message_at),
  CONSTRAINT chk_conv_status CHECK (status IN ('active','archived','deleted'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分析会话';
```

> `next_seq_no` 为 PRD 附录 B 之上的**实现扩展字段**：`SELECT … FOR UPDATE` 锁定读后 +1 分配 seq_no，配合 messages 唯一索引防重（SPEC 4.2）。

### 3.3 messages — 消息

```sql
CREATE TABLE messages (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  conversation_id BIGINT UNSIGNED NOT NULL,
  role            VARCHAR(16)     NOT NULL COMMENT 'user | assistant | tool',
  message_type    VARCHAR(16)     NOT NULL COMMENT 'text | tool_call | result',
  content         MEDIUMTEXT      NOT NULL COMMENT '正文；tool_call 存参数/结果摘要',
  tool_name       VARCHAR(64)     NULL,
  tool_status     VARCHAR(16)     NULL COMMENT 'running | success | failed（仅 tool_call 消息）',
  task_id         BIGINT UNSIGNED NULL COMMENT '产生本条消息的任务（assistant/tool 消息回溯）',
  seq_no          INT UNSIGNED    NOT NULL COMMENT '会话内单调递增',
  created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_conv_seq (conversation_id, seq_no),
  KEY idx_conv_created (conversation_id, created_at),
  KEY idx_task (task_id),
  CONSTRAINT chk_msg_role   CHECK (role       IN ('user','assistant','tool')),
  CONSTRAINT chk_msg_type   CHECK (message_type IN ('text','tool_call','result')),
  CONSTRAINT chk_msg_tstat  CHECK (tool_status IS NULL OR tool_status IN ('running','success','failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话消息';
```

> `task_id` 为实现扩展字段：支撑「历史回放时按任务分组」与「删除任务级联定位」。

### 3.4 attachments — 附件

```sql
CREATE TABLE attachments (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  conversation_id BIGINT UNSIGNED NOT NULL,
  message_id      BIGINT UNSIGNED NULL COMMENT '关联的用户消息（发送时回填）',
  file_name       VARCHAR(255)    NOT NULL COMMENT '规范化后文件名',
  file_path       VARCHAR(512)    NOT NULL COMMENT '相对 uploads 根的路径',
  file_type       VARCHAR(16)     NOT NULL COMMENT 'csv | xlsx | txt | md',
  file_size       BIGINT UNSIGNED NOT NULL COMMENT '字节',
  parse_status    VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT 'pending | parsing | ready | failed',
  duckdb_table    VARCHAR(128)    NULL COMMENT 'csv/xlsx 导入 DuckDB 后的表名 attachment_data_{id}',
  error_message   VARCHAR(1024)   NULL COMMENT '解析失败原因',
  created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_conv (conversation_id),
  KEY idx_msg (message_id),
  CONSTRAINT chk_att_ftype CHECK (file_type IN ('csv','xlsx','txt','md')),
  CONSTRAINT chk_att_pstat CHECK (parse_status IN ('pending','parsing','ready','failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话附件';
```

> `duckdb_table`、`error_message` 为实现扩展字段：前者供 Agent 上下文拼装与删除时 DROP 表定位，后者供侧栏失败提示。

### 3.5 analysis_tasks — 分析任务

```sql
CREATE TABLE analysis_tasks (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  conversation_id BIGINT UNSIGNED NOT NULL,
  user_id         BIGINT UNSIGNED NOT NULL,
  input_text      TEXT            NOT NULL,
  attachment_ids  VARCHAR(1024)   NULL COMMENT '本轮引用的附件 id 逗号分隔（实现扩展）',
  task_status     VARCHAR(16)     NOT NULL DEFAULT 'queued' COMMENT 'queued | running | success | failed | cancelled',
  current_step    VARCHAR(64)     NULL COMMENT 'planning | querying | summarizing',
  trace_id        VARCHAR(32)     NULL COMMENT '链路追踪（实现扩展，日志关联）',
  started_at      DATETIME(3)     NULL,
  finished_at     DATETIME(3)     NULL,
  error_message   TEXT            NULL,
  created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_conv (conversation_id),
  KEY idx_status (task_status),
  KEY idx_trace (trace_id),
  CONSTRAINT chk_task_status CHECK (task_status IN ('queued','running','success','failed','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分析任务（一条用户消息一个任务）';
```

> 单会话单任务与全局 ≤5 并发由应用层保证（SPEC 4.5），`idx_status` 支撑并发计数查询。

### 3.6 analysis_results — 结构化结果

```sql
CREATE TABLE analysis_results (
  id                 BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  task_id            BIGINT UNSIGNED NOT NULL,
  conversation_id    BIGINT UNSIGNED NOT NULL,
  problem_definition TEXT         NOT NULL,
  key_metrics_json   JSON         NOT NULL COMMENT '数组，元素结构见 §6.3',
  evidence_list_json JSON         NOT NULL COMMENT '数组，元素结构见 §6.3',
  conclusion_text    TEXT         NOT NULL,
  missing_data_text  TEXT         NULL,
  next_action_text   TEXT         NOT NULL,
  result_markdown    MEDIUMTEXT   NOT NULL COMMENT '完整 Markdown 渲染（复制/展示用）',
  result_file_path   VARCHAR(512) NULL COMMENT 'exports 相对路径；未导出为 NULL',
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_task (task_id),
  KEY idx_conv (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='六段结构化分析结果（一任务一行）';
```

### 3.7 context_summaries — 上下文摘要

```sql
CREATE TABLE context_summaries (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  conversation_id BIGINT UNSIGNED NOT NULL,
  start_seq_no    INT UNSIGNED    NOT NULL COMMENT '覆盖消息区间起（含）',
  end_seq_no      INT UNSIGNED    NOT NULL COMMENT '覆盖消息区间止（含）',
  summary_text    TEXT            NOT NULL,
  created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_conv (conversation_id),
  KEY idx_conv_range (conversation_id, start_seq_no, end_seq_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='历史消息 LLM 摘要（区间互不重叠，由应用层保证）';
```

### 3.8 websocket_tokens — WS 一次性令牌

```sql
CREATE TABLE websocket_tokens (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id         BIGINT UNSIGNED NOT NULL,
  conversation_id BIGINT UNSIGNED NOT NULL,
  token           VARCHAR(128)    NOT NULL,
  expires_at      DATETIME(3)     NOT NULL COMMENT '签发后 60 秒',
  consumed_at     DATETIME(3)     NULL COMMENT '一次性消费标记（建连成功即写）',
  created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_token (token),
  KEY idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='WebSocket 建连一次性令牌';
```

> 清理任务：后台协程每小时删除 `expires_at < NOW(3) - 1h` 的行。

### 3.9 system_configs — 系统配置

```sql
CREATE TABLE system_configs (
  id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  config_key   VARCHAR(128) NOT NULL COMMENT '如 llm.model',
  config_value TEXT         NULL COMMENT '敏感项存 key 引用，不明文',
  config_group VARCHAR(32)  NOT NULL COMMENT 'llm | agent | datasource | feature',
  description  VARCHAR(255) NULL,
  updated_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_key (config_key),
  KEY idx_group (config_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统配置（热更新）';
```

### 3.10 task_logs — 任务日志

```sql
CREATE TABLE task_logs (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  task_id     BIGINT UNSIGNED NOT NULL,
  log_level   VARCHAR(16)    NOT NULL COMMENT 'info | warn | error',
  log_type    VARCHAR(32)    NOT NULL COMMENT 'llm_call | tool_exec | status | summary',
  log_content TEXT           NOT NULL COMMENT '≤2000 字，含结构化摘要',
  created_at  DATETIME(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_task_created (task_id, created_at),
  CONSTRAINT chk_log_level CHECK (log_level IN ('info','warn','error'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='任务运行日志';
```

### 3.11 Alembic 迁移基线

- `0001_initial`：上述 10 表 + 索引；
- `0002_seed_configs`：插入 §6.5 配置项清单默认值；
- 迁移在 compose 首次启动由 backend 容器 entrypoint 执行（`alembic upgrade head`），幂等。

## 4. MySQL 认证库（ecogain_auth）

### 4.1 auth_users — 认证中心凭据

```sql
CREATE TABLE auth_users (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  username       VARCHAR(64)  NOT NULL,
  password_hash  VARCHAR(100) NOT NULL COMMENT 'bcrypt(cost=12)',
  display_name   VARCHAR(128) NOT NULL DEFAULT '',
  role           VARCHAR(16)  NOT NULL DEFAULT 'analyst' COMMENT 'analyst | admin',
  status         VARCHAR(16)  NOT NULL DEFAULT 'active',
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_username (username),
  CONSTRAINT chk_au_role CHECK (role IN ('analyst','admin'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='认证中心用户';
```

seed：`analyst / EcoGain@2026`（role=analyst）、`admin / EcoGain@2026`（role=admin）。

### 4.2 auth_clients — OAuth2 客户端注册

```sql
CREATE TABLE auth_clients (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  client_id      VARCHAR(64)  NOT NULL,
  client_secret  VARCHAR(128) NOT NULL COMMENT '服务间共享密钥（环境变量注入，不进日志）',
  client_name    VARCHAR(128) NOT NULL,
  redirect_uri   VARCHAR(512) NOT NULL COMMENT '精确匹配校验',
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_client_id (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='OAuth2 客户端';
```

seed：`ecogain-web`，redirect_uri = `{PUBLIC_BASE_URL}/auth/callback`。

### 4.3 auth_codes — 一次性授权码

```sql
CREATE TABLE auth_codes (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  code           VARCHAR(64)  NOT NULL,
  client_id      VARCHAR(64)  NOT NULL,
  user_id        BIGINT UNSIGNED NOT NULL,
  redirect_uri   VARCHAR(512) NOT NULL,
  expires_at     DATETIME(3)  NOT NULL COMMENT '5 分钟',
  consumed_at    DATETIME(3)  NULL,
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_code (code),
  KEY idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='OAuth2 授权码（一次性）';
```

## 5. DuckDB 分析库（analytics.duckdb）

通用约定：schema 隔离 4 场景 + 附件表置于 `attachments` schema；日期用 `DATE`、金额 `DECIMAL(12,2)`、数量 `INTEGER`；主键/索引概念弱化（DuckDB 按 ART 索引自动管理），以 `PRIMARY KEY` 声明约束即可。所有表由 `backend/seeds/init_analytics.py` 建表灌数（幂等：存在即 DROP 重建）。

seed 数据要求（PRD F10）：时间跨度近 90 天、内嵌约 3% 脏数据（NULL、超范围值、重复行、单位错位），供演示容错。

### 5.1 s1_catalog — 商品目录优化（P0）

```sql
CREATE SCHEMA s1_catalog;

CREATE TABLE s1_catalog.categories (        -- 类目表
  category_id   INTEGER PRIMARY KEY,
  category_name VARCHAR(64) NOT NULL,
  parent_id     INTEGER,                     -- 自引用，两级类目
  level         INTEGER NOT NULL,            -- 1 一级 / 2 二级
  status        VARCHAR(16) NOT NULL         -- active | disabled
);

CREATE TABLE s1_catalog.products (           -- 商品表
  product_id   INTEGER PRIMARY KEY,
  product_name VARCHAR(128) NOT NULL,
  category_id  INTEGER NOT NULL,
  brand        VARCHAR(64),
  price        DECIMAL(10,2) NOT NULL,
  status       VARCHAR(16) NOT NULL,         -- on | off
  created_at   DATE NOT NULL
);

CREATE TABLE s1_catalog.search_exposures (   -- 搜索曝光表
  exposure_date DATE NOT NULL,
  product_id    INTEGER NOT NULL,
  channel       VARCHAR(32) NOT NULL,        -- app | web | miniapp
  keyword       VARCHAR(64),
  exposure_cnt  INTEGER NOT NULL,
  PRIMARY KEY (exposure_date, product_id, channel, keyword)
);

CREATE TABLE s1_catalog.clicks (             -- 点击表
  click_date  DATE NOT NULL,
  product_id  INTEGER NOT NULL,
  channel     VARCHAR(32) NOT NULL,
  click_cnt   INTEGER NOT NULL,
  PRIMARY KEY (click_date, product_id, channel)
);

CREATE TABLE s1_catalog.conversions (        -- 转化表
  conv_date  DATE NOT NULL,
  product_id INTEGER NOT NULL,
  order_cnt  INTEGER NOT NULL,
  buyer_cnt  INTEGER NOT NULL,
  gmv        DECIMAL(14,2) NOT NULL,
  PRIMARY KEY (conv_date, product_id)
);
```

归因链路支撑：曝光/点击/转化按 (日期, 商品) 可 JOIN，形成分层漏斗；`channel` 维度支持下钻。

### 5.2 s2_refund — 退款模式分析（P0）

```sql
CREATE SCHEMA s2_refund;

CREATE TABLE s2_refund.users (               -- 用户表
  user_id       INTEGER PRIMARY KEY,
  username      VARCHAR(64) NOT NULL,
  city          VARCHAR(32),
  register_date DATE NOT NULL,
  user_level    VARCHAR(16) NOT NULL         -- new | bronze | silver | gold
);

CREATE TABLE s2_refund.orders (              -- 订单表
  order_id     BIGINT PRIMARY KEY,
  user_id      INTEGER NOT NULL,
  product_id   INTEGER NOT NULL,
  category_id  INTEGER NOT NULL,
  order_date   DATE NOT NULL,
  pay_amount   DECIMAL(12,2) NOT NULL,
  order_status VARCHAR(16) NOT NULL          -- paid | refunded | closed
);

CREATE TABLE s2_refund.refund_reasons (      -- 退款原因表
  reason_id       INTEGER PRIMARY KEY,
  reason_name     VARCHAR(64) NOT NULL,
  reason_category VARCHAR(32) NOT NULL       -- 质量 | 物流 | 描述不符 | 价格 | 其他
);

CREATE TABLE s2_refund.refund_applications ( -- 退款申请表
  refund_id     BIGINT PRIMARY KEY,
  order_id      BIGINT NOT NULL,
  reason_id     INTEGER NOT NULL,
  apply_time    TIMESTAMP NOT NULL,
  refund_amount DECIMAL(12,2) NOT NULL,
  refund_status VARCHAR(16) NOT NULL         -- approved | rejected | processing
);
```

归因链路支撑：退款率 = refund_applications / orders 按 (日期, 类目, SKU, 原因) 下钻；orders.category_id 冗余存储避免回表 products（本场景独立 schema，不依赖 s1）。

### 5.3 s3_behavior — 客户行为分析（P1）

```sql
CREATE SCHEMA s3_behavior;

CREATE TABLE s3_behavior.users (             -- 用户表
  user_id       INTEGER PRIMARY KEY,
  register_date DATE NOT NULL,
  channel       VARCHAR(32) NOT NULL,        -- organic | ads | social | referral
  is_new_month  INTEGER NOT NULL             -- 注册于 30 天内标记（按快照日计算）
);

CREATE TABLE s3_behavior.visit_events (      -- 访问事件表
  event_id   BIGINT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  event_time TIMESTAMP NOT NULL,
  page       VARCHAR(64) NOT NULL,           -- home | search | detail | cart | checkout
  device     VARCHAR(16) NOT NULL,           -- ios | android | pc
  source     VARCHAR(32)
);

CREATE TABLE s3_behavior.cart_events (       -- 加购事件表
  event_id   BIGINT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  event_time TIMESTAMP NOT NULL,
  product_id INTEGER NOT NULL,
  quantity   INTEGER NOT NULL
);

CREATE TABLE s3_behavior.order_events (      -- 下单事件表
  event_id   BIGINT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  event_time TIMESTAMP NOT NULL,
  order_id   BIGINT NOT NULL,
  product_id INTEGER NOT NULL,
  pay_amount DECIMAL(12,2) NOT NULL
);
```

归因链路支撑：访问→加购→下单漏斗按 user 维度聚合；`channel/device` 支持群体对比。

### 5.4 s4_inventory — 库存异常分析（P1）

```sql
CREATE SCHEMA s4_inventory;

CREATE TABLE s4_inventory.inventory (        -- 库存表（日快照）
  snapshot_date DATE NOT NULL,
  product_id    INTEGER NOT NULL,
  warehouse_id  INTEGER NOT NULL,
  qty_begin     INTEGER NOT NULL COMMENT '期初',
  qty_end       INTEGER NOT NULL COMMENT '期末',
  PRIMARY KEY (snapshot_date, product_id, warehouse_id)
);

CREATE TABLE s4_inventory.inbound_orders (   -- 入库表
  inbound_id   BIGINT PRIMARY KEY,
  product_id   INTEGER NOT NULL,
  warehouse_id INTEGER NOT NULL,
  inbound_date DATE NOT NULL,
  qty          INTEGER NOT NULL,
  biz_type     VARCHAR(32) NOT NULL          -- purchase | return | transfer_in
);

CREATE TABLE s4_inventory.outbound_orders (  -- 出库表
  outbound_id   BIGINT PRIMARY KEY,
  product_id    INTEGER NOT NULL,
  warehouse_id  INTEGER NOT NULL,
  outbound_date DATE NOT NULL,
  qty           INTEGER NOT NULL,
  biz_type      VARCHAR(32) NOT NULL         -- sale | scrap | transfer_out
);

CREATE TABLE s4_inventory.sales (            -- 销量表
  sale_id      BIGINT PRIMARY KEY,
  product_id   INTEGER NOT NULL,
  warehouse_id INTEGER NOT NULL,
  sale_date    DATE NOT NULL,
  qty          INTEGER NOT NULL,
  amount       DECIMAL(12,2) NOT NULL
);
```

归因链路支撑：核对公式 `qty_begin + SUM(入库) − SUM(出库) ≠ qty_end` 圈定异常 SKU；再关联 sales 波动与出入库 biz_type 分布定位原因（如 transfer 漏记）。

### 5.5 attachments — 附件导入动态表

csv/xlsx 附件解析后按下列规则建表：

- 位置：`attachments` schema；表名 `attachment_data_{attachment_id}`；
- 列类型推断：INT → `BIGINT`；浮点 → `DOUBLE`；日期（可解析）→ `DATE`；其余 `VARCHAR`；推断失败的列整体降 `VARCHAR`（脏数据容错）；
- 列名规范化：小写、空白→`_`、非法字符剔除、空列名 `col_{i}`、重复列名追加 `_2`；
- 追加元数据列：`__row_no BIGINT`（源文件行号，1-based，不含表头），供证据溯源；
- 生命周期：随附件删除 DROP；随会话删除全部 DROP（遍历 attachments.duckdb_table）。

## 6. 对象数据结构

### 6.1 API DTO（已迁移）

REST 接口的请求/响应 DTO（TypeScript 定义）与逐接口契约（参数表、必填、示例、错误场景）**统一维护于 `docs/API-接口设计文档.md`**，本节不再重复，避免双源漂移。

### 6.2 WS 消息对象（已迁移）

WebSocket 上行/下行消息对象的完整字段定义同样迁移至 `docs/API-接口设计文档.md` §8。存储层视角仅保留一条对应关系：`tool_start`/`tool_finish` 事件落库为 messages（message_type=tool_call），`result_ready` 对应 analysis_results 新增行。

### 6.3 六段结构化结果（Pydantic 模型 + JSON 示例 + Markdown 模板）

```python
class KeyMetric(BaseModel):
    metric_name: str            # 指标名
    metric_value: float | str   # 数值（无法量化时为文本）
    metric_unit: str            # % | 单 | 元 | ...
    metric_period: str          # 统计口径，如 "2026-07-19 ~ 2026-07-25（周同比）"

class Evidence(BaseModel):
    source_type: Literal['sql', 'file', 'text']
    source_name: str            # 如 "s2_refund.refund_applications 按 sku 聚合"
    evidence_text: str          # 证据陈述（含数值）
    related_metric: str         # 关联指标名
    confidence: Literal['high', 'medium', 'low']

class AnalysisResultModel(BaseModel):
    problem_definition: str                       # 六段-1
    key_metrics: list[KeyMetric]                  # 六段-2，min_length=1
    evidence_list: list[Evidence]                 # 六段-3，min_length=1
    conclusion_text: str                          # 六段-4
    missing_data_text: str | None = None          # 六段-5
    next_actions: list[str]                       # 六段-6，min_length=2
```

JSON 示例（落库 `key_metrics_json` / `evidence_list_json` 数组元素）：

```json
{
  "metric_name": "护肤品类退款率",
  "metric_value": 8.7,
  "metric_unit": "%",
  "metric_period": "2026-08-09 ~ 2026-08-15（周同比）"
}
```

```json
{
  "source_type": "sql",
  "source_name": "s2_refund.refund_applications 按 sku 聚合",
  "evidence_text": "SKU-A1023 周退款 47 单，占类目 31%，环比 +22pp",
  "related_metric": "护肤品类退款率",
  "confidence": "high"
}
```

Markdown 导出模板（`result_markdown` 渲染骨架，导出文件 `result_{task_id}.md`）：

```markdown
# 经营归因分析报告

> 任务：{task_id} ｜ 生成时间：{created_at}

## 1. 问题定义
{problem_definition}

## 2. 关键指标
| 指标 | 数值 | 单位 | 统计口径 |
| --- | --- | --- | --- |
| {metric_name} | {metric_value} | {metric_unit} | {metric_period} |

## 3. 证据列表
| 来源类型 | 来源 | 证据 | 关联指标 | 置信度 |
| --- | --- | --- | --- | --- |
| {source_type} | {source_name} | {evidence_text} | {related_metric} | {confidence} |

## 4. 归因结论
{conclusion_text}

## 5. 待补充数据
{missing_data_text}

## 6. 下一步建议
1. {next_action[0]}
2. {next_action[1]}
```

### 6.4 LangGraph Agent State

```python
class AnalysisState(TypedDict):
    messages: list[AnyMessage]          # LangChain 消息序列（含 ToolMessage 回填）
    task_id: int
    conversation_id: int
    user_id: int
    trace_id: str
    attachment_schemas: list[dict]      # [{table, columns:[{name,type}], row_count}] 结构化附件
    text_attachments: list[dict]        # [{file_name, preview}] 文本附件
    tool_rounds: int                    # 已执行工具轮次（上限 max_tool_rounds）
    final_result: AnalysisResultModel | None   # output_node 产出
```

### 6.5 配置项清单（system_configs seed）

| config_key | 组 | 类型 | 默认值 | 校验规则 |
| --- | --- | --- | --- | --- |
| llm.provider | llm | string | zhipu | 非空 |
| llm.base_url | llm | string | https://open.bigmodel.cn/api/paas/v4 | 非空 + URL 格式 |
| llm.model | llm | string | glm-4.6 | 非空 |
| llm.api_key_ref | llm | string | LLM_API_KEY | 环境变量引用名，非空 |
| llm.temperature | llm | float | 0.2 | 0 ~ 1 |
| agent.max_tool_rounds | agent | int | 15 | 5 ~ 50 |
| agent.task_timeout_seconds | agent | int | 120 | 30 ~ 600 |
| agent.context_rounds | agent | int | 20 | 5 ~ 100 |
| agent.context_token_budget | agent | int | 8000 | 2000 ~ 100000 |
| agent.sql_row_limit | agent | int | 1000 | 100 ~ 10000 |
| agent.sql_timeout_seconds | agent | int | 10 | 1 ~ 60 |
| datasource.duckdb_path | datasource | string | /data/analytics/analytics.duckdb | 容器内绝对路径 |
| feature.attachment_enabled | feature | bool | true | 布尔 |
| feature.export_enabled | feature | bool | true | 布尔 |

## 7. 数据生命周期矩阵

### 7.1 会话删除清理清单（CONV-4 级联）

| 对象 | 存储位置 | 清理动作 |
| --- | --- | --- |
| conversations 行 | MySQL | UPDATE status='deleted'（软删保留行） |
| messages 行 | MySQL | 物理 DELETE |
| attachments 行 | MySQL | 物理 DELETE（先取 file_path/duckdb_table） |
| analysis_tasks 行 | MySQL | 物理 DELETE |
| analysis_results 行 | MySQL | 物理 DELETE |
| context_summaries 行 | MySQL | 物理 DELETE |
| task_logs 行 | MySQL | 物理 DELETE（随任务） |
| attachment_data_{id} 表 | DuckDB | DROP TABLE（写锁内） |
| uploads/{uid}/{cid}/ 目录 | 文件卷 | rmtree |
| exports/{uid}/{cid}/ 目录 | 文件卷 | rmtree |
| workspace/{uid}/{cid}/ 目录 | 文件卷 | rmtree（含文本检索缓存） |

### 7.2 任务状态与数据产出对照

| 终态 | messages | analysis_results | exports 文件 | task_logs |
| --- | --- | --- | --- | --- |
| success | user 问题 + assistant 文本 + tool_call 消息 + result 卡片消息 | ✅ 一行（含 markdown） | ✅ result_{task_id}.md | 全流程 |
| failed | 已产生的中间消息保留 | ❌ | ❌ | 全流程 + 错误记录 |
| cancelled | 已产生的中间消息保留 | ❌ | ❌ | 全流程 + 取消记录 |
| 超时（failed） | 同 failed（error=50003） | ❌ | ❌ | 含超时记录 |

### 7.3 定期清理任务

| 对象 | 规则 |
| --- | --- |
| websocket_tokens | 每小时删除过期 1h 以上的行 |
| auth_codes（auth 库） | 每小时删除过期 1h 以上的行 |
| workspace 临时文件 | 会话删除时随目录清理；无独立周期任务（POC 级） |

## 8. 数据量估算与索引设计说明

### 8.1 seed 数据规模（DuckDB）

| 场景 | 表 | 行数量级 | 说明 |
| --- | --- | --- | --- |
| s1_catalog | products / categories | 500 / 40 | 两级类目 |
| s1_catalog | search_exposures / clicks / conversions | 90 天 × 500 商品 × 3 渠道 ≈ 13.5 万 / 4.5 万 / 4.5 万 | 漏斗逐层递减 |
| s2_refund | users / orders | 2000 / 5 万 | 90 天 |
| s2_refund | refund_applications | 3000（约 6% 退款率） | 注入护肤品类异常聚集 |
| s3_behavior | visit / cart / order events | 20 万 / 4 万 / 2.5 万 | 漏斗比 100:20:12.5 |
| s4_inventory | inventory 快照 | 90 天 × 100 SKU × 3 仓 ≈ 2.7 万 | 注入 5 个 SKU 账实不符 |
| s4_inventory | inbound / outbound / sales | 各 1 万左右 | biz_type 分布合理 |

单库文件预估 < 100MB，POC 规模无性能压力。

### 8.2 MySQL 系统库增长估算

按 POC 目标（≤5 并发、演示强度）：每轮分析产出约 6~12 条 messages、1 行 task + 1 行 result + 10~20 行 task_logs；千轮分析后 messages ≈ 1 万行、task_logs ≈ 2 万行——均远低于 MySQL 舒适区，现有索引（uk_conv_seq、idx_task_created）足够。

### 8.3 查询模式与索引对应

| 高频查询 | 命中索引 |
| --- | --- |
| 会话列表（用户维度倒序） | conversations.idx_user_status_last |
| 历史消息回放 | messages.uk_conv_seq |
| 并发任务计数 | analysis_tasks.idx_status |
| 任务日志查询 | task_logs.idx_task_created |
| WS 令牌原子消费 | websocket_tokens.uk_token |
| 附件归属与删除定位 | attachments.idx_conv |
