"""六段结构化输出（AGENT-7）：结构化生成 + 强校验 + 一次重试。"""
from __future__ import annotations

from pydantic import ValidationError

from app.analysis.state import AnalysisState
from app.core.logging import get_logger
from app.schemas.common import BizError
from app.schemas.result import AnalysisResultModel
from app.services import task_service
from app.services.llm_gateway import lc_to_openai, llm

log = get_logger(__name__)

OUTPUT_INSTRUCTION = """基于以上分析过程，输出最终的结构化分析结果 JSON（仅输出 JSON，不要任何其他文字）：
{
  "problem_definition": "对用户问题的规范化定义（一段话）",
  "key_metrics": [
    {"metric_name": "指标名", "metric_value": 8.7, "metric_unit": "%",
     "metric_period": "统计口径，如 2026-08-09 ~ 2026-08-15（周同比）"}
  ],
  "evidence_list": [
    {"source_type": "sql", "source_name": "数据来源（表+聚合方式）",
     "evidence_text": "证据陈述（必须含数值）", "related_metric": "关联指标名",
     "confidence": "high"}
  ],
  "conclusion_text": "归因结论（多段文本，说清主因、贡献度、影响范围）",
  "missing_data_text": "缺什么数据导致无法进一步归因；没有则填 null",
  "next_actions": ["建议 1（可执行）", "建议 2（可执行）"]
}

硬性要求：key_metrics ≥1 条；evidence_list ≥1 条且 evidence_text 含具体数值；
confidence 只能是 high/medium/low；next_actions ≥2 条且可执行。"""


def validate_result(r: AnalysisResultModel) -> None:
    if len(r.key_metrics) < 1:
        raise ValueError("key_metrics 至少 1 条")
    if len(r.evidence_list) < 1:
        raise ValueError("evidence_list 至少 1 条")
    if len(r.next_actions) < 2:
        raise ValueError("next_actions 至少 2 条")
    # confidence 枚举已由 Pydantic Literal 保证


async def generate_structured_output(state: AnalysisState) -> AnalysisResultModel:
    """结构化生成 + 校验 + 一次重试（附错误说明）。"""
    messages = lc_to_openai(state["messages"])
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            result = await llm.structured_output(messages, AnalysisResultModel, OUTPUT_INSTRUCTION)
            validate_result(result)
            await task_service.log_record(state["task_id"], "info", "llm_call", "结构化输出校验通过")
            return result
        except (ValidationError, ValueError, BizError) as e:
            last_err = e
            if attempt == 2:
                break
            await task_service.log_record(
                state["task_id"], "warn", "llm_call",
                f"结构化输出第 {attempt} 次不合规：{str(e)[:200]}，重试",
            )
            messages = messages + [
                {"role": "assistant", "content": "(上次输出不合规)"},
                {"role": "system", "content": f"上次输出不合规：{e}。请严格按 schema 重新输出。"},
            ]
    raise BizError(50000, f"结构化输出不合规：{last_err}")
