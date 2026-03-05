#!/usr/bin/env bash
# ============================================================
# Step 2.6: Post-Deploy Monitoring Sync
# Called automatically by run_deploy.sh after every successful deployment.
#
# Fixes 3 things that break on every new cluster (Lesson 35):
#
#   2.6a — Deploy kube-state-metrics (NodePort 30808) to new cluster
#   2.6b — Update prometheus.yml with new node IPs → restart Prometheus
#   2.6c — Sync run manifests to deployment engine outputs → restart exporter
#
# Lesson 38: 2.6b now writes ONLY ONE KSM target IP (not all node IPs).
#   KSM is a single pod — NodePort routes all IPs to same pod.
#   Writing N targets = N× data triplication in Prometheus.
#
# Usage:
#   ./_post_deploy_monitoring.sh <KUBECONFIG_PATH> <RUN_TS> <OUTPUTS_DIR>
# ============================================================
set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
export LANG=en_US.UTF-8
export PYTHONIOENCODING=utf-8

KUBECONFIG_PATH="${1:-}"
RUN_TS="${2:-$(date +%Y%m%d_%H%M%S)}"
OUTPUTS_DIR="${3:-$(dirname "$(readlink -f "$0")")/outputs}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROM_YML="$HOME/StarGate/10 Projects/Agent Zero/repos/agent-zero-agents/prometheus.yml"

echo "============================================================"
echo "  STEP 2.6: POST-DEPLOY MONITORING SYNC (Lesson 35)"
echo "============================================================"
echo "  Kubeconfig: $KUBECONFIG_PATH"
echo "  Run TS:     $RUN_TS"
echo "  Outputs:    $OUTPUTS_DIR"
echo ""

if [ -z "$KUBECONFIG_PATH" ] || [ ! -f "$KUBECONFIG_PATH" ]; then
    echo "[WARN] Step 2.6: No kubeconfig found — skipping monitoring sync"
    exit 0
fi

# ── Step 2.6a: Deploy kube-state-metrics ─────────────────────────────────────
echo "[$(date '+%H:%M:%S')] Step 2.6a: Deploying kube-state-metrics (NodePort 30808)..."

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo update prometheus-community >/dev/null 2>&1

helm upgrade --install kube-state-metrics prometheus-community/kube-state-metrics \
  --namespace kube-system \
  --kubeconfig="${KUBECONFIG_PATH}" \
  --set service.type=NodePort \
  --set service.nodePort=30808 \
  --set resources.requests.cpu=10m \
  --set resources.requests.memory=32Mi \
  --set resources.limits.cpu=100m \
  --set resources.limits.memory=128Mi \
  --wait --timeout=120s 2>&1

echo "[$(date '+%H:%M:%S')] OK  Step 2.6a: kube-state-metrics deployed on NodePort 30808"
echo ""

# ── Step 2.6b: Update prometheus.yml with new node IPs ───────────────────────
echo "[$(date '+%H:%M:%S')] Step 2.6b: Updating prometheus.yml with new cluster node IPs..."

# Get ExternalIP for each node
NODE_IPS=$(kubectl get nodes \
    --kubeconfig="${KUBECONFIG_PATH}" \
    -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="ExternalIP")].address}{"\n"}{end}' \
    2>/dev/null | grep -v '^$' | head -5)

echo "[$(date '+%H:%M:%S')] Detected node IPs:"
echo "$NODE_IPS" | sed 's/^/    /'

python3 -X utf8 << PYEOF
import re, sys
from pathlib import Path

prom_yml_path = r"${PROM_YML}"
run_ts = "${RUN_TS}"
node_ips_raw = """${NODE_IPS}"""

ips = [ip.strip() for ip in node_ips_raw.strip().splitlines() if ip.strip()]
if not ips:
    print("[WARN] Step 2.6b: No node IPs found — prometheus.yml not updated")
    sys.exit(0)

p = Path(prom_yml_path)
if not p.exists():
    print(f"[WARN] Step 2.6b: prometheus.yml not found at {prom_yml_path}")
    sys.exit(0)

content = p.read_text()

# Replace the kube-state-metrics targets block
# Find the static_configs targets for jtp-kube-state-metrics and replace IPs
#
# LESSON 38: KSM is a SINGLE POD — write ONLY ONE target IP (ips[0]).
# NodePort routes all node IPs to the same pod. Using N targets = N× data triplication!
# Run 4 had 3 targets → all metrics 3× inflated (660 services, 711 pods, 9 nodes shown).
# Fix: always use ips[0] as the single authoritative KSM scrape endpoint.
new_targets = f"          - '{ips[0]}:30808'  # ONE target only (Lesson 38 — prevents N× triplication)"

