"""环境变量配置（pydantic-settings）。

仅承载“进程启动必需”的配置：数据库连接、服务地址、数据目录、密钥引用。
业务热更新配置（llm/agent/datasource/feature 四组 14 项）存 MySQL system_configs，
见 core.config 的 AppConfig；两层的边界约定见 DATA §2 / §6.5。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # MySQL（连接信息不能存 DB 里，走环境变量）
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "ecogain"
    mysql_password: str = "ecogain_pass"
    mysql_database: str = "ecogain"
    mysql_auth_database: str = "ecogain_auth"

    # 服务地址
    public_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"
    # 认证中心地址（浏览器 302 跳转用）
    auth_base_url: str = "http://localhost:8001"
    # 认证中心服务间调用地址（backend → auth-server 的 /token /userinfo）；
    # docker 模式为容器服务名（http://auth-server:8001），未设置时回落 auth_base_url
    auth_internal_base_url: str | None = None

    @property
    def auth_s2s_base_url(self) -> str:
        return self.auth_internal_base_url or self.auth_base_url

    # 数据卷根目录（uploads/ exports/ workspace/ analytics/ 均在其下）
    data_dir: str = "./data"
    # DuckDB 库文件路径覆盖（可选；未设置时走 system_configs 的 datasource.duckdb_path，
    # 其默认 /data/analytics/analytics.duckdb 为容器内路径，本地裸跑自动兜底 DATA_DIR 下）
    duckdb_path: str | None = None

    # 密钥（只走环境变量；system_configs 存引用名 llm.api_key_ref）
    llm_api_key: str = ""
    auth_client_secret: str = "ecogain-web-secret"

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+asyncmy://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )


@lru_cache
def get_env() -> EnvSettings:
    return EnvSettings()
