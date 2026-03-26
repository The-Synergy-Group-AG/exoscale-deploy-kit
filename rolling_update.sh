#!/bin/bash
# rolling_update.sh — Update ALL K8s deployments to the current service_version
# ============================================================================
# L62: Strategic fix — ensures ALL 219+ service deployments AND the gateway
# deployment use the same Docker image after a quick image rebuild.
#
# Without this, only `kubectl set image deployment/docker-jtp ...` updates the
# gateway, leaving all per-service pods on old images with unpatched code.
#
# Usage:
#   bash rolling_update.sh              # reads version from config.yaml
#   bash rolling_update.sh --version 61 # explicit version override
# ============================================================================
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse version from config.yaml or CLI
VERSION="${1:-}"
if [[ "$VERSION" == "--version" ]]; then
    VERSION="${2:-}"
fi
if [[ -z "$VERSION" ]]; then
    VERSION=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$SCRIPT_DIR/config.yaml'))
print(cfg['service_version'])
")
fi

DOCKER_HUB_USER=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$SCRIPT_DIR/config.yaml'))
print(cfg['docker_hub_user'])
")
SERVICE_NAME=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$SCRIPT_DIR/config.yaml'))
print(cfg['service_name'])
")
NAMESPACE=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$SCRIPT_DIR/config.yaml'))
print(cfg['k8s_namespace'])
")

IMAGE="${DOCKER_HUB_USER}/${SERVICE_NAME}:${VERSION}"
echo "============================================================"
echo "  Rolling Update — ALL deployments → ${IMAGE}"
echo "  Namespace: ${NAMESPACE}"
echo "============================================================"
echo ""

# Get all deployments using our Docker image
UPDATED=0
SKIPPED=0
TOTAL=0

while IFS=$'\t' read -r dep_name container_name current_image; do
    TOTAL=$((TOTAL + 1))
    if [[ "$current_image" == "$IMAGE" ]]; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi
    kubectl set image "deployment/$dep_name" "$container_name=$IMAGE" -n "$NAMESPACE" 2>/dev/null
    UPDATED=$((UPDATED + 1))
    if [[ $((UPDATED % 25)) -eq 0 ]]; then
        echo "  ... $UPDATED deployments updated"
    fi
done < <(kubectl get deployments -n "$NAMESPACE" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}' \
    | grep "${DOCKER_HUB_USER}/${SERVICE_NAME}:")

echo ""
echo "============================================================"
echo "  ✅ Rolling update complete"
echo "     Updated: $UPDATED / $TOTAL deployments"
echo "     Skipped: $SKIPPED (already on ${IMAGE})"
echo "============================================================"

# Plan 174: Stage 7b — Post-deploy test suite (automatic)
echo ""
echo "  Stage 7b: Running post-deploy test suite..."
LB_IP=$(kubectl get ingress -n "$NAMESPACE" -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}' 2>/dev/null)
if [[ -n "$LB_IP" ]] && [[ -f "$SCRIPT_DIR/run_external_tests.py" ]]; then
    python3 "$SCRIPT_DIR/run_external_tests.py" \
        --gateway "https://$LB_IP" \
        --suites user_stories integration \
        --workers 10 \
        --output "/tmp/post_deploy_test_results.json" 2>&1 | tail -10
    echo ""
    echo "  Test results: /tmp/post_deploy_test_results.json"
else
    echo "  Skipped: no LB IP or test runner not found"
fi
