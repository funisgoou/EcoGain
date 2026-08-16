"""0001 initial：系统库 10 表（DATA §3 DDL 基线）

Revision ID: 0001
Revises:
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import JSON, MEDIUMTEXT

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("external_user_id", sa.String(64), nullable=False,
                  comment="认证中心用户唯一标识（auth_users.id）"),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("role", sa.String(16), nullable=False, server_default="analyst",
                  comment="analyst | admin"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active",
                  comment="active | disabled"),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.Column("updated_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_user_id", name="uk_external_user_id"),
        sa.Index("idx_username", "username"),
        comment="平台用户（登录回调时 upsert）",
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default="新分析"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("next_seq_no", sa.Integer(), nullable=False, server_default="0",
                  comment="消息序号分配计数器（实现扩展）"),
        sa.Column("last_message_at", sa.DateTime(3), nullable=True),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.Column("updated_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_user_status_last", "user_id", "status", "last_message_at"),
        comment="分析会话",
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, comment="user | assistant | tool"),
        sa.Column("message_type", sa.String(16), nullable=False,
                  comment="text | tool_call | result"),
        sa.Column("content", MEDIUMTEXT(), nullable=False,
                  comment="正文；tool_call 存参数/结果摘要"),
        sa.Column("tool_name", sa.String(64), nullable=True),
        sa.Column("tool_status", sa.String(16), nullable=True,
                  comment="running | success | failed（仅 tool_call 消息）"),
        sa.Column("task_id", sa.BigInteger(), nullable=True,
                  comment="产生本条消息的任务（assistant/tool 消息回溯）"),
        sa.Column("seq_no", sa.Integer(), nullable=False, comment="会话内单调递增"),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "seq_no", name="uk_conv_seq"),
        sa.Index("idx_conv_created", "conversation_id", "created_at"),
        sa.Index("idx_task", "task_id"),
        comment="会话消息",
    )
    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True, comment="关联的用户消息（发送时回填）"),
        sa.Column("file_name", sa.String(255), nullable=False, comment="规范化后文件名"),
        sa.Column("file_path", sa.String(512), nullable=False, comment="相对 uploads 根的路径"),
        sa.Column("file_type", sa.String(16), nullable=False, comment="csv | xlsx | txt | md"),
        sa.Column("file_size", sa.BigInteger(), nullable=False, comment="字节"),
        sa.Column("parse_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("duckdb_table", sa.String(128), nullable=True,
                  comment="csv/xlsx 导入 DuckDB 后的表名 attachment_data_{id}"),
        sa.Column("error_message", sa.String(1024), nullable=True, comment="解析失败原因"),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_conv", "conversation_id"),
        sa.Index("idx_msg", "message_id"),
        comment="会话附件",
    )
    op.create_table(
        "analysis_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("attachment_ids", sa.String(1024), nullable=True,
                  comment="本轮引用的附件 id 逗号分隔（实现扩展）"),
        sa.Column("task_status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("current_step", sa.String(64), nullable=True,
                  comment="planning | querying | summarizing"),
        sa.Column("trace_id", sa.String(32), nullable=True, comment="链路追踪（实现扩展）"),
        sa.Column("started_at", sa.DateTime(3), nullable=True),
        sa.Column("finished_at", sa.DateTime(3), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_conv", "conversation_id"),
        sa.Index("idx_status", "task_status"),
        sa.Index("idx_trace", "trace_id"),
        comment="分析任务（一条用户消息一个任务）",
    )
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("problem_definition", sa.Text(), nullable=False),
        sa.Column("key_metrics_json", JSON(), nullable=False, comment="数组，元素结构见 DATA §6.3"),
        sa.Column("evidence_list_json", JSON(), nullable=False),
        sa.Column("conclusion_text", sa.Text(), nullable=False),
        sa.Column("missing_data_text", sa.Text(), nullable=True),
        sa.Column("next_action_text", sa.Text(), nullable=False),
        sa.Column("result_markdown", MEDIUMTEXT(), nullable=False,
                  comment="完整 Markdown 渲染（复制/展示用）"),
        sa.Column("result_file_path", sa.String(512), nullable=True,
                  comment="exports 相对路径；未导出为 NULL"),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uk_task"),
        sa.Index("idx_conv", "conversation_id"),
        comment="六段结构化分析结果（一任务一行）",
    )
    op.create_table(
        "context_summaries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("start_seq_no", sa.Integer(), nullable=False, comment="覆盖消息区间起（含）"),
        sa.Column("end_seq_no", sa.Integer(), nullable=False, comment="覆盖消息区间止（含）"),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_conv", "conversation_id"),
        sa.Index("idx_conv_range", "conversation_id", "start_seq_no", "end_seq_no"),
        comment="历史消息 LLM 摘要（区间互不重叠）",
    )
    op.create_table(
        "websocket_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(3), nullable=False, comment="签发后 60 秒"),
        sa.Column("consumed_at", sa.DateTime(3), nullable=True, comment="一次性消费标记"),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uk_token"),
        sa.Index("idx_expires", "expires_at"),
        comment="WebSocket 建连一次性令牌",
    )
    op.create_table(
        "system_configs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("config_key", sa.String(128), nullable=False, comment="如 llm.model"),
        sa.Column("config_value", sa.Text(), nullable=True, comment="敏感项存 key 引用，不明文"),
        sa.Column("config_group", sa.String(32), nullable=False,
                  comment="llm | agent | datasource | feature"),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("config_key", name="uk_key"),
        sa.Index("idx_group", "config_group"),
        comment="系统配置（热更新）",
    )
    op.create_table(
        "task_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("log_level", sa.String(16), nullable=False, comment="info | warn | error"),
        sa.Column("log_type", sa.String(32), nullable=False,
                  comment="llm_call | tool_exec | status | summary"),
        sa.Column("log_content", sa.Text(), nullable=False, comment="≤2000 字"),
        sa.Column("created_at", sa.DateTime(3), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_task_created", "task_id", "created_at"),
        comment="任务运行日志",
    )


def downgrade() -> None:
    for table in ("task_logs", "system_configs", "websocket_tokens", "context_summaries",
                  "analysis_results", "analysis_tasks", "attachments", "messages",
                  "conversations", "users"):
        op.drop_table(table)
