"""上下文拼装（AGENT-2）：五段式 initial state 构建。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.analysis.state import AnalysisState
from app.core.config import get_config
from app.core.logging import TraceCtx
from app.db.duckdb import get_duckdb
from app.db.mysql import new_session
from app.models import AnalysisTask, Attachment
from app.seeds.init_analytics import SCENARIO_DATA_DICTIONARY

AGENT_SYSTEM_PROMPT = """你是一位资深经营数据分析师，帮助业务用户完成经营归因分析。

## 工作方式
1. 先理解问题，规划需要哪些数据（planning）；
2. 用 sql_query 工具查询 DuckDB 分析库取证（querying）——一次只写一条 SQL，根据结果迭代；
3. 需要时用 text_search / file_read 检索会话内文本资料与附件；
4. 证据充分后归纳结论（summarizing）。

## 数据环境
- DuckDB 分析库内置 4 个业务场景 schema（见最后的【数据字典】）；
- 用户上传的 csv/xlsx 附件已导入 attachments schema（见【本轮附件】清单）；
- SQL 仅允许 SELECT/WITH/SHOW/DESCRIBE 单条查询，注意处理脏数据（NULL/重复/超范围）。

## 证据规范
- 每条结论至少一条带数值的证据支撑，标注置信度（high/medium/low）；
- 数据不足以归因时，如实说明缺什么数据（对应"待补充数据"段），不要编造。

## 输出契约
分析收敛后，系统会要求你输出六段结构化结果（问题定义/关键指标/证据列表/归因结论/待补充数据/下一步建议）。"""


def _attachment_table_schema(table: str) -> dict:
    """读 attachments.{table} 的列结构（LLM 写 SQL 需要）。"""
    duck = get_duckdb()
    try:
        rel = duck._conn.sql(  # noqa: SLF001 —— 只读元数据
            f'SELECT * FROM attachments."{table}" LIMIT 0'
        )
        count = duck._conn.sql(  # noqa: SLF001
            f'SELECT COUNT(*) FROM attachments."{table}"'
        ).fetchone()[0]
        return {
            "table": f'attachments."{table}"',
            "columns": [{"name": c, "type": str(rel.types[i])} for i, c in enumerate(rel.columns)],
            "row_count": int(count),
        }
    except Exception:  # noqa: BLE001 —— 元数据读取失败降级为空
        return {"table": f'attachments."{table}"', "columns": [], "row_count": 0}


def _text_preview(att: Attachment, uid: int, cid: int) -> dict:
    from pathlib import Path

    from app.core.env import get_env

    preview = ""
    cache = (Path(get_env().data_dir) / "workspace" / str(uid) / str(cid)
             / f"attachment_text_{att.id}.txt")
    try:
        preview = cache.read_text(encoding="utf-8")[:300]
    except OSError:
        pass
    return {"file_name": att.file_name, "preview": preview}


async def load_ready_attachments(task: AnalysisTask) -> tuple[list[dict], list[dict]]:
    """结构化附件 → (schema 描述, 文本附件预览)。"""
    ids = [int(x) for x in (task.attachment_ids or "").split(",") if x.strip()]
    if not ids:
        return [], []
    async with new_session() as session:
        from sqlalchemy import select

        rows = await session.execute(
            select(Attachment).where(Attachment.id.in_(ids),
                                     Attachment.conversation_id == task.conversation_id)
        )
        atts = [a for a in rows.scalars().all() if a.parse_status == "ready"]
    struct_schemas, text_atts = [], []
    for att in atts:
        if att.duckdb_table:
            struct_schemas.append(_attachment_table_schema(att.duckdb_table))
        elif att.file_type in ("txt", "md"):
            text_atts.append(_text_preview(att, task.user_id, task.conversation_id))
    return struct_schemas, text_atts


async def build_initial_state(task: AnalysisTask) -> AnalysisState:
    """五段拼装（SPEC 4.6）：system prompt → 会话摘要 → 近 N 轮 → 本轮输入+附件 → 数据源说明。"""
    from app.services import summary_service

    cfg = get_config()
    msgs: list = [SystemMessage(content=AGENT_SYSTEM_PROMPT)]

    async with new_session() as session:
        # 会话摘要（CTX）
        from sqlalchemy import select

        from app.models import ContextSummary

        summaries = await session.execute(
            select(ContextSummary).where(ContextSummary.conversation_id == task.conversation_id)
            .order_by(ContextSummary.start_seq_no.asc())
        )
        for s in summaries.scalars().all():
            msgs.append(SystemMessage(content=f"[历史摘要] {s.summary_text}"))
        # 近 N 轮原始消息（降级路径：无摘要时截断最旧）
        effective = await summary_service.get_effective_context(session, task.conversation_id)
    recent = effective[-(cfg.context_rounds * 2):]  # user+assistant 各一条为一轮
    for m in recent:
        if m.role == "user":
            msgs.append(HumanMessage(content=m.content[:4000]))
        elif m.role == "assistant" and m.message_type == "text":
            msgs.append(AIMessage(content=m.content[:4000]))

    # 本轮输入：问题 + 附件清单
    struct_atts, text_atts = await load_ready_attachments(task)
    att_lines = []
    for a in struct_atts:
        cols = ", ".join(f"{c['name']}:{c['type']}" for c in a["columns"])
        att_lines.append(f"- 结构化附件 {a['table']}（{a['row_count']} 行）：{cols}")
    for t in text_atts:
        att_lines.append(f"- 文本附件 {t['file_name']}：{t['preview']}")
    human = task.input_text + ("\n\n[本轮附件]\n" + "\n".join(att_lines) if att_lines else "")
    msgs.append(HumanMessage(content=human))

    # 数据源说明（静态字典）
    msgs.append(SystemMessage(content=f"【数据字典】\n{SCENARIO_DATA_DICTIONARY}"))

    return AnalysisState(
        messages=msgs,
        task_id=task.id,
        conversation_id=task.conversation_id,
        user_id=task.user_id,
        trace_id=task.trace_id or TraceCtx.current_trace_id(),
        attachment_schemas=struct_atts,
        text_attachments=text_atts,
        tool_rounds=0,
        final_result=None,
    )
