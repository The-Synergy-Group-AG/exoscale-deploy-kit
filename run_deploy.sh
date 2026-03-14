#!/usr/bin/env bash
# ============================================================
# JTP Exoscale Deployment Runner
# Plan 122-DEH | Lesson 22: -X utf8 encoding fix
# Plan 123-P5+: Step 1.5 — auto-stage latest generated services
# Plan 125 Phase 1: Step 2.5 — Stage 5e/5f per-service pod deployment
# Plan 125 Lesson 35: Step 2.6 — Post-deploy monitoring sync (self-healing)
# Plan 125 Phase 2: Step 2.7 — Post-deploy service verification + unit tests
# Lesson 39b: Fix node_count whitespace arithmetic crash in CPU budget check
# Lesson 49: Unit-only in-pod tests (integration/e2e need external deps)
# Lesson 50: Auto-update DNS + raw REST (SDK broken) + website verify
# ============================================================
# Usage:
#   ./run_deploy.sh            # Interactive wizard + deploy
#   ./run_deploy.sh --auto     # Use config.yaml, no wizard
#   ./run_deploy.sh --teardown # Teardown THEN deploy (full cycle)
#   ./run_deploy.sh --dry-run  # Preflight check only (no deploy)
#
# Features:
#   - LESSON 22: Forces python -X utf8 (fixes Exoscale SDK cp1252 crash)
#   - LESSON 27: Adds ~/.local/bin to PATH so helm is always found
#   - LESSON 35: Step 2.6 auto-deploys kube-state-metrics + updates
#                prometheus.yml node IPs + syncs engine outputs after
#                every successful deployment (self-healing dashboards)
#   - LESSON 38: Step 2.6b writes ONLY ONE KSM target IP (not all nodes)
#                KSM is a single pod — N targets = N× data triplication
#   - LESSON 49: Step 2.7b runs unit tests ONLY via kubectl exec.
#                integration/e2e/performance/security/user_stories require
#                external network access not available inside pods.
#   - LESSON 50: Step 2.6b auto-updates jobtrackerpro.ch DNS A records to
#                current LB IP using raw REST (SDK list_dns_domains broken).
#                Deletes stale A records to prevent round-robin to dead IPs.
#                Step 2.7c verifies DNS propagation, TLS cert issuance, and
#                end-to-end website reachability before declaring success.
#   - STEP 1.5: Automatically stages latest generated-v* services via
#               prep_services.py (no manual version pinning required)
#   - STEP 2.5: Deploys 219 individual service pods (Plan 125 Stage 5e/5f)
#   - STEP 2.7: Post-deploy service verification
#               2.7a — /health sweep of all 219 service pods
#               2.7b — Unit tests only (L49) via kubectl exec
#               2.7c — DNS propagation + TLS cert + website reachability
#   - Tees ALL output to timestamped log file for post-mortem analysis
#   - Pre-flight checklist before any cloud activity
#   - Automated post-mortem JSON generation after completion
#   - Sets LANG=en_US.UTF-8 + PYTHONIOENCODING=utf-8 as belt-and-suspenders
# ============================================================
set -euo pipefail
# L44: ignore SIGHUP/SIGPIPE — survive terminal close / Cline background timeout
trap '' HUP PIPE

# L47: Cleanup guard — auto-teardown if infra was created but script fails.
# Set INFRA_CREATED=true after Step 2 exits 0; this trap fires on any exit.
INFRA_CREATED=false
cleanup_infra() {
    local _exit=$?
    if [ "$INFRA_CREATED" = "true" ] && [ "$_exit" -ne 0 ]; then
        echo ""
        echo "============================================================"
        echo "  L47 AUTO-CLEANUP: Step 2 created infra but script failed"
        echo "  exit_code=$_exit  Running teardown.py --force ..."
        echo "============================================================"
        python3 -X utf8 teardown.py --force 2>&1 || true
        echo "  L47 AUTO-CLEANUP: teardown complete"
    fi
}
trap cleanup_infra EXIT

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

# ── LESSON 27: Ensure ~/.local/bin is in PATH (helm lives here) ─────────────
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

# ── Parse args ──────────────────────────────────────────────
DO_TEARDOWN=false
DRY_RUN=false
DEPLOY_ARGS="--auto"
SKIP_SERVICES=false

