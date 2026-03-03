 !/bin/bash
# start.sh — SERVICE_NAME-aware entrypoint for docker-jtp:9
# Plan: 121-FACTORY-E2E-RESTART
#
# Image layout (build_and_push.sh copies src/ contents directly):
#   /app/services/<service_name>/main.py      ← from src/main.py  (backend)
#   /app/services/<service_name>/index.html   ← from src/index.html (frontend)
#
# Fix v3 (Plan 121): if main.py absent (frontend/static service),
#   auto-generate a minimal FastAPI stub so uvicorn can start.

if [ -n "$SERVICE_NAME" ]; then
    echo "[start.sh] Mode: SERVICE — ${SERVICE_NAME} on port 8000"
    SERVICE_DIR="/app/services/${SERVICE_NAME}"

    if [ ! -d "$SERVICE_DIR" ]; then
        echo "[start.sh] ERROR: service directory not found: $SERVICE_DIR"
        exit 1
    fi

    cd "$SERVICE_DIR"

    # Auto-generate stub main.py for frontend/static services that have no Python app
    if [ ! -f main.py ]; then
        echo "[start.sh] No main.py found — generating stub for ${SERVICE_NAME}"
        python3 - <<PYEOF
import os
svc = os.environ.get('SERVICE_NAME', 'unknown')
stub = f"""from fastapi import FastAPI
app = FastAPI(title="{svc}")

@app.get("/")
def root():
    return {{"service": "{svc}", "type": "frontend-stub", "status": "running"}}

@app.get("/health")
def health():
    return {{"status": "healthy", "service": "{svc}"}}
"""
with open("main.py", "w") as f:
    f.write(stub)
print(f"[start.sh] Stub main.py generated for {svc}")
PYEOF
    fi

    exec uvicorn main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --workers 1 \
        --log-level info \
        --no-access-log
else
    echo "[start.sh] Mode: GATEWAY on port 5000"
    cd /app
    exec uvicorn app:app \
        --host 0.0.0.0 \
        --port 5000 \
        --workers 2 \
        --log-level info
fi
