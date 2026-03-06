#!/usr/bin/env bash
# deploy_phase4.sh — Deploy Phase 4 Frontend Web Layer
# Usage: bash frontend/deploy_phase4.sh <kubeconfig>
# Deploys: nginx ConfigMaps + Deployment + Service + updated Ingress
set -euo pipefail
trap '' HUP PIPE

KUBECONFIG="${1:-}"
if [[ -z "$KUBECONFIG" ]]; then
  # Auto-detect latest kubeconfig from outputs/
  KUBECONFIG=$(ls -t "$(dirname "$0")/../outputs"/*/kubeconfig.yaml 2>/dev/null | head -1)
  [[ -z "$KUBECONFIG" ]] && { echo "ERROR: no kubeconfig found — pass as arg 1"; exit 1; }
fi
echo "[phase4] Using kubeconfig: $KUBECONFIG"

FRONTEND_DIR="$(dirname "$0")"
NS="exo-jtp-prod"

# Step 1: Inject actual index.html into the frontend-html ConfigMap
echo "[phase4] Injecting index.html into frontend-html ConfigMap..."
HTML_FILE="$FRONTEND_DIR/index.html"
[[ -f "$HTML_FILE" ]] || { echo "ERROR: $HTML_FILE not found"; exit 1; }

kubectl --kubeconfig "$KUBECONFIG" create configmap frontend-html \
  --from-file=index.html="$HTML_FILE" \
  --namespace "$NS" \
  --dry-run=client -o yaml \
  | kubectl --kubeconfig "$KUBECONFIG" apply -f -

# Step 2: Apply nginx conf ConfigMap + Deployment + Service
echo "[phase4] Applying frontend-k8s.yaml..."
kubectl --kubeconfig "$KUBECONFIG" apply -f "$FRONTEND_DIR/frontend-k8s.yaml"

# Wait for frontend-nginx rollout
echo "[phase4] Waiting for frontend-nginx rollout..."
kubectl --kubeconfig "$KUBECONFIG" rollout status deployment/frontend-nginx \
  -n "$NS" --timeout=120s

# Step 3: Apply Phase 4 Ingress (/ → nginx, /api/* → gateway)
echo "[phase4] Applying ingress-phase4.yaml..."
kubectl --kubeconfig "$KUBECONFIG" apply -f "$FRONTEND_DIR/ingress-phase4.yaml"

# Step 4: Verify
echo "[phase4] Verifying frontend pods..."
kubectl --kubeconfig "$KUBECONFIG" get pods -n "$NS" -l app=frontend-nginx
echo "[phase4] Verifying ingress..."
kubectl --kubeconfig "$KUBECONFIG" get ingress -n "$NS"

echo ""
echo "✅ Phase 4 complete — frontend-nginx deployed, ingress updated"
echo "   → https://jobtrackerpro.ch  (SPA dashboard)"
echo "   → https://jobtrackerpro.ch/api/<service>/health  (gateway)"
