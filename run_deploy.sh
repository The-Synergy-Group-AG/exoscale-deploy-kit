#!/usr/bin/env bash
# ============================================================
# JTP Exoscale Deployment Runner
# Plan 122-DEH | Lesson 22: -X utf8 encoding fix
# Plan 123-P5+: Step 1.5 — auto-stage latest generated services
# Plan 125 Phase 1: Step 2.5 — Stage 5e/5f per-service pod deployment
# ============================================================
# Usage:
#   ./run_deploy.sh            # Interactive wizard + deploy
#   ./run_deploy.sh --auto     # Use config.yaml, no wizard
#   ./run_deploy.sh --teardown # Teardown THEN deploy (full cycle)
#   ./run_deploy.sh --dry-run  # Teardown dry-run only (no deploy)
#
# Features:
#   - LESSON 22: Forces python -X utf8 (fixes Exoscale SDK cp1252 crash)
#   - LESSON 27: Adds ~/.local/bin to PATH so helm is always found
#   - STEP 1.5: Automatically stages latest generated-v* services via
#               prep_services.py (no manual version pinning required)
#   - STEP 2.5: Deploys 219 individual service pods (Plan 125 Stage 5e/5f)
#   - Tees ALL output to timestamped log file for post-mortem analysis
#   - Pre-flight checklist before any cloud activity
#   - Automated post-mortem JSON generation after completion
#   - Sets LANG=en_US.UTF-8 + PYTHONIOENCODING=utf-8 as belt-and-suspenders
# ============================================================
set -euo pipefail

# ── Config ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUTS_DIR="$SCRIPT_DIR/outputs"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$OUTPUTS_DIR/deploy_run_${TS}.log"

# ── LESSON 22: Belt-and-suspenders encoding fix ─────────────
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
# The -X utf8 flag is set on the python3 command below (most reliable fix)

# ── LESSON 27: Ensure ~/.local/bin is in PATH (helm lives here) ─────────────
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

# ── Parse args ──────────────────────────────────────────────
DO_TEARDOWN=false
DRY_RUN=false
DEPLOY_ARGS="--auto"
SKIP_SERVICES=false

for arg in "$@"; do
    case "$arg" in
        --teardown)      DO_TEARDOWN=true ;;
        --dry-run)       DRY_RUN=true ;;
        --auto)          DEPLOY_ARGS="--auto" ;;
        --wizard)        DEPLOY_ARGS="" ;;
        --skip-preflight) DEPLOY_ARGS="$DEPLOY_ARGS --skip-preflight" ;;
        --skip-services) SKIP_SERVICES=true ;;  # Plan 125: skip Stage 5e/5f
    esac
done

# ── Setup output dir ─────────────────────────────────────────
mkdir -p "$OUTPUTS_DIR"

# ── Banner ───────────────────────────────────────────────────
cat <<'BANNER'
============================================================
  JTP EXOSCALE DEPLOYMENT RUNNER
  Plan 122-DEH hardened pipeline + Plan 123-P5+ auto-staging
  Plan 125 Phase 1: 219 per-service pod deployment (Stage 5e/5f)
============================================================
BANNER
echo "  Timestamp:    $TS"
echo "  Log file:     $LOG_FILE"
echo "  Teardown:     $DO_TEARDOWN"
echo "  Dry-run:      $DRY_RUN"
echo "  Skip-services: $SKIP_SERVICES"
echo "  Args:         $DEPLOY_ARGS"
echo ""

# ── Pre-Deploy Checklist (Strategic — Plan 122-DEH) ─────────
echo "============================================================"
echo "  PRE-DEPLOY CHECKLIST"
echo "============================================================"

PREFLIGHT_PASS=true

# Check 1: Docker daemon
if docker info >/dev/null 2>&1; then
    echo "  [PASS] Docker daemon: running"
else
    echo "  [FAIL] Docker daemon: NOT running — start Docker before deploying"
    PREFLIGHT_PASS=false
fi

# Check 2: kubectl
if kubectl version --client --output=json >/dev/null 2>&1; then
    echo "  [PASS] kubectl: available"
else
    echo "  [FAIL] kubectl: NOT found"
    PREFLIGHT_PASS=false
