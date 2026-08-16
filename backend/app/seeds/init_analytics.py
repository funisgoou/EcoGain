"""EcoGain DuckDB 分析库建库灌数脚本（4 场景 schema × 17 张表）。

用途
----
按 `docs/DATA-数据设计文档.md` §5 的 DDL 重建 DuckDB 分析库的 4 个场景 schema，
灌入以运行日为锚、往前 90 天的确定性模拟数据（DATA §8.1 规模），并在数据中内嵌
每个场景的"预期归因答案"剧本与约 3% 脏数据（NULL / 超范围值 / 单位错位 /
重复主键候选），供演示容错与 Agent 提示词调优使用。

幂等语义
--------
每次运行对 4 个场景 schema 逐一执行 ``DROP SCHEMA IF EXISTS <schema> CASCADE``
后重建并灌数，可重复执行；数据由 ``random.Random(42)`` 固定种子顺序生成，
同日重跑结果完全一致（跨日重跑时时间窗整体随运行日平移，剧本信号不变）。

运行
----
    cd backend && uv run python -m app.seeds.init_analytics --db-path ./data/analytics/analytics.duckdb

说明：DATA §5 DDL 中的列内 ``COMMENT 'xxx'`` 关键字 DuckDB 不支持，
本脚本已等价改写为行尾 SQL 注释（``-- xxx``），列名/类型/主键声明与文档严格一致。
"""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

__all__ = [
    "SCENARIO_DATA_DICTIONARY",
    "main",
    "seed_s1_catalog",
    "seed_s2_refund",
    "seed_s3_behavior",
    "seed_s4_inventory",
]

# ---------------------------------------------------------------------------
# SCENARIO_DATA_DICTIONARY —— 静态数据字典（供 Agent 提示词使用）
# 与下方 DDL_* 实际建表列严格一致；勿随手改 DDL 而不同步此处。
# ---------------------------------------------------------------------------
SCENARIO_DATA_DICTIONARY: str = """EcoGain 分析库（analytics.duckdb）数据字典。时间跨度：以灌数运行日为锚往前 90 天；内嵌约 3% 脏数据（NULL、超范围值、单位错位），分析时需容错。

【s1_catalog 商品目录优化】三级漏斗：曝光→点击→转化，按 (日期, product_id) JOIN，channel 支持下钻。
s1_catalog.categories(category_id: INTEGER PK, category_name: VARCHAR(64), parent_id: INTEGER 自引用两级类目, level: INTEGER 1一级/2二级, status: VARCHAR(16) active|disabled)
s1_catalog.products(product_id: INTEGER PK, product_name: VARCHAR(128), category_id: INTEGER 指向二级类目, brand: VARCHAR(64) 可空, price: DECIMAL(10,2), status: VARCHAR(16) on|off, created_at: DATE)
s1_catalog.search_exposures(exposure_date: DATE, product_id: INTEGER, channel: VARCHAR(32) app|web|miniapp, keyword: VARCHAR(64), exposure_cnt: INTEGER, PK=(exposure_date, product_id, channel, keyword))
s1_catalog.clicks(click_date: DATE, product_id: INTEGER, channel: VARCHAR(32) 商品主渠道汇总行, click_cnt: INTEGER 当日全渠道点击合计, PK=(click_date, product_id, channel))
s1_catalog.conversions(conv_date: DATE, product_id: INTEGER, order_cnt: INTEGER 下单数, buyer_cnt: INTEGER 买家数, gmv: DECIMAL(14,2), PK=(conv_date, product_id))

【s2_refund 退款模式分析】退款率 = refund_applications / orders，可按 (日期, 类目, SKU, 原因) 下钻；本场景 category_id 独立编码 1~20，10=护肤。
s2_refund.users(user_id: INTEGER PK, username: VARCHAR(64), city: VARCHAR(32) 可空, register_date: DATE, user_level: VARCHAR(16) new|bronze|silver|gold)
s2_refund.orders(order_id: BIGINT PK, user_id: INTEGER, product_id: INTEGER SKU 编码, category_id: INTEGER 冗余存储, order_date: DATE, pay_amount: DECIMAL(12,2), order_status: VARCHAR(16) paid|refunded|closed)
s2_refund.refund_reasons(reason_id: INTEGER PK, reason_name: VARCHAR(64), reason_category: VARCHAR(32) 质量|物流|描述不符|价格|其他)
s2_refund.refund_applications(refund_id: BIGINT PK, order_id: BIGINT 关联 orders.order_id, reason_id: INTEGER 关联 refund_reasons, apply_time: TIMESTAMP, refund_amount: DECIMAL(12,2), refund_status: VARCHAR(16) approved|rejected|processing)

【s3_behavior 客户行为分析】访问→加购→下单漏斗（行数比约 100:20:12.5），按 user 维度聚合，device/channel 支持群体对比；device 为用户稳定属性，可经 visit_events 反查。
s3_behavior.users(user_id: INTEGER PK, register_date: DATE, channel: VARCHAR(32) organic|ads|social|referral, is_new_month: INTEGER 0|1 注册于 30 天内标记)
s3_behavior.visit_events(event_id: BIGINT PK, user_id: INTEGER, event_time: TIMESTAMP, page: VARCHAR(64) home|search|detail|cart|checkout, device: VARCHAR(16) ios|android|pc, source: VARCHAR(32) 可空)
s3_behavior.cart_events(event_id: BIGINT PK, user_id: INTEGER, event_time: TIMESTAMP, product_id: INTEGER, quantity: INTEGER)
s3_behavior.order_events(event_id: BIGINT PK, user_id: INTEGER, event_time: TIMESTAMP, order_id: BIGINT, product_id: INTEGER, pay_amount: DECIMAL(12,2))

【s4_inventory 库存异常分析】核对公式：qty_begin + SUM(入库) - SUM(出库) != qty_end 圈定异常 SKU，再关联 sales 波动与 biz_type 分布定位原因。
s4_inventory.inventory(snapshot_date: DATE, product_id: INTEGER, warehouse_id: INTEGER, qty_begin: INTEGER 期初, qty_end: INTEGER 期末=次日期初, PK=(snapshot_date, product_id, warehouse_id))
s4_inventory.inbound_orders(inbound_id: BIGINT PK, product_id: INTEGER, warehouse_id: INTEGER, inbound_date: DATE, qty: INTEGER, biz_type: VARCHAR(32) purchase|return|transfer_in)
s4_inventory.outbound_orders(outbound_id: BIGINT PK, product_id: INTEGER, warehouse_id: INTEGER, outbound_date: DATE, qty: INTEGER, biz_type: VARCHAR(32) sale|scrap|transfer_out)
s4_inventory.sales(sale_id: BIGINT PK, product_id: INTEGER, warehouse_id: INTEGER, sale_date: DATE, qty: INTEGER, amount: DECIMAL(12,2))

【attachments 附件导入动态表】csv/xlsx 附件解析后动态建表，无预置数据。
attachments.attachment_data_{attachment_id}(列由类型推断：整数→BIGINT、浮点→DOUBLE、可解析日期→DATE、其余→VARCHAR，推断失败整列降 VARCHAR；追加 __row_no: BIGINT 源文件行号 1-based 不含表头；随附件/会话删除而 DROP)"""

