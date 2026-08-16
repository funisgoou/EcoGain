"""安全工具集（AGENT-3 SQL 校验 / AGENT-4 路径守卫 / ATT-1 文件名规范化 / ATT-3 列名规范化）。

两份 SQL 词表是安全约束的唯一定义点（与 SPEC 4.6 一致）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.env import get_env

# ---- SQL 白名单/黑名单（SPEC 4.6）----
SQL_ALLOWED_STARTERS = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC"}
SQL_BLACKLIST = {  # 词边界匹配、大小写不敏感
    "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE", "REPLACE",
    "GRANT", "REVOKE", "ATTACH", "DETACH", "COPY", "EXPORT", "IMPORT", "CALL", "PRAGMA",
    "INSTALL", "LOAD",
}


@dataclass
class SqlRejected:
    reason: str


def strip_sql_comments(sql: str) -> str:
    """去掉 /* 块注释 */ 与 -- 行注释，防止用注释绕过黑名单（如 DELE/**/TE）。"""
    s = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    s = re.sub(r"--[^\n]*", " ", s)
    return s


def validate_sql(sql: str) -> str | SqlRejected:
    """AGENT-3 核心闸门：注释剥离 → 分号检测（禁多语句）→ 首词白名单 → 黑名单词边界扫描。"""
    s = strip_sql_comments(sql).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return SqlRejected("SQL 语句为空")
    body = s.rstrip(";")
    if ";" in body:  # 仅允许最末一个分号
        return SqlRejected("检测到多条语句，仅允许单条查询")
    first = body.split(" ", 1)[0].upper()
    if first not in SQL_ALLOWED_STARTERS:
        return SqlRejected(f"仅允许 SELECT/WITH/SHOW/DESCRIBE 开头，当前：{first}")
    for word in SQL_BLACKLIST:
        if re.search(rf"\b{word}\b", body, re.IGNORECASE):
            return SqlRejected(f"语句包含被禁止的关键词：{word}")
    return body


def wrap_limit(sql: str, max_rows: int) -> str:
    """外层包裹 LIMIT；已带合规 LIMIT 的原样放行。"""
    if m := re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.IGNORECASE):
        if int(m.group(1)) <= max_rows:
            return sql
    return f"SELECT * FROM ({sql}) AS __limited__ LIMIT {max_rows}"


def safe_path(user_id: int, conversation_id: int, relative: str,
              roots: tuple[str, ...] = ("uploads", "workspace")) -> Path | None:
    """AGENT-4/ATT-7 路径守卫：join + resolve 后必须落在 root/{uid}/{cid}/ 前缀内。

    resolve 已消解 ../ 与符号链接；Windows 下 casefold 比较，防盘符大小写差异。
    """
    rel = str(relative).replace("\\", "/").lstrip("/")
    for root in roots:
        base = (Path(get_env().data_dir) / root / str(user_id) / str(conversation_id)).resolve()
        target = (base / rel).resolve()
        try:
            common = os.path.commonpath([str(base), str(target)])
        except ValueError:  # 不同盘符
            continue
        if common.casefold() == str(base).casefold():
            return target
    return None


def secure_filename(name: str) -> str:
    """ATT-1：去路径分隔符/../控制字符，空则给 file；保留中文与常见安全字符。"""
    name = name.replace("\\", "/").split("/")[-1]  # 只留文件名部分
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "", name)  # 控制符与 Windows 非法字符
    return name.strip(". ") or "file"  # 防 ".gitignore" 类陷阱兜底


def normalize_column_name(raw: str, index: int, used: set[str]) -> str:
    """ATT-3 列名规范化：小写、空白→下划线、非法剔除、空名 col_{i}、重名追加 _2。"""
    col = re.sub(r"[^\w\u4e00-\u9fff]+", "_", str(raw).strip().lower()).strip("_")
    col = col or f"col_{index}"
    if col in used:  # 重名：name → name_2 → name_3 …
        n = 2
        while f"{col}_{n}" in used:
            n += 1
        col = f"{col}_{n}"
    used.add(col)
    return col