for arg in "$@"; do
    case "$arg" in
        --teardown)       DO_TEARDOWN=true ;;
        --dry-run)        DRY_RUN=true ;;
        --auto)           DEPLOY_ARGS="--auto" ;;
        --wizard)         DEPLOY_ARGS="" ;;
        --skip-preflight) DEPLOY_ARGS="$DEPLOY_ARGS --skip-preflight" ;;
        --skip-services)  SKIP_SERVICES=true ;;
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
  Plan 125 Phase 2: Post-deploy service verification + test suite (Step 2.7)
  Lesson 35: Post-deploy monitoring sync (Stage 2.6)
  Lesson 38: KSM single target (no triplication)
============================================================
BANNER
echo "  Timestamp:     $TS"
echo "  Log file:      $LOG_FILE"
echo "  Teardown:      $DO_TEARDOWN"
echo "  Dry-run:       $DRY_RUN"
echo "  Skip-services: $SKIP_SERVICES"
echo "  Args:          $DEPLOY_ARGS"
echo ""

# ── Pre-Deploy Checklist ──────────────────────────────────────
echo "============================================================"
echo "  PRE-DEPLOY CHECKLIST"
echo "============================================================"

PREFLIGHT_PASS=true

# Check 1: Docker
if docker info >/dev/null 2>&1; then
    echo "  [PASS] Docker daemon: running"
else
    echo "  [FAIL] Docker daemon: NOT running"
    PREFLIGHT_PASS=false
fi

# Check 2: kubectl
if kubectl version --client --output=json >/dev/null 2>&1; then
    echo "  [PASS] kubectl: available"
else
    echo "  [FAIL] kubectl: NOT found"
    PREFLIGHT_PASS=false
fi

# Check 3: helm
if helm version --short >/dev/null 2>&1; then
    HELM_VER=$(helm version --short 2>/dev/null | head -1)
    echo "  [PASS] helm: $HELM_VER"
else
    echo "  [FAIL] helm: NOT found"
    echo "         Install: curl -fsSL https://get.helm.sh/helm-v3.17.1-linux-amd64.tar.gz | tar xz && cp linux-amd64/helm ~/.local/bin/"
    PREFLIGHT_PASS=false
fi

# Check 4: Python 3.9+
if python3 -X utf8 -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null; then
    PYVER=$(python3 --version 2>&1)
    echo "  [PASS] Python: $PYVER (UTF-8 mode: OK)"
else
    echo "  [FAIL] Python 3.9+ required"
    PREFLIGHT_PASS=false
fi

# Check 4b: Python deploy dependencies (L52: pyyaml missing caused silent deploy abort)
MISSING_DEPS=""
for pkg in yaml dotenv exoscale_auth boto3; do
    if ! python3 -c "import $pkg" 2>/dev/null; then
        MISSING_DEPS="$MISSING_DEPS $pkg"
    fi
done
if [ -z "$MISSING_DEPS" ]; then
    echo "  [PASS] Python deps: yaml, dotenv, exoscale_auth, boto3 all importable"
else
    echo "  [WARN] Python deps missing:$MISSING_DEPS — installing from requirements.txt..."
    pip install -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
    pip install --target "$(python3 -c 'import site; print(site.getsitepackages()[0])')" \
        -r "$SCRIPT_DIR/requirements.txt" -q 2>&1 | tail -3
    # Re-check after install attempt
    STILL_MISSING=""
    for pkg in yaml dotenv exoscale_auth boto3; do
        python3 -c "import $pkg" 2>/dev/null || STILL_MISSING="$STILL_MISSING $pkg"
    done
    if [ -z "$STILL_MISSING" ]; then
        echo "  [PASS] Python deps installed successfully"
    else
        echo "  [FAIL] Python deps still missing after install attempt:$STILL_MISSING"
        echo "         Run: pip install -r requirements.txt"
        PREFLIGHT_PASS=false
    fi
fi

# Check 5: config.yaml
if [ -f "$SCRIPT_DIR/config.yaml" ]; then
    PROJ=$(grep 'project_name:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}' | tr -d '[:space:]\r')
    VER=$(grep 'service_version:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}' | tr -d "'[:space:]\r")
    NODE_SIZE=$(grep 'node_type_size:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}' | tr -d '[:space:]\r')
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

# Check 7: DNS
EXO_ZONE=$(grep 'exoscale_zone:' "$SCRIPT_DIR/config.yaml" 2>/dev/null | awk '{print $2}' | tr -d '[:space:]\r' || echo "ch-dk-2")
if getent hosts "api-${EXO_ZONE}.exoscale.com" >/dev/null 2>&1; then
    echo "  [PASS] DNS: api-${EXO_ZONE}.exoscale.com resolves"