# ---------------------------------------------------------------------------
# 全局常量：种子 / 时间锚点 / 批大小
# ---------------------------------------------------------------------------
SEED = 42
DAYS = 90
BATCH_SIZE = 5000
RNG = random.Random(SEED)  # 单例顺序消费，保证幂等可复现

TODAY = date.today()                     # 运行日锚点（不写死日期）
START = TODAY - timedelta(days=DAYS - 1)  # 覆盖 [START, TODAY] 共 90 天


def _money(v) -> Decimal:
    """金额统一 2 位小数落 DECIMAL 列。"""
    return Decimal(f"{v:.2f}")


def _rand_date(start: date, end: date) -> date:
    return start + timedelta(days=RNG.randint(0, (end - start).days))


def _rand_ts(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, RNG.randint(0, 23), RNG.randint(0, 59), RNG.randint(0, 59))


# ---------------------------------------------------------------------------
# DDL（照搬 DATA §5；COMMENT 关键字已改为行尾注释，DuckDB 兼容）
# ---------------------------------------------------------------------------
DDL_S1 = (
    """CREATE TABLE s1_catalog.categories (        -- 类目表
  category_id   INTEGER PRIMARY KEY,
  category_name VARCHAR(64) NOT NULL,
  parent_id     INTEGER,                     -- 自引用，两级类目
  level         INTEGER NOT NULL,            -- 1 一级 / 2 二级
  status        VARCHAR(16) NOT NULL         -- active | disabled
)""",
    """CREATE TABLE s1_catalog.products (           -- 商品表
  product_id   INTEGER PRIMARY KEY,
  product_name VARCHAR(128) NOT NULL,
  category_id  INTEGER NOT NULL,
  brand        VARCHAR(64),
  price        DECIMAL(10,2) NOT NULL,
  status       VARCHAR(16) NOT NULL,         -- on | off
  created_at   DATE NOT NULL
)""",
    """CREATE TABLE s1_catalog.search_exposures (   -- 搜索曝光表
  exposure_date DATE NOT NULL,
  product_id    INTEGER NOT NULL,
  channel       VARCHAR(32) NOT NULL,        -- app | web | miniapp
  keyword       VARCHAR(64),
  exposure_cnt  INTEGER NOT NULL,
  PRIMARY KEY (exposure_date, product_id, channel, keyword)
)""",
    """CREATE TABLE s1_catalog.clicks (             -- 点击表
  click_date  DATE NOT NULL,
  product_id  INTEGER NOT NULL,
  channel     VARCHAR(32) NOT NULL,
  click_cnt   INTEGER NOT NULL,
  PRIMARY KEY (click_date, product_id, channel)
)""",
    """CREATE TABLE s1_catalog.conversions (        -- 转化表
  conv_date  DATE NOT NULL,
  product_id INTEGER NOT NULL,
  order_cnt  INTEGER NOT NULL,
  buyer_cnt  INTEGER NOT NULL,
  gmv        DECIMAL(14,2) NOT NULL,
  PRIMARY KEY (conv_date, product_id)
)""",
)

DDL_S2 = (
    """CREATE TABLE s2_refund.users (               -- 用户表
  user_id       INTEGER PRIMARY KEY,
  username      VARCHAR(64) NOT NULL,
  city          VARCHAR(32),
  register_date DATE NOT NULL,
  user_level    VARCHAR(16) NOT NULL         -- new | bronze | silver | gold
)""",
    """CREATE TABLE s2_refund.orders (               -- 订单表
  order_id     BIGINT PRIMARY KEY,
  user_id      INTEGER NOT NULL,
  product_id   INTEGER NOT NULL,
  category_id  INTEGER NOT NULL,
  order_date   DATE NOT NULL,
  pay_amount   DECIMAL(12,2) NOT NULL,
  order_status VARCHAR(16) NOT NULL          -- paid | refunded | closed
)""",
    """CREATE TABLE s2_refund.refund_reasons (      -- 退款原因表
  reason_id       INTEGER PRIMARY KEY,
  reason_name    VARCHAR(64) NOT NULL,
  reason_category VARCHAR(32) NOT NULL       -- 质量 | 物流 | 描述不符 | 价格 | 其他
)""",
    """CREATE TABLE s2_refund.refund_applications ( -- 退款申请表
  refund_id     BIGINT PRIMARY KEY,
  order_id      BIGINT NOT NULL,
  reason_id     INTEGER NOT NULL,
  apply_time    TIMESTAMP NOT NULL,
  refund_amount DECIMAL(12,2) NOT NULL,
  refund_status VARCHAR(16) NOT NULL          -- approved | rejected | processing
)""",
)

DDL_S3 = (
    """CREATE TABLE s3_behavior.users (              -- 用户表
  user_id       INTEGER PRIMARY KEY,
  register_date DATE NOT NULL,
  channel       VARCHAR(32) NOT NULL,        -- organic | ads | social | referral
  is_new_month  INTEGER NOT NULL             -- 注册于 30 天内标记（按快照日计算）
)""",
    """CREATE TABLE s3_behavior.visit_events (      -- 访问事件表
  event_id   BIGINT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  event_time TIMESTAMP NOT NULL,
  page       VARCHAR(64) NOT NULL,           -- home | search | detail | cart | checkout
  device     VARCHAR(16) NOT NULL,           -- ios | android | pc
  source     VARCHAR(32)
)""",
    """CREATE TABLE s3_behavior.cart_events (       -- 加购事件表
  event_id   BIGINT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  event_time TIMESTAMP NOT NULL,
  product_id INTEGER NOT NULL,
  quantity   INTEGER NOT NULL
)""",
    """CREATE TABLE s3_behavior.order_events (      -- 下单事件表
  event_id   BIGINT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  event_time TIMESTAMP NOT NULL,
  order_id   BIGINT NOT NULL,
  product_id INTEGER NOT NULL,
  pay_amount DECIMAL(12,2) NOT NULL
)""",
)

