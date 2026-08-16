"""六段结构化结果 DTO（API 文档 §6.2 / DATA §6.3）。

AnalysisResultModel 是 Agent 输出与落库的共享定义，analysis/output.py 从此处 import。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class KeyMetric(BaseModel):
    metric_name: str  # 指标名
    metric_value: float | str  # 数值（无法量化时为文本）
    metric_unit: str  # % | 单 | 元 | ...
    metric_period: str  # 统计口径，如 "2026-07-19 ~ 2026-07-25（周同比）"


class Evidence(BaseModel):
    source_type: Literal["sql", "file", "text"]
    source_name: str  # 如 "s2_refund.refund_applications 按 sku 聚合"
    evidence_text: str  # 证据陈述（含数值）
    related_metric: str  # 关联指标名
    confidence: Literal["high", "medium", "low"]


class AnalysisResultModel(BaseModel):
    problem_definition: str  # 六段-1
    key_metrics: list[KeyMetric] = Field(min_length=1)  # 六段-2
    evidence_list: list[Evidence] = Field(min_length=1)  # 六段-3
    conclusion_text: str  # 六段-4
    missing_data_text: str | None = None  # 六段-5
    next_actions: list[str] = Field(min_length=2)  # 六段-6


class ResultItem(BaseModel):
    """GET /api/results/{task_id} 响应 data。"""

    problem_definition: str
    key_metrics: list[KeyMetric]
    evidence_list: list[Evidence]
    conclusion_text: str
    missing_data_text: str | None
    next_action_text: str
    result_markdown: str
    exported: bool


@field_validator("key_metrics", "evidence_list", "next_actions", mode="before")
def _ensure_list(v):  # pragma: no cover —— 防御性兜底
    return v or []
