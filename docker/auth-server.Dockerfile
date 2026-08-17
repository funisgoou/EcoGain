FROM python:3.12-slim

# 国内构建加速：pip/uv 统一走腾讯 pypi 镜像（可用 --build-arg PIP_INDEX_URL=... 覆盖）
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_DEFAULT_INDEX=${PIP_INDEX_URL} \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=300

WORKDIR /app

# uv 二进制直接从 pypi 镜像装（ghcr.io 国内拉取极慢），版本与本地开发环境一致
RUN pip install --no-cache-dir uv==0.11.17

COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY auth-server/pyproject.toml auth-server/pyproject.toml
# 不用 --frozen：它会绕过镜像配置、按 uv.lock 里固化的 pypi.org URL 下载；
# --locked 同样校验锁文件一致性，且尊重 UV_DEFAULT_INDEX 走镜像
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-dev

COPY auth-server auth-server

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/auth-server \
    PYTHONUNBUFFERED=1

WORKDIR /app/auth-server
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