DDL_S4 = (
    """CREATE TABLE s4_inventory.inventory (        -- 库存表（日快照）
  snapshot_date DATE NOT NULL,
  product_id    INTEGER NOT NULL,
  warehouse_id  INTEGER NOT NULL,
  qty_begin     INTEGER NOT NULL,            -- 期初
  qty_end       INTEGER NOT NULL,            -- 期末
  PRIMARY KEY (snapshot_date, product_id, warehouse_id)
)""",
    """CREATE TABLE s4_inventory.inbound_orders (   -- 入库表
  inbound_id   BIGINT PRIMARY KEY,
  product_id   INTEGER NOT NULL,
  warehouse_id INTEGER NOT NULL,
  inbound_date DATE NOT NULL,
  qty          INTEGER NOT NULL,
  biz_type     VARCHAR(32) NOT NULL          -- purchase | return | transfer_in
)""",
    """CREATE TABLE s4_inventory.outbound_orders (  -- 出库表
  outbound_id   BIGINT PRIMARY KEY,
  product_id    INTEGER NOT NULL,
  warehouse_id  INTEGER NOT NULL,
  outbound_date DATE NOT NULL,
  qty           INTEGER NOT NULL,
  biz_type      VARCHAR(32) NOT NULL          -- sale | scrap | transfer_out
)""",
    """CREATE TABLE s4_inventory.sales (            -- 销量表
  sale_id      BIGINT PRIMARY KEY,
  product_id   INTEGER NOT NULL,
  warehouse_id INTEGER NOT NULL,
  sale_date    DATE NOT NULL,
  qty          INTEGER NOT NULL,
  amount       DECIMAL(12,2) NOT NULL
)""",
)

# 行数统计注册表（main 结束时按实际库内计数打印）
TABLE_REGISTRY: dict[str, list[str]] = {
    "s1_catalog": ["categories", "products", "search_exposures", "clicks", "conversions"],
    "s2_refund": ["users", "orders", "refund_reasons", "refund_applications"],
    "s3_behavior": ["users", "visit_events", "cart_events", "order_events"],
    "s4_inventory": ["inventory", "inbound_orders", "outbound_orders", "sales"],
}

# ---------------------------------------------------------------------------
# 通用工具：分批插入 / 脏数据注入
# ---------------------------------------------------------------------------
# 【脏数据注入策略】（DATA §5 通用约定：约 3% 行，供演示容错）
#   1) 可空列置 NULL（如 users.city、products.brand、visit_events.source）；
#   2) NOT NULL 列注入超范围值：负数量 / 负金额 / 非法枚举 / 未来时间 / 百倍单位错位；
#   3) 重复主键：按 ~0.5% 复制已有行并扰动非主键数值列，随后按主键去重"丢弃"
#      （DuckDB PRIMARY KEY 唯一约束强制，不能真插重复行）；
#   4) 所有脏数据均通过 protect 谓词避开各场景"归因剧本"核心行，避免淹没预期信号；
#      s4 的 inventory 日快照不注入脏值，保证账实核对链纯净（否则异常 SKU 被噪声淹没）。


def insert_batches(conn: duckdb.DuckDBPyConnection, sql: str, rows: list, batch_size: int = BATCH_SIZE) -> int:
    """executemany 分批插入（每批 5000），整表包在单事务内提交（批量提交可数倍提速），返回插入行数。"""
    conn.execute("BEGIN TRANSACTION")
    try:
        for i in range(0, len(rows), batch_size):
            conn.executemany(sql, rows[i : i + batch_size])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def _dirty_pass(rows: list, mutate, protect=None, rate: float = 0.03) -> int:
    """对 rows 就地注入约 rate 比例脏数据，返回命中行数；protect(row) 为 True 的行跳过。"""
    dirty = 0
    for r in rows:
        if protect is not None and protect(r):
            continue
        if RNG.random() < rate:
            mutate(r)
            dirty += 1
    return dirty


def _duplicate_pk_pass(rows: list, pk_last_idx: int, value_idx: int, rate: float = 0.005) -> int:
    """脏数据·重复主键：复制少量行并扰动非主键数值列模拟"重复上报"，
    随后按主键（rows 行首 0..pk_last_idx 列）去重丢弃，保证不炸 PRIMARY KEY。返回丢弃行数。"""
    if len(rows) < 200:
        return 0
    dups = []
    for _ in range(max(1, int(len(rows) * rate))):
        dup = list(RNG.choice(rows))
        v = dup[value_idx]
        dup[value_idx] = v + RNG.randint(1, 99) if isinstance(v, int) else _money(float(v) * 1.5)
        dups.append(dup)
    rows.extend(dups)
    seen: set = set()
    kept = []
    for r in rows:
        k = tuple(r[: pk_last_idx + 1])
        if k in seen:
            continue
        seen.add(k)
        kept.append(r)
    dropped = len(rows) - len(kept)
    rows[:] = kept
    return dropped


# --- 各表脏数据变换函数（r 为行 list，按列下标改值） ---
def _dirty_category(r: list) -> None:
    roll = RNG.random()
    if roll < 0.4:
        r[4] = "unknown"          # 非法枚举
    elif roll < 0.7:
        r[3] = 3                  # 超范围层级
    elif r[3] == 2:
        r[2] = None               # 二级类目孤儿（可空列置 NULL）


def _dirty_product(r: list) -> None:
    roll = RNG.random()
    if roll < 0.3:
        r[3] = None               # brand 置 NULL
    elif roll < 0.55:
        r[4] = -abs(r[4])         # 负价格
    elif roll < 0.8:
        r[4] = abs(r[4]) * 100    # 单位错位（分→元）
    else:
        r[6] = TODAY + timedelta(days=RNG.randint(10, 60))  # 未来创建时间


def _dirty_exposure(r: list) -> None:
    roll = RNG.random()
    if roll < 0.35:
        r[4] = 0
    elif roll < 0.7:
        r[4] = -abs(r[4]) if r[4] else -1   # 负曝光量
    else:
        r[4] = abs(r[4]) * 100               # 百倍单位错位


def _dirty_click(r: list) -> None:
    roll = RNG.random()
    if roll < 0.5:
        r[3] = -abs(r[3]) if r[3] else -1
    else:
        r[3] = abs(r[3]) * 100               # 点击大于曝光（单位错位）


def _dirty_conversion(r: list) -> None:
    roll = RNG.random()
    if roll < 0.35:
        r[2] = -abs(r[2]) if r[2] else -1    # 负订单数
    elif roll < 0.6:
        r[4] = -abs(r[4])                    # 负 GMV
    else:
        r[3] = r[2] + RNG.randint(1, 20)     # 买家数 > 订单数（超范围）


def _dirty_user_s2(r: list) -> None:
    if RNG.random() < 0.5:
        r[2] = None                          # city 置 NULL
    else:
        r[4] = "unknown"                     # 非法等级枚举


def _dirty_order_s2(r: list) -> None:
    roll = RNG.random()
    if roll < 0.4:
        r[5] = -abs(r[5])                    # 负金额
    elif roll < 0.7:
        r[5] = abs(r[5]) * 100               # 单位错位（分→元）
    else:
        r[3] = 999                           # 超范围类目引用


def _dirty_refund(r: list) -> None:
    if RNG.random() < 0.6:
        r[4] = -abs(r[4])                    # 负退款额
    else:
        r[5] = "unknown"                     # 非法状态枚举


def _dirty_visit_s3(r: list) -> None:
    roll = RNG.random()
    if roll < 0.35:
        r[5] = None                          # source 置 NULL
    elif roll < 0.6:
        r[3] = "unknown"                     # 非法页面枚举
    else:
        r[2] = r[2] + timedelta(days=RNG.randint(1, 5))  # 未来时间（超范围）