# Replace existing IP entries under jtp-kube-state-metrics
content = re.sub(
    r"(  - job_name: 'jtp-kube-state-metrics'.*?static_configs:\s*\n\s*- targets:\s*\n)((?:\s*- '[\d\.]+:\d+'\s*\n)+)",
    lambda m: m.group(1) + new_targets + "\n",
    content,
    flags=re.DOTALL
)

# Update run_id label
content = re.sub(r"run_id:\s+'[^']+'", f"run_id:     '{run_ts}'", content)

# Update the comment with new IPs
content = re.sub(
    r'# Run \d+ \([^\)]+\) Node IPs:[^\n]*',
    f"# Run ({run_ts}) Node IPs: {', '.join(ips)} — scraping only {ips[0]} (Lesson 38)",
    content
)
# Also update/add the Updated comment
content = re.sub(
    r'# Updated: \d{4}-\d{2}-\d{2}[^\n]*new cluster[^\n]*',
    f"# Updated: {run_ts[:4]}-{run_ts[4:6]}-{run_ts[6:8]} — new cluster after deployment {run_ts}",
    content
)

p.write_text(content)
print(f"[OK] Step 2.6b: prometheus.yml updated — KSM target: {ips[0]}:30808 (1 of {len(ips)} nodes)")
PYEOF

# Restart Prometheus container to pick up new config
PROM_CONTAINER=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i prometheus | head -1 || true)
if [ -n "$PROM_CONTAINER" ]; then
    docker restart "$PROM_CONTAINER" >/dev/null 2>&1
    echo "[$(date '+%H:%M:%S')] OK  Step 2.6b: Prometheus container '$PROM_CONTAINER' restarted"
else
    echo "[WARN] Step 2.6b: Prometheus container not found — restart it manually for new IPs to take effect"
fi
echo ""

# ── Step 2.6c: Sync deployment engine outputs ────────────────────────────────
echo "[$(date '+%H:%M:%S')] Step 2.6c: Syncing deployment engine outputs..."

RUN_DIR="$OUTPUTS_DIR/$RUN_TS"
ENGINE_K8S="$PROJECT_ROOT/engines/deployment_engine/outputs/manifests/kubernetes"
ENGINE_CICD="$PROJECT_ROOT/engines/deployment_engine/outputs/ci_cd_pipelines"

mkdir -p "$ENGINE_K8S" "$ENGINE_CICD"

# Copy gateway manifests
MANIFEST_COUNT=0
if [ -d "$RUN_DIR/k8s-manifests" ]; then
    # Remove old files first (don't mix runs)
    rm -f "$ENGINE_K8S"/*.yaml 2>/dev/null || true
    cp "$RUN_DIR/k8s-manifests/"*.yaml "$ENGINE_K8S/" 2>/dev/null || true
    MANIFEST_COUNT=$(ls "$ENGINE_K8S"/*.yaml 2>/dev/null | wc -l)
    echo "[$(date '+%H:%M:%S')] OK  Step 2.6c: Copied $MANIFEST_COUNT gateway manifests"
else
    echo "[WARN] Step 2.6c: No k8s-manifests directory in $RUN_DIR"
fi

# Copy deployment report as CI/CD artifact
if [ -f "$RUN_DIR/deployment_report.json" ]; then
    cp "$RUN_DIR/deployment_report.json" "$ENGINE_CICD/deployment_report_${RUN_TS}.json"
    echo "[$(date '+%H:%M:%S')] OK  Step 2.6c: Copied deployment_report_${RUN_TS}.json"
fi

# Restart deployment engine exporter (Python 3.12 rglob symlink workaround: use real files)
pkill -f "engines/deployment_engine/inputs/metrics_exporter.py" 2>/dev/null || true
sleep 2
nohup python3 -X utf8 "$PROJECT_ROOT/engines/deployment_engine/inputs/metrics_exporter.py" \
    > /tmp/deploy_exporter_${RUN_TS}.log 2>&1 &
EXPORTER_PID=$!
sleep 3

# Verify
MANIFESTS_METRIC=$(curl -s http://localhost:8005/metrics 2>/dev/null | grep '^deployment_engine_output_manifests' | awk '{print $2}')
echo "[$(date '+%H:%M:%S')] OK  Step 2.6c: Deployment engine exporter restarted (PID $EXPORTER_PID)"
echo "[$(date '+%H:%M:%S')]     deployment_engine_output_manifests = ${MANIFESTS_METRIC:-unknown}"
echo ""

echo "============================================================"
echo "  STEP 2.6: MONITORING SYNC COMPLETE"
echo "  - kube-state-metrics: deployed on NodePort 30808"
echo "  - prometheus.yml: updated — KSM target: 1 IP only (Lesson 38)"
echo "  - deployment engine: synced with $MANIFEST_COUNT manifests"
echo "============================================================"
