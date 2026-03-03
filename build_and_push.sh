#!/bin/bash
# ============================================================
# Build and push docker-jtp:6 to Docker Hub
# Plan 121 — applies all lessons learned from Plan 120
# ============================================================
# WHAT CHANGED IN :6 vs :5:
#   - Gateway v7: PROXY_TIMEOUT=2.5s default (was 5.0s)
#   - Connection pool: max_connections=50 (was 500)
#   - keepalive_expiry=5s (was 30s)
#   - No kubectl set env patch needed after deploy
# ============================================================

set -e  # Exit on any error

DOCKER_USER="iandrewitz"
IMAGE_NAME="docker-jtp"
VERSION="6"
FULL_TAG="${DOCKER_USER}/${IMAGE_NAME}:${VERSION}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="${SCRIPT_DIR}/service"

echo "============================================================"
echo "  Building ${FULL_TAG}"
echo "  Plan 121 — Gateway v7 with PROXY_TIMEOUT=2.5s baked in"
echo "============================================================"
echo ""

# ── Step 1: Prep service source files ────────────────────────
echo "Step 1: Preparing 219 service source files..."
cd "${SCRIPT_DIR}"
python3 prep_services.py
echo ""

# ── Step 2: Copy app_v6.py as app.py for the Dockerfile ──────
echo "Step 2: Setting gateway app (app_v6.py → service/app.py)..."
cp "${SERVICE_DIR}/app_v6.py" "${SERVICE_DIR}/app.py"
echo "  ✅ app.py = gateway v7 (PROXY_TIMEOUT=2.5, pool=50)"
echo ""

# ── Step 3: Build the Docker image ───────────────────────────
echo "Step 3: Building Docker image ${FULL_TAG}..."
BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
docker build \
    --build-arg BUILD_TIME_ARG="${BUILD_TIME}" \
    --tag "${FULL_TAG}" \
    --tag "${DOCKER_USER}/${IMAGE_NAME}:latest" \
    --platform linux/amd64 \
    "${SERVICE_DIR}"
echo ""
echo "  ✅ Build complete"
echo ""

# ── Step 4: Verify the image ─────────────────────────────────
echo "Step 4: Verifying image..."
docker images "${DOCKER_USER}/${IMAGE_NAME}"
echo ""

# ── Step 5: Push to Docker Hub ───────────────────────────────
echo "Step 5: Pushing ${FULL_TAG} to Docker Hub..."
echo "  (Ensure you are logged in: docker login)"
docker push "${FULL_TAG}"
docker push "${DOCKER_USER}/${IMAGE_NAME}:latest"
echo ""
echo "  ✅ Push complete"
echo ""

# ── Summary ──────────────────────────────────────────────────
echo "============================================================"
echo "  ✅ COMPLETE: ${FULL_TAG} is ready on Docker Hub"
echo ""
echo "  Next steps:"
echo "  1. Update deploy manifest:  image: ${FULL_TAG}"
echo "  2. Provision new cluster:   python3 deploy_pipeline.py"
echo "  3. Verify gateway version:  curl http://<NODE_IP>:30671/health"
echo "     Expected: {\"version\": 7, \"proxy_timeout\": 2.5}"
echo "============================================================"
