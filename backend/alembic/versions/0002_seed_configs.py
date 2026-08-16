"""0002 seed configs：system_configs 14 项默认值（DATA §6.5）

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (config_key, 组, 默认值, 说明) —— 与 DATA §6.5 逐行对齐
CONFIG_SEED = [
    ("llm.provider", "llm", "zhipu", "LLM 供应商标识"),
    ("llm.base_url", "llm", "https://open.bigmodel.cn/api/paas/v4", "LLM OpenAI 协议网关地址"),
    ("llm.model", "llm", "glm-4.6", "模型名"),
    ("llm.api_key_ref", "llm", "LLM_API_KEY", "密钥环境变量引用名（不明文存 key）"),
    ("llm.temperature", "llm", "0.2", "采样温度 0~1"),
    ("agent.max_tool_rounds", "agent", "15", "工具轮次上限 5~50"),
    ("agent.task_timeout_seconds", "agent", "120", "任务超时 30~600s"),
    ("agent.context_rounds", "agent", "20", "上下文保留轮数 5~100"),
    ("agent.context_token_budget", "agent", "8000", "上下文 token 预算 2000~100000"),
    ("agent.sql_row_limit", "agent", "1000", "SQL 返回行数上限 100~10000"),
    ("agent.sql_timeout_seconds", "agent", "10", "SQL 超时 1~60s"),
    ("datasource.duckdb_path", "datasource", "/data/analytics/analytics.duckdb", "DuckDB 库文件路径"),
    ("feature.attachment_enabled", "feature", "true", "附件功能开关"),
    ("feature.export_enabled", "feature", "true", "导出功能开关"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for key, group, value, desc in CONFIG_SEED:
        exists = conn.execute(
            sa.text("SELECT id FROM system_configs WHERE config_key = :k"), {"k": key}
        ).scalar_one_or_none()
        if exists is None:
            conn.execute(
                sa.text(
                    "INSERT INTO system_configs (config_key, config_value, config_group, description) "
                    "VALUES (:k, :v, :g, :d)"
                ),
                {"k": key, "v": value, "g": group, "d": desc},
            )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM system_configs WHERE config_key IN :keys"),
        {"keys": tuple(k for k, *_ in CONFIG_SEED)},
    )
