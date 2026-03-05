"""Inject Step 2.5b ResourceQuota removal into run_deploy.sh."""
p = '/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/run_deploy.sh'
t = open(p).read()

# 1. Add CPU budget preflight check (Check 11) after Check 10
old_check10_end = '''# Check 10: gen_service_manifests.py exists (Plan 125 Phase 1)
if [ -f "$SCRIPT_DIR/gen_service_manifests.py" ]; then
    echo "  [PASS] gen_service_manifests.py: found (Plan 125 Stage 5e)"
else
    echo "  [WARN] gen_service_manifests.py: NOT found — Stage 5e will be skipped"
    SKIP_SERVICES=true
fi

echo ""'''

new_check10_end = '''# Check 10: gen_service_manifests.py exists (Plan 125 Phase 1)
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

echo ""'''

# 2. Add Step 2.5b ResourceQuota removal before manifest apply
old_apply = '''        if [ -z "$KUBECONFIG_PATH" ]; then
            echo "[WARN] Stage 5e: No kubeconfig found in $OUTPUTS_DIR — skipping service pod deployment"
        else'''

new_apply = '''        if [ -z "$KUBECONFIG_PATH" ]; then
            echo "[WARN] Stage 5e: No kubeconfig found in $OUTPUTS_DIR — skipping service pod deployment"
        else
            # ── Step 2.5b: Remove ResourceQuota (Lesson 34b) ────────────────
            echo "[$(date '+%H:%M:%S')] Step 2.5b: Removing ResourceQuota (Lesson 34b — prevents 220-pod scheduling)"
            kubectl delete resourcequota --all -n "${K8S_NS}" \\
                --kubeconfig="${KUBECONFIG_PATH}" --ignore-not-found=true 2>&1 || true
            echo "[$(date '+%H:%M:%S')] OK  Step 2.5b: ResourceQuota cleared"
            echo ""'''

if old_check10_end in t:
    t = t.replace(old_check10_end, new_check10_end, 1)
    print('CPU_budget_check_injected OK')
else:
    print('WARN: check10 pattern not found — skipping CPU budget check injection')

if old_apply in t:
    t = t.replace(old_apply, new_apply, 1)
    print('ResourceQuota_step_injected OK')
else:
    print('WARN: apply pattern not found — skipping ResourceQuota step injection')

open(p, 'w').write(t)
print('run_deploy.sh updated')