fi

# Check 3: helm (LESSON 27 — required for Stage 5c ingress + cert-manager)
if helm version --short >/dev/null 2>&1; then
    HELM_VER=$(helm version --short 2>/dev/null | head -1)
    echo "  [PASS] helm: $HELM_VER"
else
    echo "  [FAIL] helm: NOT found (required for Stage 5c ingress-nginx + cert-manager)"
    echo "         Install: cd /tmp && curl -fsSL https://get.helm.sh/helm-v3.17.1-linux-amd64.tar.gz | tar xz && cp linux-amd64/helm ~/.local/bin/"
    PREFLIGHT_PASS=false
fi

# Check 4: Python 3 with -X utf8 (Lesson 22)
if python3 -X utf8 -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null; then
    PYVER=$(python3 --version 2>&1)
    echo "  [PASS] Python: $PYVER (UTF-8 mode: OK)"
else
    echo "  [FAIL] Python 3.9+ required"
    PREFLIGHT_PASS=false
fi

# Check 5: config.yaml exists and readable
if [ -f "$SCRIPT_DIR/config.yaml" ]; then
    PROJ=$(grep 'project_name:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}')
    VER=$(grep 'service_version:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}' | tr -d "'")
    NODE_SIZE=$(grep 'node_type_size:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}')
    echo "  [PASS] config.yaml: project=$PROJ version=$VER node=$NODE_SIZE"
else
    echo "  [FAIL] config.yaml not found"
    PREFLIGHT_PASS=false
fi

# Check 6: .env credentials
if [ -f "$SCRIPT_DIR/.env" ]; then
    HAS_EXO=$(grep -c 'EXO_API_KEY=' "$SCRIPT_DIR/.env" 2>/dev/null || echo 0)
    HAS_DHT=$(grep -c 'DOCKER_HUB_TOKEN=' "$SCRIPT_DIR/.env" 2>/dev/null || echo 0)
    if [ "$HAS_EXO" -gt 0 ] && [ "$HAS_DHT" -gt 0 ]; then
        echo "  [PASS] .env credentials: EXO_API_KEY and DOCKER_HUB_TOKEN found"
    else
        echo "  [FAIL] .env: missing EXO_API_KEY or DOCKER_HUB_TOKEN"
        PREFLIGHT_PASS=false
    fi
else
    echo "  [FAIL] .env not found — copy .env.example and fill in credentials"
    PREFLIGHT_PASS=false
fi

# Check 7: DNS for Exoscale zone
EXO_ZONE=$(grep 'exoscale_zone:' "$SCRIPT_DIR/config.yaml" 2>/dev/null | awk '{print $2}' || echo "ch-dk-2")
if getent hosts "api-${EXO_ZONE}.exoscale.com" >/dev/null 2>&1; then
    echo "  [PASS] DNS: api-${EXO_ZONE}.exoscale.com resolves"
else
    echo "  [WARN] DNS: api-${EXO_ZONE}.exoscale.com not resolving — check network/VPN"
fi

# Check 8: Disk space (>= 2GB free)
FREE_KB=$(df -k "$SCRIPT_DIR" | awk 'NR==2 {print $4}')
FREE_GB=$((FREE_KB / 1024 / 1024))
if [ "$FREE_GB" -ge 2 ]; then
    echo "  [PASS] Disk space: ${FREE_GB}GB free"
else
    echo "  [WARN] Disk space: only ${FREE_GB}GB free (recommend >= 2GB)"
fi

# Check 9: prep_services.py exists
if [ -f "$SCRIPT_DIR/prep_services.py" ]; then
    echo "  [PASS] prep_services.py: found"
else
    echo "  [FAIL] prep_services.py: NOT found"
    PREFLIGHT_PASS=false
fi

# Check 10: gen_service_manifests.py exists (Plan 125 Phase 1)
if [ -f "$SCRIPT_DIR/gen_service_manifests.py" ]; then
    echo "  [PASS] gen_service_manifests.py: found (Plan 125 Stage 5e)"
else
    echo "  [WARN] gen_service_manifests.py: NOT found — Stage 5e will be skipped"
    SKIP_SERVICES=true
fi