else
    echo "  [WARN] DNS: api-${EXO_ZONE}.exoscale.com not resolving — check network/VPN"
fi

# Check 8: Disk space
FREE_KB=$(df -k "$SCRIPT_DIR" | awk 'NR==2 {print $4}')
FREE_GB=$((FREE_KB / 1024 / 1024))
if [ "$FREE_GB" -ge 2 ]; then
    echo "  [PASS] Disk space: ${FREE_GB}GB free"
else
    echo "  [WARN] Disk space: only ${FREE_GB}GB free (recommend >= 2GB)"
fi

# Check 9: prep_services.py
if [ -f "$SCRIPT_DIR/prep_services.py" ]; then
    echo "  [PASS] prep_services.py: found"
else
    echo "  [FAIL] prep_services.py: NOT found"
    PREFLIGHT_PASS=false
fi

# Check 10: gen_service_manifests.py (Plan 125 Phase 1)
if [ -f "$SCRIPT_DIR/gen_service_manifests.py" ]; then
    echo "  [PASS] gen_service_manifests.py: found (Plan 125 Stage 5e)"
else
    echo "  [WARN] gen_service_manifests.py: NOT found — Stage 5e will be skipped"
    SKIP_SERVICES=true
fi

# Check 11: run_service_tests.py (Plan 125 Phase 2 Step 2.7)
if [ -f "$SCRIPT_DIR/run_service_tests.py" ]; then
    echo "  [PASS] run_service_tests.py: found (Plan 125 Step 2.7b)"
else
    echo "  [WARN] run_service_tests.py: NOT found — Step 2.7b test suite will be skipped"
fi

# Check 12: CPU Budget Validation (Lesson 34c/36 — CRITICAL)
# Lesson 39b fix: strip all whitespace + CR from grep result before arithmetic
# 3 nodes × 3700m × 0.75 / 220 services = 37.8m headroom — use 10m (safe)
NODE_COUNT_CFG=$(grep 'node_count:' "$SCRIPT_DIR/config.yaml" 2>/dev/null \
    | awk '{print $2}' | tr -d '[:space:]\r\n' || true)
NODE_COUNT_CFG="${NODE_COUNT_CFG:-3}"
if ! [[ "$NODE_COUNT_CFG" =~ ^[0-9]+$ ]]; then NODE_COUNT_CFG=3; fi
NUM_SERVICES=220
CLUSTER_CPU_M=$(( NODE_COUNT_CFG * 3700 ))
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

# ── Dry run: preflight only ───────────────────────────────────
if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN: preflight passed. Engine ready for Run 5."
    echo "  To deploy: cd $SCRIPT_DIR && bash run_deploy.sh --auto"
    exit 0
fi

# ── All output tee'd to log from here ────────────────────────
exec > >(tee -a "$LOG_FILE") 2>&1
echo "[$(date '+%H:%M:%S')] Deployment log started: $LOG_FILE"
echo ""

# ── Step 1: Optional teardown ───────────────────────────────
if [ "$DO_TEARDOWN" = "true" ]; then
    echo "============================================================"
    echo "  STEP 1: TEARDOWN"
    echo "============================================================"
    cd "$SCRIPT_DIR"
    set +e
    python3 -X utf8 teardown.py --force 2>&1
    TEAR_EXIT=$?
    set -e
    if [ $TEAR_EXIT -ne 0 ]; then
        echo "[WARN] Teardown exited $TEAR_EXIT — continuing to deploy"
    else
        echo "[OK] Teardown complete"
    fi
    echo "Waiting 30s for Exoscale to release resources..."
    sleep 30
fi

# ── Step 1.5: Stage latest generated services ───────────────
echo "============================================================"
echo "  STEP 1.5: STAGE SERVICES"
echo "============================================================"
cd "$SCRIPT_DIR"
python3 -X utf8 prep_services.py 2>&1
PREP_EXIT=$?
if [ $PREP_EXIT -ne 0 ]; then
    echo "[ABORT] prep_services.py FAILED (exit=$PREP_EXIT)"
    exit 1
fi
echo "[OK] Service staging complete"
echo ""

# ── Step 2: Deploy ──────────────────────────────────────────
echo "============================================================"
echo "  STEP 2: DEPLOYMENT"
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

# L47: Mark infra as created so cleanup_infra trap can fire if later steps fail.
if [ "$DEPLOY_EXIT" -eq 0 ]; then
    INFRA_CREATED=true
fi

