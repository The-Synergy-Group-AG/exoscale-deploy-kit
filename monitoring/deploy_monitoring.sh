#!/bin/bash
# Deploy Monitoring Stack (Prometheus + Grafana) — Plan 170 Gap 15
# Called by deploy_pipeline.py Stage 5g: Post-deploy monitoring
# This is NOT optional — monitoring must be deployed on every infrastructure provisioning.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="exo-jtp-prod"

echo "  [monitoring] Deploying Prometheus + Grafana to ${NAMESPACE}..."

# Apply Prometheus config + deployment
kubectl apply -f "${SCRIPT_DIR}/prometheus-config.yaml" -n "${NAMESPACE}" 2>&1 | sed 's/^/    /'
kubectl apply -f "${SCRIPT_DIR}/prometheus-deployment.yaml" -n "${NAMESPACE}" 2>&1 | sed 's/^/    /'

# Create dashboard ConfigMap from JSON file (separate from YAML to handle large JSON)
if [ -f "${SCRIPT_DIR}/grafana-dashboard-fleet.json" ]; then
    kubectl create configmap grafana-dashboard-fleet \
        --from-file=jtp-fleet-dashboard.json="${SCRIPT_DIR}/grafana-dashboard-fleet.json" \
        -n "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - 2>&1 | sed 's/^/    /'
fi

# Apply Grafana config + deployment
kubectl apply -f "${SCRIPT_DIR}/grafana-deployment.yaml" -n "${NAMESPACE}" 2>&1 | sed 's/^/    /'

# Wait for pods
echo "  [monitoring] Waiting for monitoring pods..."
kubectl rollout status deployment/prometheus -n "${NAMESPACE}" --timeout=120s 2>&1 | sed 's/^/    /' || true
kubectl rollout status deployment/grafana -n "${NAMESPACE}" --timeout=120s 2>&1 | sed 's/^/    /' || true

# Verify
PROM_READY=$(kubectl get pods -n "${NAMESPACE}" -l app=prometheus --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
GRAF_READY=$(kubectl get pods -n "${NAMESPACE}" -l app=grafana --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)

echo "  [monitoring] Prometheus: ${PROM_READY} pod(s) running"
echo "  [monitoring] Grafana: ${GRAF_READY} pod(s) running"

if [ "${PROM_READY}" -ge 1 ] && [ "${GRAF_READY}" -ge 1 ]; then
    echo "  [monitoring] OK — Monitoring stack deployed"
    echo "  [monitoring] Access Grafana: kubectl port-forward svc/grafana 3000:3000 -n ${NAMESPACE}"
    echo "  [monitoring] Dashboard: JTP Agent Fleet Dashboard (pre-provisioned)"
else
    echo "  [monitoring] WARN — Monitoring pods not fully ready (will start shortly)"
fi
