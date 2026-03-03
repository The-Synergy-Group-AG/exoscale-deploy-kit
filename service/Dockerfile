# JTP-Bio-V3 Gateway — 219 Microservices (Plan 121 v6)
# Key changes vs v5:
#   - app.py = gateway v7: PROXY_TIMEOUT=2.5s default (was 5.0s)
#   - Connection pool: max_connections=50 (was 500), keepalive_expiry=5s (was 30s)
#   - PROXY_TIMEOUT fix baked in — no kubectl patch needed after deploy
# Multi-stage build: venv built once, only runtime libs in final image

# ── Stage 1: Build ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install consolidated requirements (all 219 services use the same deps)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ── Stage 2: Production ───────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT="production" \
    BUILD_TIME=""

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appuser && useradd -r -g appuser appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy gateway entrypoint + startup script
# NOTE: app.py in this build = app_v6.py (gateway v7) — copied by build_and_push.sh
COPY app.py .
COPY start.sh .

# Copy all 219 service src directories into services/
# Each service lands at: /app/services/{service_name}/main.py
COPY services/ ./services/

ARG BUILD_TIME_ARG
ENV BUILD_TIME=$BUILD_TIME_ARG

RUN chown -R appuser:appuser /app && chmod +x /app/start.sh
USER appuser

EXPOSE 5000

# Health check hits the aggregate /health endpoint
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:5000/health || exit 1

# Startup script selects the right service based on SERVICE_NAME env var
CMD ["/app/start.sh"]