# ── Step 2.1: DNS Update — immediately after LB IP is known (Lesson 51) ─────
# L51: DNS must be updated BEFORE cert-manager runs the ACME HTTP-01 challenge.
#      If DNS still points to the old LB IP when Let's Encrypt does secondary
#      validation, the challenge fails (invalid) and the cert is not issued.
#      Moving DNS update here gives ~10-15 min of propagation time while the
#      219 service pods deploy — cert-manager only runs after ingress is live.
if [ "$DEPLOY_EXIT" -eq 0 ]; then
    EARLY_REPORT=$(find "$OUTPUTS_DIR" -name "deployment_report.json" | sort | tail -1)
    EARLY_LB_IP=$(python3 -c "import json; d=json.load(open('$EARLY_REPORT')); print(d['resources']['ingress']['lb_ip'])" 2>/dev/null || echo "")
    if [ -n "$EARLY_LB_IP" ]; then
        echo ""
        echo "============================================================"
        echo "  STEP 2.1: EARLY DNS UPDATE → jobtrackerpro.ch → $EARLY_LB_IP"
        echo "  (L51: update DNS now so it propagates before ACME challenge)"
        echo "============================================================"
        set +e
        python3 -X utf8 "$SCRIPT_DIR/_update_dns.py" "$EARLY_LB_IP" 2>&1
        EARLY_DNS_EXIT=$?
        set -e
        if [ $EARLY_DNS_EXIT -ne 0 ]; then
            echo "[WARN] Step 2.1: DNS update failed (exit=$EARLY_DNS_EXIT) — cert may fail"
        else
            echo "[OK]   Step 2.1: DNS updated early → $EARLY_LB_IP"
        fi
    else
        echo "[WARN] Step 2.1: Could not extract LB_IP — skipping early DNS update"
    fi
fi