def _dirty_cart_s3(r: list) -> None:
    r[4] = -abs(r[4]) if r[4] else -1        # 负数量


def _dirty_order_s3(r: list) -> None:
    if RNG.random() < 0.5:
        r[5] = -abs(r[5])                    # 负金额
    else:
        r[5] = abs(r[5]) * 100               # 单位错位


def _dirty_sale_s4(r: list) -> None:
    roll = RNG.random()
    if roll < 0.4:
        r[4] = -abs(r[4]) if r[4] else -1    # 负销量（sales 不参与账实核对，安全）
    elif roll < 0.7:
        r[5] = -abs(r[5])                    # 负金额
    else:
        r[5] = abs(r[5]) * 100               # 单位错位


def _dirty_ledger_biztype(r: list) -> None:
    r[5] = "unknown"                         # 非法业务类型枚举（不改变数量，账实核对不受影响）


# ---------------------------------------------------------------------------
# s1_catalog —— 商品目录优化
# ---------------------------------------------------------------------------
L1_CATEGORY_NAMES = ["护肤", "彩妆", "个护家清", "母婴", "保健", "食品饮料", "数码家电", "服饰内衣"]
L2_SUFFIXES: dict[str, list[str]] = {
    "护肤": ["精华", "面膜", "洁面", "乳液面霜"],
    "彩妆": ["口红", "粉底", "眼影", "化妆工具"],
    "个护家清": ["洗发护发", "沐浴清洁", "纸品家清", "口腔护理"],
    "母婴": ["婴儿辅食", "奶粉", "纸尿裤", "婴儿洗护"],
    "保健": ["维生素", "蛋白粉", "鱼油", "益生菌"],
    "食品饮料": ["休闲零食", "饮品冲调", "粮油调味", "生鲜速食"],
    "数码家电": ["耳机", "手机配件", "充电设备", "智能音箱"],
    "服饰内衣": ["男装", "女装", "内衣家居服", "运动服饰"],
}
# 剧本指定的 3 个异常二级类目
S1_ANOMALY_SUBCATEGORY_NAMES = ("护肤-精华", "彩妆-口红", "保健-蛋白粉")

BRANDS = ["自然堂", "珀莱雅", "兰蔻", "欧莱雅", "资生堂", "薇诺娜", "汤臣倍健", "斯维诗",
          "三只松鼠", "良品铺子", "全棉时代", "babycare", "小米", "华为", "南极人", "优衣库"]
KEYWORDS = ["官方旗舰店", "正品保障", "限时折扣", "新品上市", "热卖爆款", "包邮", "买一送一", "券后价"]
CHANNELS = ("app", "web", "miniapp")


def seed_s1_catalog(conn: duckdb.DuckDBPyConnection) -> None:
    """【归因剧本·s1_catalog —— 流量质量劣化】

    预期归因答案：二级类目「护肤-精华」「彩妆-口红」「保健-蛋白粉」下的商品（约 47 个）
    近 30 天搜索曝光量暴涨 3.5~5 倍，但点击率（CTR）仅为大盘的 ~18%（约 2% vs 大盘 8%~15%），
    转化率（订单/点击）仅为大盘的 ~30%。即：三个类目买量/关键词引流失真，
    曝光激增但流量质量劣化，CTR 与 CVR 双双显著低于大盘——可由 SQL 按
    (近 30 天 vs 前 60 天) 分组对比曝光量、CTR、CVR 直接发现。

    脏数据：products(brand NULL/负价/价格单位错位/未来创建时间)、categories(非法枚举/孤儿类目)、
    三张事实表(负计数/置 0/百倍单位错位)；重复主键候选生成后去重丢弃。
    剧本商品（3 个异常类目下的 product）全部豁免脏数据，保证信号干净。
    """
    conn.execute("DROP SCHEMA IF EXISTS s1_catalog CASCADE")
    conn.execute("CREATE SCHEMA s1_catalog")
    for stmt in DDL_S1:
        conn.execute(stmt)

    # ---- 维度：类目（8 一级 × 4 二级 = 40，两级结构）----
    cat_rows: list[list] = []
    name_of_cat: dict[int, str] = {}
    l1_ids: dict[str, int] = {}
    next_id = 1
    for l1 in L1_CATEGORY_NAMES:
        l1_ids[l1] = next_id
        name_of_cat[next_id] = l1
        cat_rows.append([next_id, l1, None, 1, "active" if RNG.random() > 0.05 else "disabled"])
        next_id += 1
    subcat_id_of_name: dict[str, int] = {}
    for l1 in L1_CATEGORY_NAMES:
        for suffix in L2_SUFFIXES[l1]:
            name = f"{l1}-{suffix}"
            subcat_id_of_name[name] = next_id
            name_of_cat[next_id] = name
            cat_rows.append([next_id, name, l1_ids[l1], 2, "active"])
            next_id += 1
    anomaly_cat_ids = {subcat_id_of_name[n] for n in S1_ANOMALY_SUBCATEGORY_NAMES}

    # ---- 维度：商品 500，均匀挂到 32 个二级类目 ----
    subcat_ids = list(range(9, 41))  # 二级类目 id 9..40
    product_rows: list[list] = []
    main_channel: dict[int, str] = {}
    base_metrics: dict[int, tuple[int, float, float]] = {}  # pid -> (基础日曝光, CTR, CVR)
    surge_factor: dict[int, float] = {}
    cat_of_product: dict[int, int] = {}
    for pid in range(1, 501):
        cid = subcat_ids[(pid - 1) % len(subcat_ids)]
        cat_of_product[pid] = cid
        brand = RNG.choice(BRANDS)
        sub_name = name_of_cat[cid]
        product_rows.append([
            pid,
            f"{brand}·{sub_name} {pid:03d}号",
            cid,
            brand,
            _money(RNG.uniform(19.9, 899.9)),
            "on" if RNG.random() < 0.92 else "off",
            _rand_date(START - timedelta(days=730), START - timedelta(days=1)),
        ])
        main_channel[pid] = RNG.choices(CHANNELS, weights=(0.5, 0.3, 0.2))[0]
        base_metrics[pid] = (RNG.randint(150, 600), RNG.uniform(0.08, 0.15), RNG.uniform(0.20, 0.35))
        if cid in anomaly_cat_ids:
            surge_factor[pid] = RNG.uniform(3.5, 5.0)  # 近 30 天曝光暴涨系数
    anomaly_pids = {pid for pid in range(1, 501) if cat_of_product[pid] in anomaly_cat_ids}

    # ---- 事实：曝光 90×500×3=13.5万；点击 90×500=4.5万（主渠道汇总行）；转化 4.5万 ----
    exposures: list[list] = []
    click_rows: list[list] = []
    conv_rows: list[list] = []
    for d in range(DAYS):
        day = START + timedelta(days=d)
        recent = d >= DAYS - 30  # 剧本窗口：近 30 天
        for pid in range(1, 501):
            base_expo, ctr, cvr = base_metrics[pid]
            is_anom = pid in anomaly_pids
            surge = surge_factor[pid] if (is_anom and recent) else 1.0
            ctr_eff = ctr * 0.18 if (is_anom and recent) else ctr
            cvr_eff = cvr * 0.30 if (is_anom and recent) else cvr
            expo_total = 0
            for ch, w in (("app", 0.5), ("web", 0.3), ("miniapp", 0.2)):
                n = max(int(base_expo * w * surge * RNG.uniform(0.7, 1.3)), 0)
                exposures.append([day, pid, ch, RNG.choice(KEYWORDS), n])
                expo_total += n
            clicks = max(int(expo_total * ctr_eff * RNG.uniform(0.8, 1.2)), 0)
            click_rows.append([day, pid, main_channel[pid], clicks])
            order_cnt = max(int(clicks * cvr_eff * RNG.uniform(0.8, 1.2)), 0)
            buyer_cnt = int(order_cnt * RNG.uniform(0.8, 1.0))
            price = product_rows[pid - 1][4]
            conv_rows.append([day, pid, order_cnt, buyer_cnt, _money(order_cnt * float(price) * RNG.uniform(0.9, 1.1))])

    # ---- 脏数据 + 重复主键（剧本商品豁免）----
    n_dirty = [
        _dirty_pass(cat_rows, _dirty_category, protect=lambda r: r[0] in anomaly_cat_ids, rate=0.05),
        _dirty_pass(product_rows, _dirty_product, protect=lambda r: r[0] in anomaly_pids),
        _dirty_pass(exposures, _dirty_exposure, protect=lambda r: r[1] in anomaly_pids),
        _dirty_pass(click_rows, _dirty_click, protect=lambda r: r[1] in anomaly_pids),
        _dirty_pass(conv_rows, _dirty_conversion, protect=lambda r: r[1] in anomaly_pids),
    ]
    n_dup = [
        _duplicate_pk_pass(exposures, 3, 4),
        _duplicate_pk_pass(click_rows, 2, 3),
        _duplicate_pk_pass(conv_rows, 1, 4),
    ]

    # ---- 灌数 ----
    insert_batches(conn, "INSERT INTO s1_catalog.categories VALUES (?, ?, ?, ?, ?)", cat_rows)
    insert_batches(conn, "INSERT INTO s1_catalog.products VALUES (?, ?, ?, ?, ?, ?, ?)", product_rows)
    insert_batches(conn, "INSERT INTO s1_catalog.search_exposures VALUES (?, ?, ?, ?, ?)", exposures)
    insert_batches(conn, "INSERT INTO s1_catalog.clicks VALUES (?, ?, ?, ?)", click_rows)
    insert_batches(conn, "INSERT INTO s1_catalog.conversions VALUES (?, ?, ?, ?, ?)", conv_rows)
    print(f"[s1_catalog] categories={len(cat_rows)} products={len(product_rows)} "
          f"search_exposures={len(exposures)} clicks={len(click_rows)} conversions={len(conv_rows)} "
          f"(脏 {sum(n_dirty)} 行, 重复主键丢弃 {sum(n_dup)} 行)")


