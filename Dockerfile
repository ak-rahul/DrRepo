# syntax=docker/dockerfile:1.7
# DrRepo image: Streamlit UI by default; the same image runs the CLI, MCP server,
# or health API by overriding the command (see docker-compose.yml).

# ---- build stage: resolve and install dependencies with uv -------------------
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first (cached layer), then the project itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- runtime stage ------------------------------------------------------------
FROM python:3.12-slim-trixie

# git: the clone collector shells out to it. curl: container healthcheck only.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 drrepo
WORKDIR /app
COPY --from=builder --chown=drrepo:drrepo /app/.venv /app/.venv
RUN mkdir -p /app/reports /app/logs && chown -R drrepo:drrepo /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER drrepo

# 8501 Streamlit UI · 8000 health API · 8765 MCP (streamable-http)
EXPOSE 8501 8000 8765

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://localhost:8501/_stcore/health || exit 1

# Credentials are supplied at runtime (--env-file / compose env_file); none are baked in.
CMD ["drrepo", "ui", "--host", "0.0.0.0", "--port", "8501", "--headless"]
