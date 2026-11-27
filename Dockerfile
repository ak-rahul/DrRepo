# syntax=docker/dockerfile:1.7
# DrRepo image: Streamlit UI by default; the same image runs the CLI or the
# health API by overriding the command (see docker-compose.yml).

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

# semgrep lives in its own tool environment: as a project dependency it would
# pin mcp/opentelemetry/wcmatch to vulnerable versions. Bump it deliberately.
ARG SEMGREP_VERSION=1.187.0
ENV UV_TOOL_DIR=/opt/uv-tools \
    UV_TOOL_BIN_DIR=/opt/uv-tools/bin
RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install "semgrep==${SEMGREP_VERSION}"

# ---- runtime stage ------------------------------------------------------------
FROM python:3.12-slim-trixie

LABEL org.opencontainers.image.title="DrRepo"       org.opencontainers.image.description="Agentic health check for public GitHub repositories"       org.opencontainers.image.source="https://github.com/ak-rahul/DrRepo"       org.opencontainers.image.licenses="MIT"

# git: the clone collector shells out to it. Versions track the pinned Debian
# release (security updates via `apt-get upgrade`), so they aren't pinned here.
# hadolint ignore=DL3008
RUN apt-get update     && apt-get upgrade -y     && apt-get install -y --no-install-recommends git     && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --user-group drrepo
WORKDIR /app
# Code and tools stay root-owned (read-only for the app user); only the output
# directories are writable.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /opt/uv-tools /opt/uv-tools
RUN install -d -o 1000 -g 1000 /app/reports /app/logs

ENV PATH="/app/.venv/bin:/opt/uv-tools/bin:$PATH"     PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1

USER 1000:1000

# 8501 Streamlit UI · 8000 health API
EXPOSE 8501 8000

# Python instead of curl: one less package (and CVE surface) in the image.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3     CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=5)"]

# Credentials are supplied at runtime (--env-file / compose env_file); none are baked in.
CMD ["drrepo", "ui", "--host", "0.0.0.0", "--port", "8501", "--headless"]
