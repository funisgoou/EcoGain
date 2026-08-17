FROM python:3.12-slim

# 国内构建加速：pip/uv 统一走腾讯 pypi 镜像（可用 --build-arg PIP_INDEX_URL=... 覆盖）
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=300

WORKDIR /app

# uv 二进制直接从 pypi 镜像装（ghcr.io 国内拉取极慢），版本与本地开发环境一致
RUN pip install --no-cache-dir uv==0.11.17

# 先拷贝依赖清单，利用层缓存
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY auth-server/pyproject.toml auth-server/pyproject.toml
# uv.lock 已按腾讯镜像生成（URL 固化为 mirrors.cloud.tencent.com），
# --frozen 跳过重新解析与索引校验、直接按锁文件安装，构建结果确定
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev

COPY backend backend
COPY auth-server auth-server

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/backend \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
EXPOSE 8000