# ---------------------------------------------------------------------------
# s2_refund —— 退款模式分析
# ---------------------------------------------------------------------------
CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "重庆", "西安",
          "苏州", "天津", "长沙", "郑州", "青岛", "合肥", "福州", "昆明", "沈阳", "厦门"]
S2_SKINCARE_CATEGORY_ID = 10          # 剧本固定：护肤品类 category_id = 10（s2 独立类目空间 1~20）
S2_ANOMALY_PRODUCT_IDS = (1023, 1024)  # 剧本固定：SKU-A1023 / SKU-A1024


def seed_s2_refund(conn: duckdb.DuckDBPyConnection) -> None:
    """【归因剧本·s2_refund —— 描述不符退款 scandal】

    预期归因答案：护肤品类（category_id=10）下 2 个 SKU——SKU-A1023（product_id=1023）与
    SKU-A1024（product_id=1024）——近 2 周退款异常聚集：退款率 ~45%（大盘基线 ~5.2%），
    原因分布畸变为「描述不符」占 ~75%（大盘仅 ~12%）。二者合计贡献近 2 周整体退款率
    上升约 6pp（对齐 PRD 示例：整体 ~11.6% vs 排除该两 SKU ~5.2%）。
    全期退款率 ≈ 3000/50000 ≈ 6%，与 DATA §8.1 对齐。

    脏数据：users(city NULL/非法等级)、orders(负金额/金额单位错位/超范围类目 999)、
    refund_applications(负退款额/非法状态)；两异常 SKU 的订单与退款豁免脏数据。
    """
    conn.execute("DROP SCHEMA IF EXISTS s2_refund CASCADE")
    conn.execute("CREATE SCHEMA s2_refund")
    for stmt in DDL_S2:
        conn.execute(stmt)

    # ---- 维度：用户 2000 ----
    user_rows: list[list] = []
    for uid in range(1, 2001):
        user_rows.append([
            uid,
            f"会员{uid:04d}",
            None if RNG.random() < 0.025 else RNG.choice(CITIES),
            TODAY - timedelta(days=RNG.randint(30, 1000)),
            RNG.choices(("new", "bronze", "silver", "gold"), weights=(0.2, 0.4, 0.3, 0.1))[0],
        ])

    # ---- 维度：退款原因 10 条（5 大类）----
    reason_rows = [
        [1, "商品质量问题", "质量"],
        [2, "商品破损/漏水", "质量"],
        [3, "物流太慢", "物流"],
        [4, "长时间未收到货", "物流"],
        [5, "与商品描述不符", "描述不符"],
        [6, "图片与实物不符", "描述不符"],
        [7, "价格比别处贵", "价格"],
        [8, "优惠活动未生效", "价格"],
        [9, "不想要了/冲动下单", "其他"],
        [10, "错拍/多拍", "其他"],
    ]
    # 基线原因权重：质量 25% / 物流 30% / 描述不符 12% / 价格 15% / 其他 18%
    baseline_reason = ((1, 0.13), (2, 0.12), (3, 0.15), (4, 0.15), (5, 0.06), (6, 0.06), (7, 0.08), (8, 0.07), (9, 0.09), (10, 0.09))
    # 剧本原因权重（异常 SKU 近 2 周）：描述不符 ~75%
    anomaly_reason = ((5, 0.45), (6, 0.30), (1, 0.08), (2, 0.07), (9, 0.05), (10, 0.05))

    # ---- 事实：订单 5 万（90 天）+ 退款申请约 3000 ----
    order_rows: list[list] = []
    refund_rows: list[list] = []
    protected_order_ids: set[int] = set()
    order_id = 100_000
    refund_id = 0
    base_per_day, extra = divmod(50_000, DAYS)
    for d in range(DAYS):
        day = START + timedelta(days=d)
        in_window = d >= DAYS - 14  # 剧本窗口：近 2 周
        for _ in range(base_per_day + (1 if d < extra else 0)):
            order_id += 1
            if RNG.random() < (0.16 if in_window else 0.10):
                pid = RNG.choice(S2_ANOMALY_PRODUCT_IDS)  # 热销护肤 SKU，近 2 周占比升高
            else:
                pid = RNG.randint(1, 2000)
                if pid in S2_ANOMALY_PRODUCT_IDS:
                    pid = 1025  # 非剧本路径绕开异常 SKU 编码
            category_id = S2_SKINCARE_CATEGORY_ID if pid in S2_ANOMALY_PRODUCT_IDS else (pid - 1) % 20 + 1
            refund_rate = (0.45 if in_window else 0.06) if pid in S2_ANOMALY_PRODUCT_IDS else 0.052
            refunded = RNG.random() < refund_rate
            status = "refunded" if refunded else RNG.choices(("paid", "closed"), weights=(0.85, 0.15))[0]
            pay = _money(RNG.uniform(39, 1999))
            order_rows.append([order_id, RNG.randint(1, 2000), pid, category_id, day, pay, status])
            if refunded:
                refund_id += 1
                if pid in S2_ANOMALY_PRODUCT_IDS and in_window:
                    reason_id = RNG.choices([i for i, _ in anomaly_reason], weights=[w for _, w in anomaly_reason])[0]
                    protected_order_ids.add(order_id)
                else:
                    reason_id = RNG.choices([i for i, _ in baseline_reason], weights=[w for _, w in baseline_reason])[0]
                apply_day = min(day + timedelta(days=RNG.randint(1, 10)), TODAY)
                refund_rows.append([
                    refund_id,
                    order_id,
                    reason_id,
                    _rand_ts(apply_day),
                    _money(float(pay) * RNG.uniform(0.5, 1.0)),
                    RNG.choices(("approved", "rejected", "processing"), weights=(0.70, 0.15, 0.15))[0],
                ])

    # ---- 脏数据 + 重复主键（异常 SKU 的订单/退款豁免）----
    n_dirty = [
        _dirty_pass(user_rows, _dirty_user_s2),
        _dirty_pass(order_rows, _dirty_order_s2, protect=lambda r: r[2] in S2_ANOMALY_PRODUCT_IDS),
        _dirty_pass(refund_rows, _dirty_refund, protect=lambda r: r[1] in protected_order_ids),
    ]
    n_dup = [
        _duplicate_pk_pass(order_rows, 0, 5),
        _duplicate_pk_pass(refund_rows, 0, 4),
    ]

    # ---- 灌数 ----
    insert_batches(conn, "INSERT INTO s2_refund.users VALUES (?, ?, ?, ?, ?)", user_rows)
    insert_batches(conn, "INSERT INTO s2_refund.refund_reasons VALUES (?, ?, ?)", reason_rows)
    insert_batches(conn, "INSERT INTO s2_refund.orders VALUES (?, ?, ?, ?, ?, ?, ?)", order_rows)
    insert_batches(conn, "INSERT INTO s2_refund.refund_applications VALUES (?, ?, ?, ?, ?, ?)", refund_rows)
    print(f"[s2_refund] users={len(user_rows)} orders={len(order_rows)} refund_reasons={len(reason_rows)} "
          f"refund_applications={len(refund_rows)}（退款率≈{len(refund_rows) / len(order_rows) * 100:.1f}%）"
          f"(脏 {sum(n_dirty)} 行, 重复主键丢弃 {sum(n_dup)} 行)")


