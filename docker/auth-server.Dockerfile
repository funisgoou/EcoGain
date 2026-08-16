FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY auth-server/pyproject.toml auth-server/pyproject.toml
RUN uv sync --frozen --no-dev

COPY auth-server auth-server

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/auth-server \
    PYTHONUNBUFFERED=1

WORKDIR /app/auth-server
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
