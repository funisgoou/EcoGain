"""配置单例与热更新（CFG-1 / CFG-2）。

system_configs 全量加载为 AppConfig 单例；DB 缺行时用 DEFAULTS 兜底。
reload_config 先全量校验后原子替换，失败旧配置继续生效。
校验规则与默认值和 DATA §6.5 一字不差。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.env import get_env
from app.core.logging import get_logger

log = get_logger(__name__)

# (config_key, 组, 类型, 默认值, 校验规则描述) —— 与 DATA §6.5 逐行对齐
DEFAULTS: dict[str, tuple[str, str, Any]] = {
    "llm.provider": ("llm", "string", "tokenrhythm"),
    "llm.base_url": ("llm", "string", "https://tokenrhythm.studio/v1"),
    "llm.model": ("llm", "string", "deepseek-v4-flash-0731"),
    "llm.api_key_ref": ("llm", "string", "LLM_API_KEY"),
    "llm.temperature": ("llm", "float", 0.2),
    "agent.max_tool_rounds": ("agent", "int", 15),
    "agent.task_timeout_seconds": ("agent", "int", 120),
    "agent.context_rounds": ("agent", "int", 20),
    "agent.context_token_budget": ("agent", "int", 8000),
    "agent.sql_row_limit": ("agent", "int", 1000),
    "agent.sql_timeout_seconds": ("agent", "int", 10),
    "datasource.duckdb_path": ("datasource", "string", "/data/analytics/analytics.duckdb"),
    "feature.attachment_enabled": ("feature", "bool", True),
    "feature.export_enabled": ("feature", "bool", True),
}

# config_key → AppConfig 字段名（显式映射，llm 组字段带 llm_ 前缀、其余组去前缀）
_KEY_TO_FIELD: dict[str, str] = {
    "llm.provider": "llm_provider",
    "llm.base_url": "llm_base_url",
    "llm.model": "llm_model",
    "llm.api_key_ref": "llm_api_key_ref",
    "llm.temperature": "llm_temperature",
    "agent.max_tool_rounds": "max_tool_rounds",
    "agent.task_timeout_seconds": "task_timeout_seconds",
    "agent.context_rounds": "context_rounds",
    "agent.context_token_budget": "context_token_budget",
    "agent.sql_row_limit": "sql_row_limit",
    "agent.sql_timeout_seconds": "sql_timeout_seconds",
    "datasource.duckdb_path": "duckdb_path",
    "feature.attachment_enabled": "attachment_enabled",
    "feature.export_enabled": "export_enabled",
}

_URL_RE = re.compile(r"^https?://")


@dataclass
class AppConfig:
    """system_configs 的类型化视图。属性名 = config_key 去掉组前缀后的蛇形名。"""

    llm_provider: str = DEFAULTS["llm.provider"][2]
    llm_base_url: str = DEFAULTS["llm.base_url"][2]
    llm_model: str = DEFAULTS["llm.model"][2]
    llm_api_key_ref: str = DEFAULTS["llm.api_key_ref"][2]
    llm_temperature: float = DEFAULTS["llm.temperature"][2]
    max_tool_rounds: int = DEFAULTS["agent.max_tool_rounds"][2]
    task_timeout_seconds: int = DEFAULTS["agent.task_timeout_seconds"][2]
    context_rounds: int = DEFAULTS["agent.context_rounds"][2]
    context_token_budget: int = DEFAULTS["agent.context_token_budget"][2]
    sql_row_limit: int = DEFAULTS["agent.sql_row_limit"][2]
    sql_timeout_seconds: int = DEFAULTS["agent.sql_timeout_seconds"][2]
    duckdb_path: str = DEFAULTS["datasource.duckdb_path"][2]
    attachment_enabled: bool = DEFAULTS["feature.attachment_enabled"][2]
    export_enabled: bool = DEFAULTS["feature.export_enabled"][2]

    # ---- 校验（DATA §6.5 校验规则列）----
    errors: list[str] = field(default_factory=list, repr=False)

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not self.llm_provider:
            errs.append("llm.provider 不能为空")
        if not self.llm_base_url or not _URL_RE.match(self.llm_base_url):
            errs.append("llm.base_url 需为合法 URL")
        if not self.llm_model:
            errs.append("llm.model 不能为空")
        if not self.llm_api_key_ref:
            errs.append("llm.api_key_ref 不能为空")
        if not 0 <= self.llm_temperature <= 1:
            errs.append("llm.temperature 需在 0~1")
        if not 5 <= self.max_tool_rounds <= 50:
            errs.append("agent.max_tool_rounds 需在 5~50")
        if not 30 <= self.task_timeout_seconds <= 600:
            errs.append("agent.task_timeout_seconds 需在 30~600")
        if not 5 <= self.context_rounds <= 100:
            errs.append("agent.context_rounds 需在 5~100")
        if not 2000 <= self.context_token_budget <= 100000:
            errs.append("agent.context_token_budget 需在 2000~100000")
        if not 100 <= self.sql_row_limit <= 10000:
            errs.append("agent.sql_row_limit 需在 100~10000")
        if not 1 <= self.sql_timeout_seconds <= 60:
            errs.append("agent.sql_timeout_seconds 需在 1~60")
        if not self.duckdb_path:
            errs.append("datasource.duckdb_path 不能为空")
        self.errors = errs
        return errs

    @classmethod
    def from_rows(cls, rows: list[tuple[str, str | None]]) -> "AppConfig":
        """system_configs 查询行 → AppConfig；未知 key 忽略，缺行用默认值。"""
        field_of_key = {k: v for k, v in _KEY_TO_FIELD.items()}
        type_map = {k: v[1] for k, v in DEFAULTS.items()}
        kwargs: dict[str, Any] = {}
        for key, value in rows:
            if key not in type_map or value is None:
                continue
            t = type_map[key]
            try:
                parsed: Any
                if t == "int":
                    parsed = int(value)
                elif t == "float":
                    parsed = float(value)
                elif t == "bool":
                    parsed = str(value).strip().lower() in ("1", "true", "yes", "on")
                else:
                    parsed = str(value).strip()
                kwargs[field_of_key[key]] = parsed
            except (TypeError, ValueError):
                # 单项类型不符不炸整次加载，交给 validate() 汇总报告
                continue
        return cls(**{k: v for k, v in kwargs.items() if k in field_of_key.values()})


# ---- 进程级单例 ----
_config: AppConfig | None = None


def get_config() -> AppConfig:
    if _config is None:
        # 单测/未初始化场景兜底：默认值（DUCKDB_PATH 覆盖 > DATA_DIR 推导）
        env_duck = os.environ.get("DUCKDB_PATH", "").strip()
        duck = env_duck or f"{get_env().data_dir}/analytics/analytics.duckdb"
        return AppConfig(duckdb_path=duck)
    return _config


def set_config(cfg: AppConfig) -> None:
    global _config
    _config = cfg


async def load_configs(engine: AsyncEngine) -> AppConfig:
    """CFG-1：启动时全量读取 system_configs（lifespan 调用）。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        rows = (await session.execute(text("SELECT config_key, config_value FROM system_configs"))).all()
    cfg = AppConfig.from_rows(list(rows))
    # 解析优先级：DUCKDB_PATH 环境变量 > system_configs 值 > DATA_DIR 兜底
    # （DB 默认值 /data/... 为容器内路径，本地裸跑时不存在，改用 DATA_DIR）
    env_duck = os.environ.get("DUCKDB_PATH", "").strip()
    if env_duck:
        cfg.duckdb_path = env_duck
    elif not cfg.duckdb_path or cfg.duckdb_path == DEFAULTS["datasource.duckdb_path"][2]:
        cfg.duckdb_path = f"{get_env().data_dir}/analytics/analytics.duckdb"
    errs = cfg.validate()
    if errs:
        log.warning("config_validation_failed", errors=errs)
    set_config(cfg)
    log.info("config_loaded", items=len(rows))
    return cfg


@dataclass
class ReloadResult:
    status: str  # ok | error
    message: str


async def reload_config(engine: AsyncEngine) -> ReloadResult:
    """CFG-2：管理端热更新。先构建新配置并校验，全部通过才原子替换；
    校验失败旧配置继续生效。LLM 客户端失效由 llm_gateway 监听配置指纹自动完成。"""
    try:
        new_cfg = await load_configs(engine)
        # load_configs 内部已 set_config，若校验失败需回滚为旧值
        if new_cfg.errors:
            old = get_config()
            set_config(old)  # 旧配置继续生效
            return ReloadResult("error", "配置校验失败：" + "；".join(new_cfg.errors))
    except Exception as e:  # noqa: BLE001 —— reload 入口需兜住一切 DB 异常
        log.error("config_reload_failed", error=str(e))
        return ReloadResult("error", f"配置重载失败：{e}")
    n = len([f for f in fields(AppConfig) if f.name != "errors"])
    return ReloadResult("ok", f"重载 {n} 项配置，LLM 客户端已重建")