# Check 11: CPU Budget Validation (Lesson 34c/36 — CRITICAL)
# 3 nodes × 3700m × 0.75 / 220 services = 37.8m headroom — use 10m (safe)
NODE_COUNT_CFG=$(grep 'node_count:' "$SCRIPT_DIR/config.yaml" 2>/dev/null | awk '{print $2}' || echo 3)
NUM_SERVICES=220
CLUSTER_CPU_M=$((NODE_COUNT_CFG * 3700))
MAX_SAFE_REQUEST_M=$(( (CLUSTER_CPU_M * 75 / 100) / NUM_SERVICES ))
echo "  [INFO] CPU budget: ${NODE_COUNT_CFG} nodes × 3700m × 0.75 / ${NUM_SERVICES} svcs = ${MAX_SAFE_REQUEST_M}m safe request"
if [ "${MAX_SAFE_REQUEST_M}" -lt 10 ]; then
    echo "  [FAIL] CPU budget: cluster too small for ${NUM_SERVICES} services with 10m each"
    PREFLIGHT_PASS=false
else
    echo "  [PASS] CPU budget: ${MAX_SAFE_REQUEST_M}m/svc available (using 10m requests = safe)"
fi

echo ""

if [ "$PREFLIGHT_PASS" = "false" ]; then
    echo "  [ABORT] Pre-deploy checklist FAILED — fix issues above before deploying"
    exit 1
fi

echo "  [OK] All critical checks passed — proceeding"
echo ""

# ── Dry run: just report ─────────────────────────────────────
if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN: would run teardown + stage-services + deploy + stage-5e. Exiting."
    exit 0
fi

# ── All output tee'd to log from here ────────────────────────
exec > >(tee -a "$LOG_FILE") 2>&1
echo "[$(date '+%H:%M:%S')] Deployment log started: $LOG_FILE"
echo ""

# ── Step 1: Optional teardown ───────────────────────────────
if [ "$DO_TEARDOWN" = "true" ]; then
    echo "============================================================"
    echo "  STEP 1: TEARDOWN — Decommissioning existing infrastructure"
    echo "============================================================"
    cd "$SCRIPT_DIR"
    set +e
    python3 -X utf8 teardown.py --force 2>&1
    TEAR_EXIT=$?
    set -e
    echo ""
    if [ $TEAR_EXIT -ne 0 ]; then
        echo "[WARN] Teardown exited with code $TEAR_EXIT — continuing to deploy"
    else
        echo "[OK] Teardown complete"
    fi
    echo ""
    # Brief pause to let Exoscale fully release locks
    echo "Waiting 30s for Exoscale to fully release resources..."
    sleep 30
fi

# ── Step 1.5: Stage latest generated services ───────────────
echo "============================================================"
echo "  STEP 1.5: STAGE SERVICES — auto-selecting latest generation"
echo "============================================================"
cd "$SCRIPT_DIR"
python3 -X utf8 prep_services.py 2>&1
PREP_EXIT=$?
if [ $PREP_EXIT -ne 0 ]; then
    echo "[ABORT] prep_services.py FAILED (exit=$PREP_EXIT) — cannot build Docker image without services"
    exit 1
fi
echo "[OK] Service staging complete"
echo ""

# ── Step 2: Deploy ──────────────────────────────────────────
echo "============================================================"
echo "  STEP 2: DEPLOYMENT — Fresh deploy with Plan 122-DEH engine"
echo "============================================================"
cd "$SCRIPT_DIR"
set +e
python3 -X utf8 deploy_pipeline.py $DEPLOY_ARGS 2>&1
DEPLOY_EXIT=$?
set -e

echo ""
echo "============================================================"
echo "  STEP 2 COMPLETED — Exit code: $DEPLOY_EXIT"
echo "============================================================"
echo ""

