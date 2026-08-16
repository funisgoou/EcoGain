"""上下文摘要（CTX-1 触发判断 / CTX-2 区间压缩与降级）。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.logging import get_logger
from app.db.mysql import new_session
from app.models import ContextSummary, Message
from app.services import task_service

log = get_logger(__name__)

SUMMARY_PROMPT = """你是一个经营分析会话的摘要助手。请把下面这段多轮对话压缩为一段简洁的要点摘要，
保留：分析的问题、已确认的关键结论（含数值）、使用过的数据口径、尚未解决的追问。
直接输出摘要正文，不要任何前后缀。

{messages}"""


async def check_compaction_needed(session: AsyncSession, conversation_id: int) -> bool:
    """CTX-1：轮数 > context_rounds 或拼装上下文估算 token（字符数/3）超预算。"""
    rounds = (
        await session.execute(
            select(func.count()).select_from(Message).where(
                Message.conversation_id == conversation_id, Message.role == "user"
            )
        )
    ).scalar_one()
    if rounds > get_config().context_rounds:
        return True
    msgs = await get_effective_context(session, conversation_id)
    est_tokens = sum(len(m.content) for m in msgs) // 3
    return est_tokens > get_config().context_token_budget


async def summarize_range(session: AsyncSession, conversation_id: int) -> None:
    """CTX-2：取未被摘要覆盖的最早连续区间（≤10 轮）→ LLM 压缩 → 写 context_summaries。
    失败降级：不写摘要，后续拼装时直接截断最旧消息（get_effective_context 侧处理）。"""
    from app.services.llm_gateway import llm

    covered = (
        await session.execute(
            select(ContextSummary.start_seq_no, ContextSummary.end_seq_no).where(
                ContextSummary.conversation_id == conversation_id
            )
        )
    ).all()
    covered_set: set[int] = set()
    for start, end in covered:
        covered_set.update(range(start, end + 1))
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.role.in_(("user", "assistant")))
        .order_by(Message.seq_no.asc())
    )
    candidates = [m for m in result.scalars().all() if m.seq_no not in covered_set]
    if not candidates:
        return
    batch = candidates[:20]  # ≤10 轮（user+assistant 各一条为一轮）
    lines = [f"[{m.role}] {m.content[:2000]}" for m in batch]
    try:
        text = await llm.complete(SUMMARY_PROMPT.format(messages="\n".join(lines)))
        async with new_session() as s2, s2.begin():
            s2.add(ContextSummary(
                conversation_id=conversation_id,
                start_seq_no=batch[0].seq_no,
                end_seq_no=batch[-1].seq_no,
                summary_text=text,
            ))
        log.info("context_summarized", conversation_id=conversation_id,
                 start=batch[0].seq_no, end=batch[-1].seq_no)
    except Exception as e:  # noqa: BLE001 —— PRD F8-R5 降级路径
        log.warning("summary_failed_degraded", conversation_id=conversation_id, error=str(e))


async def get_effective_context(session: AsyncSession, conversation_id: int) -> list[Message]:
    """拼装视角的"有效消息"= 未被任何摘要覆盖的消息（seq_no 升序）。"""
    covered = (
        await session.execute(
            select(ContextSummary.start_seq_no, ContextSummary.end_seq_no).where(
                ContextSummary.conversation_id == conversation_id
            )
        )
    ).all()
    covered_set: set[int] = set()
    for start, end in covered:
        covered_set.update(range(start, end + 1))
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.seq_no.notin_(covered_set))
        .order_by(Message.seq_no.asc())
    )
    return list(result.scalars().all())
