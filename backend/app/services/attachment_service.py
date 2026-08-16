"""附件业务（ATT-1~8）：上传、异步解析、DuckDB 导入、级联删除、启动恢复。"""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

import aiofiles
import pandas as pd
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.env import get_env
from app.core.logging import get_logger
from app.core.security import normalize_column_name, safe_path, secure_filename
from app.db.duckdb import get_duckdb
from app.db.mysql import new_session
from app.models import Attachment, Conversation
from app.schemas import ws as wsmsg
from app.schemas.common import BizError
from app.ws.manager import MANAGER

log = get_logger(__name__)

ALLOWED_EXT = {"csv", "xlsx", "txt", "md"}
ALLOWED_MIME: dict[str, set[str]] = {  # 扩展名 → 可接受 mimetype（双校验）
    "csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "txt": {"text/plain"},
    "md": {"text/markdown", "text/plain"},
}
MAX_SIZE = 10 * 1024 * 1024  # 10MB 上限
TEXT_PREVIEW_CHARS = 300


async def save_upload(session: AsyncSession, user_id: int, conversation_id: int, file) -> Attachment:
    """ATT-1：扩展名+mimetype 双校验、10MB 上限、secure_filename、落盘、建行、
    fire-and-forget 触发异步解析。"""
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXT or (file.content_type or "") not in ALLOWED_MIME[ext]:
        raise BizError(40002, "仅支持 csv/xlsx/txt/md")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise BizError(40002, "文件超过 10MB 上限")
    name = secure_filename(file.filename or "file")
    rel_dir = Path(get_env().data_dir) / "uploads" / str(user_id) / str(conversation_id)
    rel_dir.mkdir(parents=True, exist_ok=True)
    dest = rel_dir / name
    if dest.exists():  # 冲突加后缀
        name = f"{dest.stem}_{secrets.token_hex(3)}{dest.suffix}"
        dest = rel_dir / name
    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)
    att = Attachment(
        conversation_id=conversation_id,
        file_name=name,
        file_path=f"{user_id}/{conversation_id}/{name}",
        file_type=ext,
        file_size=len(content),
        parse_status="pending",
    )
    session.add(att)
    await session.flush()
    att_id = att.id
    # ATT-2 异步解析，立即返回（fire-and-forget）
    asyncio.create_task(parse_attachment(att_id))
    return att


def _read_sheet(src: Path, file_type: str):
    """结构化读取：编码 utf-8 → gbk 退避；脏行跳过计数。返回 (rows, columns, skipped)。"""
    if file_type == "csv":
        for enc in ("utf-8", "gbk", "utf-8-sig"):
            try:
                df = pd.read_csv(src, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("无法识别的文件编码（尝试 utf-8/gbk）")
    else:
        df = pd.read_excel(src)
    df = df.dropna(how="all")  # 全空行剔除
    skipped = int(df.isna().all(axis=1).sum()) if len(df) else 0
    df = df.where(pd.notna(df), None)  # NaN → None（DuckDB NULL）
    return df.to_dict("records"), list(df.columns), skipped


def _read_text_lenient(src: Path) -> str:
    for enc in ("utf-8", "gbk", "utf-16", "latin-1"):
        try:
            return src.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return src.read_bytes().decode("utf-8", errors="replace")


async def parse_attachment(att_id: int) -> None:
    """ATT-2~4 主链路：parsing →（结构化导入 DuckDB / 文本提取缓存）→ ready；
    任何异常 failed；终态广播 attachment_status。"""
    async with new_session() as session, session.begin():
        att = await session.get(Attachment, att_id)
        if att is None:
            return
        att.parse_status = "parsing"
        conv = await session.get(Conversation, att.conversation_id)
        uid = conv.user_id if conv else 0
        cid, ftype = att.conversation_id, att.file_type
        src = Path(get_env().data_dir) / "uploads" / att.file_path
        try:
            if ftype in ("csv", "xlsx"):
                rows, columns, skipped = await asyncio.to_thread(_read_sheet, src, ftype)
                table = f"attachment_data_{att.id}"
                await _import_to_duckdb(table, columns, rows)
                att.duckdb_table = table
            else:  # txt / md
                text = await asyncio.to_thread(_read_text_lenient, src)
                cache_dir = Path(get_env().data_dir) / "workspace" / str(uid) / str(cid)
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / f"attachment_text_{att.id}.txt").write_text(text, encoding="utf-8")
            att.parse_status = "ready"
            final_status = "ready"
            log.info("attachment_parsed", attachment_id=att.id, file_type=ftype)
        except Exception as e:  # noqa: BLE001 —— 解析失败是业务终态而非异常
            att.parse_status = "failed"
            att.error_message = str(e)[:1000]
            final_status = "failed"
            log.warning("attachment_parse_failed", attachment_id=att.id, error=str(e))
    await MANAGER.broadcast(cid, wsmsg.msg_attachment_status(att_id, final_status))