# ---------------------------------------------------------------------------
# s3_behavior —— 客户行为分析
# ---------------------------------------------------------------------------
S3_SOURCES = ("direct", "push", "ads", "share")
S3_FILLER_PAGES = ("home", "search", "detail", "cart")
S3_CHECKOUT_DAILY = {"ios": 150, "android": 150, "pc": 100}
S3_BASE_CONV = 0.75          # checkout → order 基线转化率
S3_ANDROID_ANOM_CONV = 0.20  # 剧本：android 近 3 周转化率


def seed_s3_behavior(conn: duckdb.DuckDBPyConnection) -> None:
    """【归因剧本·s3_behavior —— android 支付体验劣化】

    预期归因答案：android 端 checkout 页近 3 周下单转化率仅 ~20%，显著低于 ios/pc 的 ~75%
    （即 android checkout 流失率 ~80% vs ios/pc ~25%）——支付链路体验劣化剧本。
    事件级口径（order_events/visit_events where page='checkout' 按设备分组）与 user 级口径
    （checkout 访问者当日内下单，经 user_id + event_time JOIN device）双路径均可复现：
    每笔下单归因到当日同设备的真实 checkout 访问者，下单时间晚于其 checkout 1~90 分钟。
    窗口外三端转化率一致（~75%）。漏斗表行数比 100:20:12.5，device 为用户稳定属性。

    脏数据：visit_events(source NULL/非法页面/未来时间，近 3 周 checkout 行豁免)、
    cart_events(负数量)、order_events(负金额/单位错位，金额不参与流失率口径)。
    """
    conn.execute("DROP SCHEMA IF EXISTS s3_behavior CASCADE")
    conn.execute("CREATE SCHEMA s3_behavior")
    for stmt in DDL_S3:
        conn.execute(stmt)

    # ---- 维度：用户 2000（device 为用户稳定属性，供群体对比）----
    user_rows: list[list] = []
    device_of: dict[int, str] = {}
    pools: dict[str, list[int]] = {"ios": [], "android": [], "pc": []}
    for uid in range(1, 2001):
        reg = TODAY - timedelta(days=RNG.randint(0, 400))
        channel = RNG.choices(("organic", "ads", "social", "referral"), weights=(0.40, 0.25, 0.20, 0.15))[0]
        user_rows.append([uid, reg, channel, 1 if reg >= TODAY - timedelta(days=30) else 0])
        device = RNG.choices(("ios", "android", "pc"), weights=(0.35, 0.40, 0.25))[0]
        device_of[uid] = device
        pools[device].append(uid)

    # ---- 事实：visit 20 万 / cart 4 万 / order ~2.5 万 ----
    visit_rows: list[list] = []
    cart_rows: list[list] = []
    order_rows: list[list] = []
    event_id = 0
    total_visits = 200_000
    per_day, extra = divmod(total_visits, DAYS)
    # 每日每设备的 checkout 访问者池 (user_id, event_time)——下单事件从池内归因抽取，
    # 保证"checkout 访问者当日内下单"的 user 级漏斗与事件级漏斗口径一致，剧本双路径可查。
    checkout_pools: list[dict[str, list[tuple[int, datetime]]]] = []
    anom_since = TODAY - timedelta(days=20)  # 近 3 周窗口（含当日）
    for d in range(DAYS):
        day = START + timedelta(days=d)
        # checkout 访问：按设备定向生成（带 ±8 抖动）
        checkout_today: dict[str, int] = {}
        pool_today: dict[str, list[tuple[int, datetime]]] = {}
        for dev, base_n in S3_CHECKOUT_DAILY.items():
            n = base_n + RNG.randint(-8, 8)
            checkout_today[dev] = n
            pool_today[dev] = []
            for _ in range(n):
                event_id += 1
                uid = RNG.choice(pools[dev])
                ts = _rand_ts(day)
                pool_today[dev].append((uid, ts))
                visit_rows.append([event_id, uid, ts, "checkout", dev,
                                   RNG.choice(S3_SOURCES) if RNG.random() < 0.8 else None])
        checkout_pools.append(pool_today)
        # 其余页面填充，凑满当日总行数
        filler = per_day + (1 if d < extra else 0) - sum(checkout_today.values())
        for _ in range(filler):
            event_id += 1
            uid = RNG.randint(1, 2000)
            page = RNG.choices(S3_FILLER_PAGES, weights=(30, 28, 24, 18))[0]
            visit_rows.append([
                event_id,
                uid,
                _rand_ts(day),
                page,
                device_of[uid],
                RNG.choice(S3_SOURCES) if RNG.random() < 0.8 else None,
            ])

    # 加购 4 万
    cart_per_day, cart_extra = divmod(40_000, DAYS)
    for d in range(DAYS):
        day = START + timedelta(days=d)
        for _ in range(cart_per_day + (1 if d < cart_extra else 0)):
            event_id += 1
            cart_rows.append([event_id, RNG.randint(1, 2000), _rand_ts(day), RNG.randint(1, 500), RNG.randint(1, 5)])

    # 下单 ~2.5 万：checkout × 设备转化率；android 近 3 周骤降（剧本）
    # 每笔下单从当日同设备的 checkout 访问者池中抽取用户，下单时间晚于其 checkout 1~90 分钟
    # （跨日则钳回当日 23:59），确保 o.event_time >= c.event_time 的 user 级漏斗 JOIN 成立。
    day_end = datetime(TODAY.year, TODAY.month, TODAY.day, 23, 59, 59)
    order_seq = 0
    for d in range(DAYS):
        day = START + timedelta(days=d)
        in_anom_window = day >= anom_since
        for dev in ("ios", "android", "pc"):
            conv = S3_ANDROID_ANOM_CONV if (dev == "android" and in_anom_window) else S3_BASE_CONV
            pool = checkout_pools[d][dev]
            n = min(len(pool), int(len(pool) * conv * RNG.uniform(0.92, 1.08)))
            for uid, ts in RNG.sample(pool, n):
                event_id += 1
                order_seq += 1
                ots = ts + timedelta(minutes=RNG.randint(1, 90))
                if ots.date() != day:  # 跨日钳回当日（仅运行日深夜可能触发）
                    ots = min(ots, day_end)
                order_rows.append([
                    event_id,
                    uid,
                    ots,
                    500_000 + order_seq,  # s3 独立 order_id 空间（与 s2.orders 区分）
                    RNG.randint(1, 500),
                    _money(RNG.uniform(29, 1999)),
                ])

    # ---- 脏数据 + 重复主键 ----
    n_dirty = [
        _dirty_pass(visit_rows, _dirty_visit_s3,
                    protect=lambda r: r[3] == "checkout" and r[2].date() >= anom_since),
        _dirty_pass(cart_rows, _dirty_cart_s3),
        _dirty_pass(order_rows, _dirty_order_s3),
    ]
    n_dup = [
        _duplicate_pk_pass(cart_rows, 0, 4),
        _duplicate_pk_pass(order_rows, 0, 5),
    ]

    # ---- 灌数 ----
    insert_batches(conn, "INSERT INTO s3_behavior.users VALUES (?, ?, ?, ?)", user_rows)
    insert_batches(conn, "INSERT INTO s3_behavior.visit_events VALUES (?, ?, ?, ?, ?, ?)", visit_rows)
    insert_batches(conn, "INSERT INTO s3_behavior.cart_events VALUES (?, ?, ?, ?, ?)", cart_rows)
    insert_batches(conn, "INSERT INTO s3_behavior.order_events VALUES (?, ?, ?, ?, ?, ?)", order_rows)
    print(f"[s3_behavior] users={len(user_rows)} visit_events={len(visit_rows)} cart_events={len(cart_rows)} "
          f"order_events={len(order_rows)} (脏 {sum(n_dirty)} 行, 重复主键丢弃 {sum(n_dup)} 行)")


