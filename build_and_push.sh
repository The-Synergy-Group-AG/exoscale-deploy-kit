#!/usr/bin/env bash
# ============================================================
# build_and_push.sh — Build and push docker-jtp to Docker Hub
# ============================================================
# Architecture:
#   Service source files are NOT stored in this repository.
#   They are owned by the Service Engine and live at:
#     engines/service_engine/outputs/<generation>/services/
#
#   prep_services.py reads the CURRENT pointer file to determine
#   which generation to use, then syncs service/src/ files into
#   the Docker build workspace (service/services/) — a gitignored
#   ephemeral artifact that exists only during the build.
#
# Usage:
#   ./build_and_push.sh                    # uses CURRENT generation
#   ./build_and_push.sh --version 8.2.22   # pin to specific generation
#   ./build_and_push.sh --dry-run          # sync + report, no docker build
#   ./build_and_push.sh --no-push          # build only, skip docker push
#
# Configuration: config.yaml (project_name, service_name, service_version)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="${SCRIPT_DIR}/service"
CONFIG="${SCRIPT_DIR}/config.yaml"

# ── Parse CLI args ────────────────────────────────────────────────────────────
GEN_VERSION=""
DRY_RUN=false
NO_PUSH=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version|-v) GEN_VERSION="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        --no-push)    NO_PUSH=true; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Read version from config.yaml ────────────────────────────────────────────
if [[ ! -f "$CONFIG" ]]; then
    echo "❌ config.yaml not found at: $CONFIG"
    exit 1
fi

DOCKER_USER=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c['docker_hub_user'])")
IMAGE_NAME=$(python3  -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c['service_name'])")
VERSION=$(python3     -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(str(c['service_version']))")

FULL_TAG="${DOCKER_USER}/${IMAGE_NAME}:${VERSION}"
LATEST_TAG="${DOCKER_USER}/${IMAGE_NAME}:latest"

echo ""
echo "============================================================"
echo "  JTP Build & Push Pipeline"
echo "  Image   : ${FULL_TAG}"
echo "  Config  : ${CONFIG}"
[[ "$DRY_RUN" == "true" ]] && echo "  Mode    : DRY RUN (no docker build/push)"
[[ "$NO_PUSH" == "true" ]] && echo "  Mode    : NO PUSH (build only)"
echo "============================================================"
echo ""

# ── Step 1: Sync services from Service Engine output ─────────────────────────
echo "Step 1: Sync service source from Service Engine output..."
cd "${SCRIPT_DIR}"

SYNC_ARGS=""
[[ -n "$GEN_VERSION" ]] && SYNC_ARGS="--version ${GEN_VERSION}"
[[ "$DRY_RUN" == "true" ]] && SYNC_ARGS="${SYNC_ARGS} --dry-run"

if ! python3 prep_services.py ${SYNC_ARGS}; then
    EXIT_CODE=$?
    if [[ $EXIT_CODE -eq 2 ]]; then
        echo ""
        echo "⚠️  Sync completed with validation warnings (some services missing main.py)."
        echo "   Continuing build — check services_manifest.json for details."
    else
        echo ""
        echo "❌ Service sync FAILED (exit code ${EXIT_CODE}). Aborting build."
        exit 1
    fi
fi
echo ""

# Stop here if dry run
if [[ "$DRY_RUN" == "true" ]]; then
    echo "============================================================"
    echo "  DRY RUN complete — no Docker image built or pushed"
    echo "============================================================"
    exit 0
fi

# ── Step 2: Set gateway entrypoint + copy dashboard ──────────────────────────
echo "Step 2: Set gateway entrypoint (app_v6.py → service/app.py)..."
cp "${SERVICE_DIR}/app_v6.py" "${SERVICE_DIR}/app.py"
echo "  ✅ app.py = Gateway v7 (PROXY_TIMEOUT=2.5s, pool=50)"
# Plan 144: Copy port registry (single source of truth for all service ports)
cp "${SCRIPT_DIR}/../shared/core/service_ports.py" "${SERVICE_DIR}/service_ports.py" 2>/dev/null || echo "  ⚠ service_ports.py not found (using hardcoded fallback)"
echo "  ✅ service_ports.py = Port Registry SSOT (Plan 144)"
cp "${SCRIPT_DIR}/frontend/index.html" "${SERVICE_DIR}/dashboard.html"
echo "  ✅ dashboard.html = service dashboard (219 services)"
cp "${SCRIPT_DIR}/frontend/home.html"  "${SERVICE_DIR}/home.html"
echo "  ✅ home.html = AI-First dual-mode home page (L56)"
cp "${SCRIPT_DIR}/frontend/catalog.json" "${SERVICE_DIR}/catalog.json"
echo "  ✅ catalog.json = runtime API catalog (L62)"
echo ""

# ── Step 3: Build Docker image ────────────────────────────────────────────────
echo "Step 3: Build Docker image ${FULL_TAG} (platform: linux/amd64)..."
BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
docker build \
    --build-arg BUILD_TIME_ARG="${BUILD_TIME}" \
    --tag "${FULL_TAG}" \
    --tag "${LATEST_TAG}" \
    --platform linux/amd64 \
    "${SERVICE_DIR}"
echo ""
echo "  ✅ Build complete"
echo ""

# ── Step 4: Verify image ─────────────────────────────────────────────────────
echo "Step 4: Verify image..."
docker images "${DOCKER_USER}/${IMAGE_NAME}"
echo ""

# ── Step 5: Push to Docker Hub ───────────────────────────────────────────────
if [[ "$NO_PUSH" == "true" ]]; then
    echo "Step 5: Push skipped (--no-push)"
else
    echo "Step 5: Push ${FULL_TAG} to Docker Hub..."
    echo "  (Ensure you are logged in: docker login)"
    docker push "${FULL_TAG}"
    docker push "${LATEST_TAG}"
    echo ""
    echo "  ✅ Push complete"
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo "============================================================"
echo "  ✅ COMPLETE: ${FULL_TAG} is ready"
echo ""
echo "  Next steps:"
echo "  1. Run deployment : bash run_deploy.sh"
echo "  2. Or directly    : python3 deploy_pipeline.py"
echo "  3. Quick update   : bash rolling_update.sh   (updates ALL 219+ pods)"
echo "  4. Verify gateway : curl http://<NODE_IP>:30671/health"
echo "     Expected        : {\"version\": 7, \"proxy_timeout\": 2.5}"
echo "============================================================"