def _infer_type(values: list) -> str:
    """列类型推断：INT→BIGINT / 浮点→DOUBLE / 其余 VARCHAR（脏数据容错整体降级）。"""
    import re as _re

    int_re, float_re, date_re = _re.compile(r"^-?\d+$"), _re.compile(r"^-?\d+\.\d+$"), None
    seen = 0
    is_int = is_float = is_date = True
    for v in values:
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        s = str(v)
        seen += 1
        if is_int and not int_re.match(s):
            is_int = False
        if is_float and not (float_re.match(s) or int_re.match(s)):
            is_float = False
        if is_date:
            try:
                import datetime as _dt

                _dt.date.fromisoformat(s[:10])
            except ValueError:
                is_date = False
        if seen >= 200 and not (is_int or is_float or is_date):
            break
    if seen == 0:
        return "VARCHAR"
    if is_int:
        return "BIGINT"
    if is_float:
        return "DOUBLE"
    if is_date:
        return "DATE"
    return "VARCHAR"


def _col_values(rows: list[dict], key) -> list:
    return [r.get(key) for r in rows[:500]]


async def _import_to_duckdb(table: str, columns, rows: list[dict]) -> None:
    """ATT-3：写锁内建表分批插入；类型推断失败整列降 VARCHAR；附 __row_no。"""
    duck = get_duckdb()
    used: set[str] = set()
    col_defs: list[str] = []
    col_names: list[str] = []
    for i, c in enumerate(columns):
        name = normalize_column_name(c, i, used)
        typ = _infer_type(_col_values(rows, c))
        col_names.append(name)
        col_defs.append(f'"{name}" {typ}')
    col_defs.append('"__row_no" BIGINT')
    async with duck.write_txn():
        await asyncio.to_thread(
            duck._conn.execute,  # noqa: SLF001 —— 单例内部连接（写锁保护下）
            f'CREATE SCHEMA IF NOT EXISTS attachments',
        )
        await asyncio.to_thread(
            duck._conn.execute,  # noqa: SLF001
            f'CREATE TABLE attachments."{table}" ({", ".join(col_defs)})',
        )

        def _batch_insert(conn) -> None:
            placeholders = ", ".join("?" for _ in range(len(col_names) + 1))
            sql = f'INSERT INTO attachments."{table}" VALUES ({placeholders})'
            batch: list[tuple] = []
            for row_no, r in enumerate(rows, 1):
                batch.append(tuple(r.get(c) for c in columns) + (row_no,))
                if len(batch) >= 5000:
                    conn.executemany(sql, batch)
                    batch = []
            if batch:
                conn.executemany(sql, batch)

        await asyncio.to_thread(_batch_insert, duck._conn)


async def get_owned(session: AsyncSession, user_id: int, attachment_id: int) -> Attachment:
    att = await session.get(Attachment, attachment_id)
    conv = await session.get(Conversation, att.conversation_id) if att else None
    if att is None or conv is None or conv.status == "deleted":
        raise BizError(40401, "附件不存在")
    if conv.user_id != user_id:
        raise BizError(40301, "无权访问该附件")
    return att


async def get_ready_attachments(
    session: AsyncSession, conversation_id: int, ids: list[int]
) -> list[Attachment] | None:
    """返回 None 表示存在不合规附件（不属于本会话 / parse_status != ready）。"""
    if not ids:
        return []
    result = await session.execute(
        select(Attachment).where(Attachment.id.in_(ids), Attachment.conversation_id == conversation_id)
    )
    atts = list(result.scalars().all())
    if len(atts) != len(ids) or any(a.parse_status != "ready" for a in atts):
        return None
    return atts


async def delete_attachment(att: Attachment) -> None:
    """ATT-6 级联：DB 行 → 源文件 → 检索缓存 → DuckDB 表。"""
    duck = get_duckdb()
    async with new_session() as session, session.begin():
        conv = await session.get(Conversation, att.conversation_id)
        uid = conv.user_id if conv else 0
        await session.execute(text("DELETE FROM attachments WHERE id = :id"), {"id": att.id})
    cid, table = att.conversation_id, att.duckdb_table
    (Path(get_env().data_dir) / "uploads" / att.file_path).unlink(missing_ok=True)
    (Path(get_env().data_dir) / "workspace" / str(uid) / str(cid)
     / f"attachment_text_{att.id}.txt").unlink(missing_ok=True)
    if table:
        try:
            async with duck.write_txn():
                await asyncio.to_thread(
                    duck._conn.execute,  # noqa: SLF001
                    f'DROP TABLE IF EXISTS attachments."{table}"',
                )
        except Exception as e:  # noqa: BLE001 —— DuckDB 清理失败不阻塞删除
            log.error("duckdb_drop_failed", error=str(e), table=table)
    log.info("attachment_deleted", attachment_id=att.id)


async def get_attachment_file(att: Attachment) -> Path | None:
    """ATT-7 下载定位（路径穿越在此拦截）。uid 经会话归属链取得。"""
    async with new_session() as session:
        conv = await session.get(Conversation, att.conversation_id)
        uid = conv.user_id if conv else 0
    path = safe_path(uid, att.conversation_id, att.file_path, roots=("uploads",))
    if path is None or not path.exists():
        return None
    return path


async def recover_stuck_attachments() -> None:
    """ATT-8 启动恢复：pending/parsing → failed。"""
    async with new_session() as session, session.begin():
        await session.execute(text("""
            UPDATE attachments SET parse_status = 'failed',
                error_message = '服务重启导致解析中断'
            WHERE parse_status IN ('pending', 'parsing')
        """))
    log.info("stuck_attachments_recovered")
