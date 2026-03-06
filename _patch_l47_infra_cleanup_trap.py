#!/usr/bin/env python3
"""
L47 Patch: run_deploy.sh — add infrastructure cleanup trap.

ROOT CAUSE (Lesson 47):
  deploy_pipeline.py (Step 2) exits 0 when infrastructure is successfully
  created (SKS cluster, nodepool, SG, LB).  run_deploy.sh then runs
  gen_service_manifests.py (Step 2.5) and other post-pipeline steps.

  If ANY post-pipeline step fails (e.g. the L46 NameError in
  gen_service_manifests.py), run_deploy.sh exits with an error but there is
  NO cleanup handler.  The cloud resources from Step 2 are left running,
  accumulating cost and causing pool-name conflicts on the next run.

  The existing `trap '' HUP PIPE` only suppresses HUP/PIPE signals.
  There is no `trap ... EXIT` or `trap ... ERR` for post-pipeline failures.

FIX:
  1. Add INFRA_CREATED=false guard variable before Step 2.
  2. Set INFRA_CREATED=true after Step 2 exits 0.
  3. Add `trap cleanup_infra EXIT` that calls `python3 teardown.py --force`
     if INFRA_CREATED=true AND the overall exit code is non-zero.

This ensures any failed deployment that created real cloud infrastructure
will always clean itself up, preventing orphaned clusters.
"""
import sys
from pathlib import Path

TARGET = Path(__file__).parent / "run_deploy.sh"
text   = TARGET.read_text(encoding="utf-8")

# ── Patch 1: add cleanup_infra function + EXIT trap after HUP/PIPE trap ──
OLD_TRAP = "trap '' HUP PIPE"
NEW_TRAP = """\
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
trap cleanup_infra EXIT"""

# ── Patch 2: set INFRA_CREATED=true after Step 2 exits 0 ─────────────────
OLD_STEP2_END = """\
echo ""
echo "============================================================"
echo "  STEP 2 COMPLETED — Exit code: $DEPLOY_EXIT"
echo "============================================================"
echo ""

# ── Step 2.5: Stage 5e/5f — Per-Service Pod Deployment (Plan 125) ─────────
if [ "$SKIP_SERVICES" = "false" ] && [ "$DEPLOY_EXIT" -eq 0 ]; then"""

NEW_STEP2_END = """\
echo ""
echo "============================================================"
echo "  STEP 2 COMPLETED — Exit code: $DEPLOY_EXIT"
echo "============================================================"
echo ""

# L47: Mark infra as created so cleanup_infra trap can fire if later steps fail.
if [ "$DEPLOY_EXIT" -eq 0 ]; then
    INFRA_CREATED=true
fi

# ── Step 2.5: Stage 5e/5f — Per-Service Pod Deployment (Plan 125) ─────────
if [ "$SKIP_SERVICES" = "false" ] && [ "$DEPLOY_EXIT" -eq 0 ]; then"""

errors = []
if OLD_TRAP not in text:
    errors.append(f"ERROR: HUP/PIPE trap anchor not found")
if OLD_STEP2_END not in text:
    errors.append(f"ERROR: Step 2 COMPLETED anchor not found")

if errors:
    for e in errors:
        print(e)
    sys.exit(1)

patched = text.replace(OLD_TRAP, NEW_TRAP, 1)
patched = patched.replace(OLD_STEP2_END, NEW_STEP2_END, 1)
TARGET.write_text(patched, encoding="utf-8")

lines = patched.count('\n')
print(f"OK  patched {TARGET.name} ({lines} lines)")
print(f"    + cleanup_infra() function with EXIT trap")
print(f"    + INFRA_CREATED=true set after DEPLOY_EXIT=0")
print(f"    Orphaned clusters will now auto-teardown on any post-pipeline failure")
