#!/usr/bin/env python3
"""
Patch run_deploy.sh — Add Step 2.7d: External CI/CD test runner (L53).
Inserts after Step 2.7c (website reachability) and before deployment banner.
"""
from pathlib import Path

target = Path(__file__).parent / "run_deploy.sh"
text   = target.read_text()

# ── Insertion point ──────────────────────────────────────────────────────────
# Insert the Step 2.7d block between the closing `fi` of the
# "if [ $WEB_EXIT -ne 0 ]" block and the "else" clause that covers
# DEPLOY_EXIT != 0 / --skip-services.
# Anchor: the two consecutive lines that close Step 2.7c and open the else.

OLD = '''\
        if [ $WEB_EXIT -ne 0 ]; then
            echo "[WARN] Step 2.7c: Website check FAILED — manual investigation required"
        fi
    fi
else
    if [ "$DEPLOY_EXIT" -ne 0 ]; then
        echo "[INFO] Step 2.7: Skipped — deploy failed (exit=$DEPLOY_EXIT)"
    else
        echo "[INFO] Step 2.7: Skipped (--skip-services)"
    fi
fi'''

NEW = '''\
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
            python3 -X utf8 "$SCRIPT_DIR/run_external_tests.py" \
                --gateway "https://${DOMAIN}" \
                --output  "$EXT_REPORT" \
                --workers 20
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
fi'''

if OLD not in text:
    print("ERROR: anchor not found in run_deploy.sh — check the script manually")
    raise SystemExit(1)

patched = text.replace(OLD, NEW, 1)
target.write_text(patched)
print(f"Patched: {target}")
print(f"Line count: {len(patched.splitlines())}")