# ---------------------------------------------------------------------------
# s4_inventory —— 库存异常分析
# ---------------------------------------------------------------------------
S4_SKU_COUNT = 100
S4_WAREHOUSES = (1, 2, 3)
# 剧本固定：5 个 SKU 账实不符（调拨漏记）—— sku -> 仓
S4_ANOMALY_TARGETS: dict[int, int] = {7: 1, 23: 2, 41: 3, 66: 1, 89: 2}


def seed_s4_inventory(conn: duckdb.DuckDBPyConnection) -> None:
    """【归因剧本·s4_inventory —— transfer 漏记账实不符】

    预期归因答案：SKU 7（1 号仓）、SKU 23（2 号仓）、SKU 41（3 号仓）、SKU 66（1 号仓）、
    SKU 89（2 号仓）共 5 个 (SKU, 仓) 组合存在"期初 + 入库 − 出库 ≠ 期末"：每个约 8 个
    快照日被注入 ±30~80 的账实缺口（物理调拨已发生但 transfer 流水漏记），
    90 天累计缺口数百件；其余 SKU 账实链严格自洽（Σ(期末−期初) = Σ入库 − Σ出库）。
    可由 SQL 按 (product_id, warehouse_id) 核对公式圈定，再看出入库 biz_type 分布定位。

    脏数据：sales(负销量/负金额/金额单位错位，不参与账实核对)、出入库流水(非法 biz_type
    枚举，不改变数量)。inventory 快照刻意不注入脏值，保证账实核对链纯净（见模块头部策略④）。
    """
    conn.execute("DROP SCHEMA IF EXISTS s4_inventory CASCADE")
    conn.execute("CREATE SCHEMA s4_inventory")
    for stmt in DDL_S4:
        conn.execute(stmt)

    unit_price = {sku: round(RNG.uniform(15, 300), 2) for sku in range(1, S4_SKU_COUNT + 1)}
    stock: dict[tuple[int, int], int] = {}
    anomaly_days: dict[tuple[int, int], set[int]] = {}
    for sku, wh in S4_ANOMALY_TARGETS.items():
        anomaly_days[(sku, wh)] = set(RNG.sample(range(DAYS), 8))  # 每个异常组合 8 个漏记日
    for sku in range(1, S4_SKU_COUNT + 1):
        for wh in S4_WAREHOUSES:
            stock[(sku, wh)] = RNG.randint(250, 650)

    inv_rows: list[list] = []
    inbound_rows: list[list] = []
    outbound_rows: list[list] = []
    sales_rows: list[list] = []
    inbound_id = outbound_id = sale_id = 0

    for d in range(DAYS):
        day = START + timedelta(days=d)
        # 阶段一：生成当日全部业务事件（调拨双边同日成对登记，保证除剧本外账实自洽）
        day_in: dict[tuple[int, int], int] = defaultdict(int)
        day_out: dict[tuple[int, int], int] = defaultdict(int)
        for sku in range(1, S4_SKU_COUNT + 1):
            for wh in S4_WAREHOUSES:
                key = (sku, wh)
                begin = stock[key]
                if RNG.random() < 0.38:  # 销售出库（同步记销量表）
                    q = RNG.randint(1, 9)
                    sale_id += 1
                    sales_rows.append([sale_id, sku, wh, day, q, _money(q * unit_price[sku] * RNG.uniform(0.9, 1.1))])
                    outbound_id += 1
                    outbound_rows.append([outbound_id, sku, wh, day, q, "sale"])
                    day_out[key] += q
                if RNG.random() < 0.004:  # 报损出库
                    q = RNG.randint(1, 5)
                    outbound_id += 1
                    outbound_rows.append([outbound_id, sku, wh, day, q, "scrap"])
                    day_out[key] += q
                if RNG.random() < 0.04:  # 常规仓间调拨（双边成对记账）
                    q = RNG.randint(10, 40)
                    dest = RNG.choice([w for w in S4_WAREHOUSES if w != wh])
                    outbound_id += 1
                    outbound_rows.append([outbound_id, sku, wh, day, q, "transfer_out"])
                    day_out[key] += q
                    inbound_id += 1
                    inbound_rows.append([inbound_id, sku, dest, day, q, "transfer_in"])
                    day_in[(sku, dest)] += q
                if begin < 250:  # 低库存强制采购补货（保证数量不穿底，见下方期末非负证明）
                    q = 400 - begin + RNG.randint(0, 50)
                    inbound_id += 1
                    inbound_rows.append([inbound_id, sku, wh, day, q, "purchase"])
                    day_in[key] += q
                elif begin > 850 and RNG.random() < 0.5:  # 高库存强制调拨分流
                    q = RNG.randint(50, 120)
                    dest = RNG.choice([w for w in S4_WAREHOUSES if w != wh])
                    outbound_id += 1
                    outbound_rows.append([outbound_id, sku, wh, day, q, "transfer_out"])
                    day_out[key] += q
                    inbound_id += 1
                    inbound_rows.append([inbound_id, sku, dest, day, q, "transfer_in"])
                    day_in[(sku, dest)] += q
                elif RNG.random() < 0.26:  # 日常采购入库
                    q = RNG.randint(12, 40)
                    inbound_id += 1
                    inbound_rows.append([inbound_id, sku, wh, day, q, "purchase"])
                    day_in[key] += q
                if RNG.random() < 0.05:  # 退货入库
                    q = RNG.randint(1, 15)
                    inbound_id += 1
                    inbound_rows.append([inbound_id, sku, wh, day, q, "return"])
                    day_in[key] += q
        # 阶段二：按事件结转日快照（期末 = 期初 + 入库 − 出库；剧本 SKU 注入账实缺口）
        # 期末非负证明（保证账实链自洽，禁止 max(end,0) 钳位——钳位会制造额外"账实不符"噪声）：
        #   begin ≥ 250 时，单日出库上限 = 销售9 + 报损5 + 常规调拨40 + 高库存调拨120 = 174
        #   （高库存调拨分支要求 begin > 850，期末 ≥ 676）→ 期末 ≥ 250 − 54 = 196 ≥ 0；
        #   begin < 250 时走强制补货分支，期末 ≥ 400 − 54 > 0。剧本缺口 ±80 后仍 > 0。
        for sku in range(1, S4_SKU_COUNT + 1):
            for wh in S4_WAREHOUSES:
                key = (sku, wh)
                begin = stock[key]
                end = begin + day_in[key] - day_out[key]
                if d in anomaly_days.get(key, ()):
                    end += RNG.choice((-1, 1)) * RNG.randint(30, 80)  # 调拨漏记 → 账实不符
                assert end >= 0, f"库存穿底（{key} 第{d}天），补货阈值需上调"
                inv_rows.append([day, sku, wh, begin, end])
                stock[key] = end

    # ---- 脏数据 + 重复主键（快照表不注入，保账实链纯净）----
    n_dirty = [
        _dirty_pass(sales_rows, _dirty_sale_s4),
        _dirty_pass(inbound_rows, _dirty_ledger_biztype, rate=0.015),
        _dirty_pass(outbound_rows, _dirty_ledger_biztype, rate=0.015),
    ]
    n_dup = [
        _duplicate_pk_pass(inbound_rows, 0, 4),
        _duplicate_pk_pass(outbound_rows, 0, 4),
        _duplicate_pk_pass(sales_rows, 0, 4),
    ]

    # ---- 灌数 ----
    insert_batches(conn, "INSERT INTO s4_inventory.inventory VALUES (?, ?, ?, ?, ?)", inv_rows)
    insert_batches(conn, "INSERT INTO s4_inventory.inbound_orders VALUES (?, ?, ?, ?, ?, ?)", inbound_rows)
    insert_batches(conn, "INSERT INTO s4_inventory.outbound_orders VALUES (?, ?, ?, ?, ?, ?)", outbound_rows)
    insert_batches(conn, "INSERT INTO s4_inventory.sales VALUES (?, ?, ?, ?, ?, ?)", sales_rows)
    print(f"[s4_inventory] inventory={len(inv_rows)} inbound_orders={len(inbound_rows)} "
          f"outbound_orders={len(outbound_rows)} sales={len(sales_rows)} "
          f"(脏 {sum(n_dirty)} 行, 重复主键丢弃 {sum(n_dup)} 行)")


