# DrRepo Dockerfile
# Pinned to a specific patch release (not the floating `3.11-slim` tag) so
# rebuilds are reproducible; `apt-get upgrade` below still pulls latest
# security patches for installed OS packages on every build.
FROM python:3.11.15-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# `git` is a runtime dependency: the repo_clone collector shells out to it to
# shallow-clone repositories for analysis. `curl` is only for the healthcheck.
# `apt-get upgrade` applies OS security patches released since the base image
# was built -- rebuild periodically even without a Dockerfile change.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements first (for better caching)
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY app.py .
COPY scripts/ ./scripts/

# Create necessary directories
RUN mkdir -p logs reports

# Create non-root user for security
RUN useradd -m -u 1000 drrepo && \
    chown -R drrepo:drrepo /app

USER drrepo

# 8501: Streamlit UI
# 8000: Health Check API (optional)
EXPOSE 8501 8000

# Health check using Streamlit's built-in health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Real credentials must be supplied at runtime (--env-file .env or
# docker-compose's env_file) -- no .env is baked into the image.
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=false", \
     "--server.enableXsrfProtection=false"]
