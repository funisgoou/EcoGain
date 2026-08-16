"""text_search 工具（AGENT-5）：会话内文本附件与工作区文件的关键词检索。"""
from __future__ import annotations

from pathlib import Path

from app.analysis.state import AnalysisState
from app.core.env import get_env

SEARCH_DESC = "在会话内的文本资料（txt/md 附件与工作区文件）中做关键词检索，返回文件名/行号/上下文片段。"

SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "text_search",
        "description": SEARCH_DESC,
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "检索关键词（大小写不敏感）"}
            },
            "required": ["keyword"],
        },
    },
}

MAX_HITS_PER_FILE = 50
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
SEARCH_DEPTH = 2  # workspace 子目录深度


async def text_search_tool(state: AnalysisState, keyword: str) -> str:
    if not keyword.strip():
        return "关键词为空"
    ws_root = Path(get_env().data_dir) / "workspace" / str(state["user_id"]) / str(state["conversation_id"])
    files: list[Path] = []
    if ws_root.exists():
        files = [f for f in ws_root.rglob("*") if f.is_file()
                 and f.suffix.lower() in (".txt", ".md") and f.stat().st_size <= MAX_FILE_SIZE]
        # 深度限制（rglob 全量后过滤，POC 规模可接受）
        files = [f for f in files if len(f.relative_to(ws_root).parts) <= SEARCH_DEPTH + 1]
    hits = []
    kw = keyword.lower()
    for f in files:
        file_hits = 0
        try:
            for line_no, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                pos = line.lower().find(kw)
                if pos >= 0:
                    snippet = line[max(0, pos - 120):pos + 120].strip()
                    hits.append(f"{f.name}:{line_no}: {snippet}")
                    file_hits += 1
                    if file_hits >= MAX_HITS_PER_FILE:
                        break
        except OSError:
            continue
    if not hits:
        return "未检索到匹配内容"
    return "\n".join(hits[:200])