# ---------------------------------------------------------------------------
# main：幂等入口 + 行数统计摘要
# ---------------------------------------------------------------------------
def _print_summary(conn: duckdb.DuckDBPyConnection) -> None:
    print("========== 灌数完成：各场景行数统计 ==========")
    for schema, tables in TABLE_REGISTRY.items():
        parts = []
        for t in tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {schema}.{t}").fetchone()[0]
            parts.append(f"{t}={n}")
        print(f"{schema}: {', '.join(parts)}")


def main(db_path: str = "./data/analytics/analytics.duckdb") -> None:
    """幂等入口：建父目录 → 连接（文件不存在则创建）→ 4 场景逐个 DROP 重建灌数 → 打印摘要。"""
    RNG.seed(SEED)  # 重置随机流：同进程内重复调用 main 也生成完全一致的数据
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    try:
        for fn in (seed_s1_catalog, seed_s2_refund, seed_s3_behavior, seed_s4_inventory):
            fn(conn)
        _print_summary(conn)
    finally:
        conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EcoGain DuckDB 分析库建库灌数（幂等：DROP SCHEMA 后重建）")
    parser.add_argument(
        "--db-path",
        default="./data/analytics/analytics.duckdb",
        help="DuckDB 库文件路径（默认 ./data/analytics/analytics.duckdb）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(args.db_path)