# ── Step 2.5: Stage 5e/5f — Per-Service Pod Deployment (Plan 125) ─────────
if [ "$SKIP_SERVICES" = "false" ] && [ "$DEPLOY_EXIT" -eq 0 ]; then
    echo "============================================================"
    echo "  STEP 2.5: STAGE 5e — Deploying 219 Service Pods"
    echo "============================================================"

    KUBECONFIG_PATH=$(find "$OUTPUTS_DIR" -name "kubeconfig.yaml" | sort | tail -1)
    K8S_NS=$(grep 'k8s_namespace:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}' | tr -d '[:space:]\r')
    SVC_VER=$(grep 'service_version:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}' | tr -d "'[:space:]\r")
    SVC_IMAGE="iandrewitz/docker-jtp:${SVC_VER}"
    SERVICE_MANIFESTS_DIR="$OUTPUTS_DIR/k8s-services-${TS}"

    if [ -z "$KUBECONFIG_PATH" ]; then
        echo "[WARN] Stage 5e: No kubeconfig found — skipping"
    else
        echo "[$(date '+%H:%M:%S')] Stage 5e: kubeconfig = $KUBECONFIG_PATH"
        echo "[$(date '+%H:%M:%S')] Stage 5e: image      = $SVC_IMAGE"
        echo "[$(date '+%H:%M:%S')] Stage 5e: namespace  = $K8S_NS"
        echo ""

        # Step 2.5b: Remove ResourceQuota (Lesson 34b — CRITICAL)
        echo "[$(date '+%H:%M:%S')] Step 2.5b: Removing ResourceQuota (Lesson 34b)"
        kubectl delete resourcequota --all -n "${K8S_NS}" \
            --kubeconfig="${KUBECONFIG_PATH}" --ignore-not-found=true 2>&1 || true
        echo "[$(date '+%H:%M:%S')] OK  Step 2.5b: ResourceQuota cleared"
        echo ""

        cd "$SCRIPT_DIR"
        python3 -X utf8 gen_service_manifests.py \
            --output-dir "${SERVICE_MANIFESTS_DIR}" \
            --image "${SVC_IMAGE}" \
            --namespace "${K8S_NS}" 2>&1
        GEN_EXIT=$?

        if [ $GEN_EXIT -ne 0 ]; then
            echo "[WARN] Stage 5e: gen_service_manifests.py failed (exit=$GEN_EXIT)"
        else
            MANIFEST_COUNT=$(ls "${SERVICE_MANIFESTS_DIR}"/*.yaml 2>/dev/null | wc -l)
            echo "[$(date '+%H:%M:%S')] Stage 5e: Applying ${MANIFEST_COUNT} manifests (batches of 50)..."

            BATCH=0
            for yaml_file in "${SERVICE_MANIFESTS_DIR}"/*.yaml; do
                kubectl apply -f "${yaml_file}" --kubeconfig="${KUBECONFIG_PATH}" 2>&1
                BATCH=$((BATCH + 1))
                if [ $((BATCH % 50)) -eq 0 ]; then
                    echo "[$(date '+%H:%M:%S')] Stage 5e: Applied ${BATCH}/${MANIFEST_COUNT} — sleeping 5s..."
                    sleep 5
                fi
            done

            echo "[$(date '+%H:%M:%S')] OK  Stage 5e: ${BATCH}/${MANIFEST_COUNT} manifests applied"
            echo ""

            # Stage 5f: Wait for Running
            echo "============================================================"
            echo "  STEP 2.5: STAGE 5f — Waiting for Service Pods Ready"
            echo "============================================================"

            TIMEOUT_S=600
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
                    echo "[$(date '+%H:%M:%S')] Stage 5f: ${RUNNING}/219 pods running (${ELAPSED}s)..."
                    LAST_REPORTED="${RUNNING}"
                fi

                if [ "${RUNNING}" -ge 200 ]; then
                    echo "[$(date '+%H:%M:%S')] OK  Stage 5f: ${RUNNING}/219 ready — threshold met"
                    break
                fi

                if [ "${ELAPSED}" -gt "${TIMEOUT_S}" ]; then
                    echo "[$(date '+%H:%M:%S')] WARN Stage 5f: Timeout ${TIMEOUT_S}s — ${RUNNING}/219 running"
                    break
                fi

                sleep 15
            done

            echo "[$(date '+%H:%M:%S')] OK  Stage 5e/5f complete"
        fi
    fi
elif [ "$SKIP_SERVICES" = "true" ]; then
    echo "[INFO] Step 2.5: Skipped (--skip-services)"
elif [ "$DEPLOY_EXIT" -ne 0 ]; then
    echo "[WARN] Step 2.5: Skipped — deploy_pipeline.py failed (exit=$DEPLOY_EXIT)"
fi

# ── Step 2.6: Post-Deploy Monitoring Sync (Lesson 35 + 38) ──────────────────
# 2.6a KSM deployed (NodePort 30808)
# 2.6b prometheus.yml updated — ONE target only (Lesson 38) → Prometheus restart
# 2.6c engine outputs synced → exporter restart
if [ "$DEPLOY_EXIT" -eq 0 ]; then
    LATEST_KC=$(find "$OUTPUTS_DIR" -name "kubeconfig.yaml" | sort | tail -1)
    LATEST_RUN_DIR=$(find "$OUTPUTS_DIR" -maxdepth 1 -type d -name '[0-9]*' | sort | tail -1)
    LATEST_RUN_TS=$(basename "$LATEST_RUN_DIR" 2>/dev/null || echo "$TS")

    set +e
    bash "$SCRIPT_DIR/_post_deploy_monitoring.sh" \
        "${LATEST_KC}" "${LATEST_RUN_TS}" "${OUTPUTS_DIR}" 2>&1
    MONITORING_EXIT=$?
    set -e
    if [ $MONITORING_EXIT -ne 0 ]; then
        echo "[WARN] Step 2.6: Monitoring sync exited $MONITORING_EXIT (non-fatal)"
    fi
else
    echo "[INFO] Step 2.6: Skipped — deploy failed (exit=$DEPLOY_EXIT)"
fi

# ── Step 2.6b: DNS Update (Lesson 50) ────────────────────────────────────────
# Auto-update jobtrackerpro.ch A records to current LB IP.
# L50: SDK list_dns_domains() is broken — _update_dns.py uses raw REST.
# L50: Delete stale A records to avoid round-robin to dead IPs.
if [ "$DEPLOY_EXIT" -eq 0 ]; then
    LATEST_REPORT=$(find "$OUTPUTS_DIR" -name "deployment_report.json" | sort | tail -1)
    LB_IP=$(python3 -c "import json; d=json.load(open('$LATEST_REPORT')); print(d['resources']['ingress']['lb_ip'])" 2>/dev/null || echo "")
    if [ -n "$LB_IP" ]; then
        echo ""
        echo "============================================================"
        echo "  STEP 2.6b: DNS UPDATE → jobtrackerpro.ch → $LB_IP"
        echo "  (Lesson 50: auto-update A records, delete stale duplicates)"
        echo "============================================================"
        set +e
        python3 -X utf8 "$SCRIPT_DIR/_update_dns.py" "$LB_IP" 2>&1
        DNS_EXIT=$?
        set -e
        if [ $DNS_EXIT -ne 0 ]; then
            echo "[WARN] Step 2.6b: DNS update failed (exit=$DNS_EXIT) — check manually"
        else
            echo "[OK]   Step 2.6b: DNS updated → $LB_IP"
        fi
    else
        echo "[WARN] Step 2.6b: Could not extract LB_IP from deployment_report — DNS not updated"
    fi
fi

# ── Step 2.7: Post-Deploy Service Verification (Plan 125 Phase 2) ────────────
# 2.7a /health sweep — all 220 pods, 20 workers
# 2.7b Unit tests only (L49: integration/e2e require external deps not in pod)
if [ "$DEPLOY_EXIT" -eq 0 ] && [ "$SKIP_SERVICES" = "false" ]; then
    LATEST_KC=$(find "$OUTPUTS_DIR" -name "kubeconfig.yaml" | sort | tail -1)
    K8S_NS=$(grep 'k8s_namespace:' "$SCRIPT_DIR/config.yaml" | awk '{print $2}' | tr -d '[:space:]\r')
    HEALTH_REPORT="$OUTPUTS_DIR/health_${TS}.json"
    TEST_REPORT="$OUTPUTS_DIR/test_results_${TS}.json"

    if [ -z "$LATEST_KC" ]; then
        echo "[WARN] Step 2.7: No kubeconfig — skipping"
    else
        echo ""
        echo "============================================================"
        echo "  STEP 2.7a: SERVICE HEALTH SWEEP (/health on all pods)"
        echo "============================================================"
        set +e
        python3 -X utf8 "$SCRIPT_DIR/service_health_check.py" \
            --kubeconfig    "${LATEST_KC}" \
            --namespace     "${K8S_NS}" \
            --workers       20 \
            --timeout       10 \
            --fail-threshold 0.80 \
            --output-json   "${HEALTH_REPORT}" 2>&1
        HEALTH_EXIT=$?
        set -e
        echo ""
        if [ $HEALTH_EXIT -ne 0 ]; then
            echo "[WARN] Step 2.7a: Below 80% threshold (exit=$HEALTH_EXIT) — Report: $HEALTH_REPORT"
        else
            echo "[OK]   Step 2.7a: /health sweep PASSED"
        fi

        echo ""
        echo "============================================================"
        echo "  STEP 2.7b: IN-POD UNIT TEST RUNNER"
        echo "  Suites: unit only (L49: integration/e2e/perf/security/user_stories"
        echo "          require external deps not available via kubectl exec)"
        echo "  219 services via kubectl exec (20 parallel workers)"
        echo "============================================================"
        set +e
        python3 -X utf8 "$SCRIPT_DIR/run_service_tests.py" \
            --kubeconfig    "${LATEST_KC}" \
            --namespace     "${K8S_NS}" \
            --workers       20 \
            --suites        unit \
            --suite-timeout 180 \
            --fail-threshold 0.80 \
            --output-json   "${TEST_REPORT}" 2>&1
        TEST_EXIT=$?
        set -e
        echo ""
        if [ $TEST_EXIT -ne 0 ]; then
            echo "[WARN] Step 2.7b: Below 80% pass threshold (exit=$TEST_EXIT) — Report: $TEST_REPORT"
        else
            echo "[OK]   Step 2.7b: Unit tests PASSED"
        fi

        echo ""
        echo "============================================================"
        echo "  STEP 2.7c: WEBSITE REACHABILITY CHECK (L50)"
        echo "  DNS propagation → TLS cert issuance → HTTP(S) response"
        echo "============================================================"
        DOMAIN="jobtrackerpro.ch"
        LB_IP_CHECK=$(python3 -c "import json; d=json.load(open('$(find "$OUTPUTS_DIR" -name deployment_report.json | sort | tail -1)')); print(d['resources']['ingress']['lb_ip'])" 2>/dev/null || echo "")
        WEB_EXIT=0

        if [ -z "$LB_IP_CHECK" ]; then
            echo "[WARN] Step 2.7c: Could not determine LB IP — skipping"
        else
            # 1. DNS propagation: wait up to 5 min for domain to resolve to LB IP
            echo "[2.7c] Checking DNS: $DOMAIN → $LB_IP_CHECK ..."
            DNS_OK=false
            for i in $(seq 1 30); do
                RESOLVED=$(python3 -c "
import urllib.request, json
try:
    with urllib.request.urlopen('https://dns.google/resolve?name=$DOMAIN&type=A', timeout=5) as r:
        ans = json.load(r).get('Answer', [])
        ips = [a['data'] for a in ans if a.get('type') == 1]
        print(','.join(ips))
except: print('')
" 2>/dev/null)
                if echo "$RESOLVED" | grep -q "$LB_IP_CHECK"; then
                    echo "[2.7c] DNS OK: $DOMAIN → $RESOLVED"
                    DNS_OK=true
                    break
                fi
                echo "[2.7c] DNS not yet propagated (got: ${RESOLVED:-none}) — retry $i/30 ..."
                sleep 10
            done
            if [ "$DNS_OK" = "false" ]; then
                echo "[WARN] Step 2.7c: DNS did not propagate to $LB_IP_CHECK within 5 min"
                WEB_EXIT=1
            fi

            # 2. TLS cert: wait up to 5 min; if challenge invalid, auto-retry (L52)
            # L52: Let's Encrypt secondary validation can hit old LB IP if DNS was stale
            #      at challenge time → challenge marked invalid → cert never issues.
            #      Fix: detect invalid challenge, delete cert to force cert-manager retry.
            echo "[2.7c] Checking TLS cert issuance ..."
            CERT_OK=false
            CERT_RETRIED=false
            for i in $(seq 1 30); do
                CERT_STATUS=$(KUBECONFIG="$LATEST_KC" kubectl get secret jobtrackerpro-ch-tls \
                    -n "$K8S_NS" -o jsonpath='{.type}' 2>/dev/null || echo "")
                if [ "$CERT_STATUS" = "kubernetes.io/tls" ]; then
                    echo "[2.7c] TLS cert issued: jobtrackerpro-ch-tls"
                    CERT_OK=true
                    break
                fi
                # Check for invalid ACME challenge — auto-retry once (L52)
                INVALID_CHALLENGE=$(KUBECONFIG="$LATEST_KC" kubectl get challenges -n "$K8S_NS" \
                    -o jsonpath='{range .items[?(@.status.state=="invalid")]}{.metadata.name}{"\n"}{end}' \
                    2>/dev/null | head -1)
                if [ -n "$INVALID_CHALLENGE" ] && [ "$CERT_RETRIED" = "false" ]; then
                    echo "[2.7c] L52: Invalid ACME challenge detected — deleting cert to force retry..."
                    KUBECONFIG="$LATEST_KC" kubectl delete certificate jobtrackerpro-ch-tls \
                        -n "$K8S_NS" 2>/dev/null || true
                    KUBECONFIG="$LATEST_KC" kubectl annotate ingress docker-jtp-ingress \
                        -n "$K8S_NS" cert-manager.io/retry="$(date +%s)" --overwrite 2>/dev/null || true
                    CERT_RETRIED=true
                    echo "[2.7c] L52: Cert retry triggered — waiting for new challenge..."
                    sleep 15
                    continue
                fi
                echo "[2.7c] Cert not ready yet (status: ${CERT_STATUS:-missing}) — retry $i/30 ..."
                sleep 10
            done
            if [ "$CERT_OK" = "false" ]; then
                echo "[WARN] Step 2.7c: TLS cert not issued within 5 min — HTTP-only check"
            fi

            # 3. Website reachability: HTTP then HTTPS
            echo "[2.7c] Checking website reachability ..."
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                -H "Host: $DOMAIN" "http://$LB_IP_CHECK/" --max-time 10 2>/dev/null || echo "000")
            echo "[2.7c] HTTP response: $HTTP_CODE"

            if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "308" ] || [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
                echo "[2.7c] HTTP OK ($HTTP_CODE)"
                if [ "$CERT_OK" = "true" ]; then
                    HTTPS_CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
                        "https://$DOMAIN/" --max-time 10 2>/dev/null || echo "000")
                    echo "[2.7c] HTTPS response: $HTTPS_CODE"
                    if [ "$HTTPS_CODE" = "200" ]; then
                        echo "[OK]   Step 2.7c: $DOMAIN is live and serving HTTPS ✓"
                    else
                        echo "[WARN] Step 2.7c: HTTPS returned $HTTPS_CODE (cert may still be propagating)"
                    fi
                else
                    echo "[OK]   Step 2.7c: $DOMAIN is HTTP-reachable (HTTPS pending cert)"
                fi
            else
                echo "[WARN] Step 2.7c: Website not reachable — HTTP $HTTP_CODE"
                WEB_EXIT=1
            fi
        fi

        if [ $WEB_EXIT -ne 0 ]; then
            echo "[WARN] Step 2.7c: Website check FAILED — manual investigation required"
        fi

        # ── Step 2.7d: External CI/CD test runner (L53) ──────────────────────
        # Runs integration, e2e, security, user_stories for all 219 services
        # against the live gateway. Unit tests stay in-pod (L49).
        if [ "$WEB_EXIT" -eq 0 ]; then
            echo ""
            echo "  STEP 2.7d: EXTERNAL CI/CD TESTS (L53)"
            echo "  ----------------------------------------"
            EXT_REPORT="${OUTPUTS_DIR}/external_tests_${TS}.json"
            python3 -X utf8 "$SCRIPT_DIR/run_external_tests.py"                 --gateway "https://${DOMAIN}"                 --output  "$EXT_REPORT"                 --workers 20
            EXT_EXIT=$?
            if [ $EXT_EXIT -eq 0 ]; then
                echo "[OK]   Step 2.7d: External CI/CD tests PASSED — Report: $EXT_REPORT"
            else
                echo "[WARN] Step 2.7d: External CI/CD tests had failures — Report: $EXT_REPORT"
            fi
        else
            echo "[INFO] Step 2.7d: Skipped — website not reachable"
        fi
    fi
else
    if [ "$DEPLOY_EXIT" -ne 0 ]; then
        echo "[INFO] Step 2.7: Skipped — deploy failed (exit=$DEPLOY_EXIT)"
    else
        echo "[INFO] Step 2.7: Skipped (--skip-services)"
    fi
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
HEALTH_REPORT_FINAL="${OUTPUTS_DIR}/health_${TS}.json"
TEST_REPORT_FINAL="${OUTPUTS_DIR}/test_results_${TS}.json"

python3 -X utf8 - <<PYEOF
import json, subprocess, sys
from datetime import datetime
from pathlib import Path

ts           = "$TS"
log_file     = "$LOG_FILE"
deploy_exit  = $DEPLOY_EXIT
latest_rpt   = "$LATEST_REPORT"
out_file     = "$POSTMORTEM_FILE"
health_rpt   = "$HEALTH_REPORT_FINAL"
test_rpt     = "$TEST_REPORT_FINAL"

pm = {
    "timestamp":          ts,
    "completed_at":       datetime.now().isoformat(),
    "deployment_success": deploy_exit == 0,
    "exit_code":          deploy_exit,
    "log_file":           log_file,
    "deployment_report":  None,
    "health_report":      None,
    "test_report":        None,
    "issues_detected":    [],
    "git_commit":         "",
    "plan":               "125",
}

if latest_rpt and Path(latest_rpt).exists():
    try:
        pm["deployment_report"] = json.loads(Path(latest_rpt).read_text())
    except Exception as e:
        pm["issues_detected"].append(f"Could not parse deployment report: {e}")

if Path(health_rpt).exists():
    try:
        pm["health_report"] = json.loads(Path(health_rpt).read_text()).get("summary", {})
    except Exception:
        pass

if Path(test_rpt).exists():
    try:
        pm["test_report"] = json.loads(Path(test_rpt).read_text()).get("summary", {})
    except Exception:
        pass

if Path(log_file).exists():
    log_content = Path(log_file).read_text(errors="replace")
    for pattern, label in [
        ("FAIL",          "Pipeline stage FAILED"),
        ("CrashLoopBack", "Pod CrashLoopBackOff detected"),
        ("ErrImagePull",  "Image pull failure"),
        ("HTTP 500",      "Exoscale API 500 error"),
        ("conflict",      "API conflict (409)"),
        ("WARN",          "Pipeline warnings present"),
    ]:
        count = log_content.count(pattern)
        if count > 0:
            pm["issues_detected"].append(f"{label} ({count} occurrences)")

try:
    result = subprocess.run(["git", "log", "--oneline", "-1"],
        capture_output=True, text=True, cwd="$SCRIPT_DIR")
    pm["git_commit"] = result.stdout.strip()
except Exception:
    pass

Path(out_file).write_text(json.dumps(pm, indent=2))
print(f"[POSTMORTEM] Report: {out_file}")
if pm["issues_detected"]:
    print(f"[POSTMORTEM] Issues ({len(pm['issues_detected'])}):")
    for issue in pm["issues_detected"]:
        print(f"  - {issue}")
if pm["deployment_success"]:
    print("[POSTMORTEM] STATUS: DEPLOYMENT SUCCESS")
else:
    print(f"[POSTMORTEM] STATUS: DEPLOYMENT FAILED (exit={deploy_exit})")
PYEOF

exit $DEPLOY_EXIT
