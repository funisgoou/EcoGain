"""结果业务（RES-1 落库 / RES-2 查询 / RES-4 幂等导出）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.env import get_env
from app.core.logging import get_logger
from app.db.mysql import new_session
from app.models import AnalysisResult, AnalysisTask
from app.schemas import ws as wsmsg
from app.schemas.common import BizError
from app.schemas.result import AnalysisResultModel
from app.services import message_service
from app.ws.manager import MANAGER

log = get_logger(__name__)

MARKDOWN_TEMPLATE = """# 经营归因分析报告

> 任务：{task_id} ｜ 生成时间：{created_at}

## 1. 问题定义
{problem_definition}

## 2. 关键指标
| 指标 | 数值 | 单位 | 统计口径 |
| --- | --- | --- | --- |
{metric_rows}

## 3. 证据列表
| 来源类型 | 来源 | 证据 | 关联指标 | 置信度 |
| --- | --- | --- | --- | --- |
{evidence_rows}

## 4. 归因结论
{conclusion_text}

## 5. 待补充数据
{missing_data_text}

## 6. 下一步建议
{next_action_lines}
"""


def render_markdown(r: AnalysisResultModel, task_id: int, created_at: datetime | None = None) -> str:
    """RES-1/4 共用渲染（DATA §6.3 模板）。"""
    metric_rows = "\n".join(
        f"| {m.metric_name} | {m.metric_value} | {m.metric_unit} | {m.metric_period} |"
        for m in r.key_metrics
    )
    evidence_rows = "\n".join(
        f"| {e.source_type} | {e.source_name} | {e.evidence_text} | {e.related_metric} | {e.confidence} |"
        for e in r.evidence_list
    )
    next_action_lines = "\n".join(
        f"{i + 1}. {a}" for i, a in enumerate(r.next_actions)
    )
    return MARKDOWN_TEMPLATE.format(
        task_id=task_id,
        created_at=(created_at or datetime.now()).isoformat(timespec="seconds"),
        problem_definition=r.problem_definition,
        metric_rows=metric_rows,
        evidence_rows=evidence_rows,
        conclusion_text=r.conclusion_text,
        missing_data_text=r.missing_data_text or "无",
        next_action_lines=next_action_lines,
    )


async def save_result(session: AsyncSession, task: AnalysisTask,
                      result: AnalysisResultModel) -> AnalysisResult:
    """RES-1：六段落库 + result 卡片消息 + result_ready 推送。"""
    row = AnalysisResult(
        task_id=task.id,
        conversation_id=task.conversation_id,
        problem_definition=result.problem_definition,
        key_metrics_json=[m.model_dump() for m in result.key_metrics],
        evidence_list_json=[e.model_dump() for e in result.evidence_list],
        conclusion_text=result.conclusion_text,
        missing_data_text=result.missing_data_text,
        next_action_text="\n".join(f"{i + 1}. {a}" for i, a in enumerate(result.next_actions)),
        result_markdown=render_markdown(result, task.id),
    )
    session.add(row)
    await session.flush()
    await message_service.append_message(
        session, task.conversation_id, "assistant", "result", f"result:{row.id}",
        task_id=task.id,
    )  # result 卡片消息
    cid, tid, rid = task.conversation_id, task.id, row.id
    await MANAGER.broadcast(cid, wsmsg.msg_result_ready(tid, rid))
    return row


async def get_by_task(session: AsyncSession, user_id: int, task_id: int) -> AnalysisResult:
    task = await session.get(AnalysisTask, task_id)
    if task is None:
        raise BizError(40401, "任务不存在")
    if task.user_id != user_id:
        raise BizError(40301, "无权访问该任务")
    row = (
        await session.execute(select(AnalysisResult).where(AnalysisResult.task_id == task_id))
    ).scalar_one_or_none()
    if row is None:
        raise BizError(40401, "任务未产生结果")
    return row


async def ensure_export_file(session: AsyncSession, user_id: int, task_id: int) -> Path:
    """RES-4 幂等导出：已有且文件在 → 直接返回；否则补渲染落盘（不经过 Agent）。"""
    row = await get_by_task(session, user_id, task_id)
    dest = (Path(get_env().data_dir) / "exports" / str(user_id)
            / str(row.conversation_id) / f"result_{task_id}.md")
    if not (row.result_file_path and dest.exists()):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(row.result_markdown, encoding="utf-8")  # 复用落库时渲染的 md
        async with new_session() as s2, s2.begin():
            await s2.execute(
                text("UPDATE analysis_results SET result_file_path = :p WHERE task_id = :t"),
                {"p": f"{user_id}/{row.conversation_id}/result_{task_id}.md", "t": task_id},
            )
        log.info("result_exported", task_id=task_id)
    return dest