# ── Step 2.5: Stage 5e/5f — Per-Service Pod Deployment (Plan 125) ────────────
if [ "$SKIP_SERVICES" = "false" ] && [ "$DEPLOY_EXIT" -eq 0 ]; then
    echo "============================================================"
    echo "  STEP 2.5: STAGE 5e — Deploying 219 Service Pods (Plan 125)"
    echo "============================================================"

    # Find latest kubeconfig from deploy_pipeline output
    KUBECONFIG_PATH=$(find "$OUTPUTS_DIR" -name "kubeconfig.yaml" | sort | tail -1)
    K8S_NS=$(grep 'k8s_namespace:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}')
    SVC_VER=$(grep 'service_version:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}' | tr -d "'")
    SVC_IMAGE="iandrewitz/docker-jtp:${SVC_VER}"
    SERVICE_MANIFESTS_DIR="$OUTPUTS_DIR/k8s-services-${TS}"

    if [ -z "$KUBECONFIG_PATH" ]; then
        echo "[WARN] Stage 5e: No kubeconfig found in $OUTPUTS_DIR — skipping service pod deployment"
    else
        echo "[$(date '+%H:%M:%S')] Stage 5e: kubeconfig = $KUBECONFIG_PATH"
        echo "[$(date '+%H:%M:%S')] Stage 5e: image      = $SVC_IMAGE"
        echo "[$(date '+%H:%M:%S')] Stage 5e: namespace  = $K8S_NS"
        echo "[$(date '+%H:%M:%S')] Stage 5e: manifests  = $SERVICE_MANIFESTS_DIR"
        echo ""

        # -- Step 2.5b: Remove ResourceQuota (Lesson 34b -- CRITICAL) --
        echo "[$(date '+%H:%M:%S')] Step 2.5b: Removing ResourceQuota (Lesson 34b)"
        kubectl delete resourcequota --all -n "${K8S_NS}" \
            --kubeconfig="${KUBECONFIG_PATH}" --ignore-not-found=true 2>&1 || true
        echo "[$(date '+%H:%M:%S')] OK  Step 2.5b: ResourceQuota cleared"
        echo ""
        # Generate per-service manifests
        cd "$SCRIPT_DIR"
        python3 -X utf8 gen_service_manifests.py \
            --output-dir "${SERVICE_MANIFESTS_DIR}" \
            --image "${SVC_IMAGE}" \
            --namespace "${K8S_NS}" 2>&1
        GEN_EXIT=$?

        if [ $GEN_EXIT -ne 0 ]; then
            echo "[WARN] Stage 5e: gen_service_manifests.py failed (exit=$GEN_EXIT) — skipping apply"
        else
            MANIFEST_COUNT=$(ls "${SERVICE_MANIFESTS_DIR}"/*.yaml 2>/dev/null | wc -l)
            echo "[$(date '+%H:%M:%S')] Stage 5e: Applying ${MANIFEST_COUNT} service manifests (batches of 50)..."
            echo ""

            BATCH=0
            for yaml_file in "${SERVICE_MANIFESTS_DIR}"/*.yaml; do
                kubectl apply -f "${yaml_file}" --kubeconfig="${KUBECONFIG_PATH}" 2>&1
                BATCH=$((BATCH + 1))
                if [ $((BATCH % 50)) -eq 0 ]; then
                    echo "[$(date '+%H:%M:%S')] Stage 5e: Applied ${BATCH}/${MANIFEST_COUNT} — sleeping 5s..."
                    sleep 5
                fi
            done

            echo ""
            echo "[$(date '+%H:%M:%S')] OK  Stage 5e: ${BATCH}/${MANIFEST_COUNT} service manifests applied"
            echo ""

            # ── Stage 5f: Wait for service pods to be Running ────────────────
            echo "============================================================"
            echo "  STEP 2.5: STAGE 5f — Waiting for Service Pods Ready"
            echo "============================================================"

            TIMEOUT_S=600   # 10 minutes max
            START_T=$(date +%s)
            LAST_REPORTED="-1"

            while true; do
                RUNNING=$(kubectl get pods -n "${K8S_NS}" \
                    --kubeconfig="${KUBECONFIG_PATH}" \
                    --field-selector=status.phase=Running \
                    --no-headers 2>/dev/null \
                    | grep -v "docker-jtp\|nginx\|cert-manager\|ingress" \
                    | wc -l || echo 0)

                ELAPSED=$(( $(date +%s) - START_T ))

                if [ "${RUNNING}" != "${LAST_REPORTED}" ]; then
                    echo "[$(date '+%H:%M:%S')] Stage 5f: ${RUNNING}/219 service pods running (${ELAPSED}s elapsed)..."
                    LAST_REPORTED="${RUNNING}"
                fi

                if [ "${RUNNING}" -ge 200 ]; then
                    echo "[$(date '+%H:%M:%S')] OK  Stage 5f: ${RUNNING}/219 service pods ready — threshold met"
                    break
                fi

                if [ "${ELAPSED}" -gt "${TIMEOUT_S}" ]; then
                    echo "[$(date '+%H:%M:%S')] WARN Stage 5f: Timeout after ${TIMEOUT_S}s — ${RUNNING}/219 pods running"
                    echo "  Run: kubectl get pods -n ${K8S_NS} --kubeconfig=${KUBECONFIG_PATH} | grep -v Running"
                    break
                fi

                sleep 15
            done

            echo ""
            echo "[$(date '+%H:%M:%S')] OK  Stage 5e/5f complete"
        fi
    fi
elif [ "$SKIP_SERVICES" = "true" ]; then
    echo "[INFO] Step 2.5: Skipped (--skip-services flag or gen_service_manifests.py not found)"
elif [ "$DEPLOY_EXIT" -ne 0 ]; then
    echo "[WARN] Step 2.5: Skipped — deploy_pipeline.py failed (exit=$DEPLOY_EXIT)"
fi

echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETED — Exit code: $DEPLOY_EXIT"
echo "  Log: $LOG_FILE"
echo "============================================================"
echo ""

# ── Step 3: Post-mortem report ───────────────────────────────
POSTMORTEM_FILE="$OUTPUTS_DIR/postmortem_${TS}.json"
LATEST_REPORT=$(find "$OUTPUTS_DIR" -name "deployment_report.json" -newer "$SCRIPT_DIR/config.yaml" 2>/dev/null | sort | tail -1)

python3 -X utf8 - <<PYEOF
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

ts = "$TS"
log_file = "$LOG_FILE"
deploy_exit = $DEPLOY_EXIT
latest_report = "$LATEST_REPORT"
out_file = "$POSTMORTEM_FILE"

pm = {
    "timestamp": ts,
    "completed_at": datetime.now().isoformat(),
    "deployment_success": deploy_exit == 0,
    "exit_code": deploy_exit,
    "log_file": log_file,
    "deployment_report": None,
    "issues_detected": [],
    "git_commit": "",
    "plan": "125",
}

# Attach deployment_report.json if found
if latest_report and Path(latest_report).exists():
    try:
        pm["deployment_report"] = json.loads(Path(latest_report).read_text())
    except Exception as e:
        pm["issues_detected"].append(f"Could not parse deployment report: {e}")

# Scan log for known error patterns
if Path(log_file).exists():
    log_content = Path(log_file).read_text(errors="replace")
    patterns = [
        ("FAIL",          "Pipeline stage FAILED"),
        ("CrashLoopBack", "Pod CrashLoopBackOff detected"),
        ("ErrImagePull",  "Image pull failure"),
        ("HTTP 500",      "Exoscale API 500 error"),
        ("conflict",      "API conflict (409) during resource creation"),
        ("WARN",          "Pipeline warnings present"),
    ]
    for pattern, label in patterns:
        count = log_content.count(pattern)
        if count > 0:
            pm["issues_detected"].append(f"{label} ({count} occurrences)")

# Get current git commit
try:
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        capture_output=True, text=True,
        cwd="$SCRIPT_DIR"
    )
    pm["git_commit"] = result.stdout.strip()
except Exception:
    pass

Path(out_file).write_text(json.dumps(pm, indent=2))
print(f"[POSTMORTEM] Report: {out_file}")
if pm["issues_detected"]:
    print(f"[POSTMORTEM] Issues detected ({len(pm['issues_detected'])}):")
    for issue in pm["issues_detected"]:
        print(f"  - {issue}")
if pm["deployment_success"]:
    print("[POSTMORTEM] STATUS: DEPLOYMENT SUCCESS")
else:
    print(f"[POSTMORTEM] STATUS: DEPLOYMENT FAILED (exit={deploy_exit})")
PYEOF

exit $DEPLOY_EXIT
