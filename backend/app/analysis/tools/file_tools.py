"""file_read / file_write 工具（AGENT-4）：目录白名单内读写。"""
from __future__ import annotations

from pathlib import Path

from app.analysis.state import AnalysisState
from app.core.env import get_env
from app.core.logging import get_logger
from app.core.security import safe_path

log = get_logger(__name__)

READ_LIMIT = 1024 * 1024  # 1MB
WORKSPACE_QUOTA = 50 * 1024 * 1024  # 会话工作区用量上限

READ_DESC = "读取会话内文件（上传附件或工作区中间产物）。仅限当前会话目录。"
WRITE_DESC = "向当前会话工作区写入文本文件（分析中间产物，如整理后的笔记）。仅限 workspace 目录。"

READ_SCHEMA = {
    "type": "function",
    "function": {
        "name": "file_read",
        "description": READ_DESC,
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "相对会话目录的路径"}},
            "required": ["path"],
        },
    },
}

WRITE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "file_write",
        "description": WRITE_DESC,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对 workspace 的路径"},
                "content": {"type": "string", "description": "文本内容"},
            },
            "required": ["path", "content"],
        },
    },
}


async def file_read_tool(state: AnalysisState, path: str) -> str:
    target = safe_path(state["user_id"], state["conversation_id"], path,
                       roots=("uploads", "workspace"))
    if target is None or not target.is_file():
        return "[50002] 路径越权或文件不存在"
    data = target.read_bytes()
    truncated = len(data) > READ_LIMIT
    text = data[:READ_LIMIT].decode("utf-8", errors="replace")
    return text + ("\n...（文件超出 1MB 已截断）" if truncated else "")


async def file_write_tool(state: AnalysisState, path: str, content: str) -> str:
    target = safe_path(state["user_id"], state["conversation_id"], path, roots=("workspace",))
    if target is None:
        return "[50002] 路径越权：仅允许写入本会话 workspace 目录"
    # 会话用量检查（workspace 目录 ≤50MB）
    ws_root = Path(get_env().data_dir) / "workspace" / str(state["user_id"]) / str(state["conversation_id"])
    used = sum(f.stat().st_size for f in ws_root.rglob("*") if f.is_file()) if ws_root.exists() else 0
    if used + len(content.encode("utf-8")) > WORKSPACE_QUOTA:
        return "[50002] 会话工作区空间超限（≤50MB）"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"已写入 {path}（{len(content)} 字符）"
