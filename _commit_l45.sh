#!/bin/bash
set -e
cd /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit

git add run_service_tests.py _patch_test_workdir.py outputs/test_results_unit_20260306.json

cat > /tmp/commit_l45.txt << 'EOF'
Lesson 45: Fix pytest working directory — 206/219 services pass unit tests

Root cause: run_suite_in_pod() ran `python -m pytest tests/unit/` relative to
/app, but tests live at /app/services/{SERVICE_NAME}/tests/unit/.

Fix: Use `sh -c "cd /app/services/{service_name} && python -m pytest tests/..."` 
and pass svc_name (from SERVICE_NAME env var) to run_suite_in_pod().

Test results (unit suite, 219 services):
  ✅ 206 PASS  (94.1% — above 80% threshold)
  ❌ 13 FAIL
     - 11 *-frontend services: test_endpoint_get_root schema mismatch
     - 2 services (configuration_management, template_ecosystem_manager):
       missing endpoints /settings/reset, /features, /features/{name}
  Individual tests: 2785 passed / 29 failed

Report: outputs/test_results_unit_20260306.json
EOF

git commit -F /tmp/commit_l45.txt
