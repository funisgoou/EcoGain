"""generate_result_file 工具（AGENT-6）：结果文件显式生成出口（幂等）。"""
from __future__ import annotations

from app.analysis.state import AnalysisState
from app.core.logging import get_logger
from app.services.result_service import render_markdown

log = get_logger(__name__)

GEN_DESC = "生成/刷新本轮分析的结果 Markdown 文件。正常链路系统已自动生成；仅在需要显式确认时调用。"

GEN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_result_file",
        "description": GEN_DESC,
        "parameters": {"type": "object", "properties": {}},
    },
}


async def generate_result_file_tool(state: AnalysisState) -> str:
    from app.db.mysql import new_session
    from app.models import AnalysisResult
    from sqlalchemy import text as sa_text

    r = state.get("final_result")
    if r is None:
        return "[40001] 结果尚未生成"
    async with new_session() as session:
        row = (await session.execute(
            sa_text("SELECT id FROM analysis_results WHERE task_id = :t"), {"t": state["task_id"]}
        )).scalar_one_or_none()
        if row is None:
            return "[40001] 结果尚未落库"
        # 已有结果：文件渲染幂等，导出兜底在 execute_analysis 的 ensure_export_file 完成
    md = render_markdown(r, state["task_id"])
    return f"结果文件已就绪（{len(md)} 字符），下载入口：/api/results/{state['task_id']}/download"
