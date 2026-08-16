FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 先拷贝依赖清单，利用层缓存
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY auth-server/pyproject.toml auth-server/pyproject.toml
RUN uv sync --frozen --no-dev

COPY backend backend
COPY auth-server auth-server

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/backend \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
EXPOSE 8000
