#!/usr/bin/env python3
"""
Patch run_service_tests.py to fix the pytest working directory.
Problem: pytest runs `tests/unit/` relative to /app but tests are at
         /app/services/{SERVICE_NAME}/tests/unit/
Fix 1:   run_suite_in_pod() gets a new `service_name` param and uses
         sh -c "cd /app/services/{name} && python -m pytest tests/{suite}/ ..."
Fix 2:   call site passes svc_name to run_suite_in_pod()
"""
import re

path = '/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/run_service_tests.py'

with open(path) as f:
    src = f.read()

# ── Fix 1: function signature ────────────────────────────────────────────────
OLD_SIG = (
    "def run_suite_in_pod(kubeconfig: str, namespace: str, pod_name: str,\n"
    "                     suite: str, timeout: int = 120) -> dict:"
)
NEW_SIG = (
    "def run_suite_in_pod(kubeconfig: str, namespace: str, pod_name: str,\n"
    "                     suite: str, service_name: str = \"\",\n"
    "                     timeout: int = 120) -> dict:"
)
assert OLD_SIG in src, "ERROR: old signature not found"
src = src.replace(OLD_SIG, NEW_SIG, 1)
print("Fix 1: function signature updated")

# ── Fix 2: cmd construction — replace with sh -c cd && pytest ───────────────
OLD_CMD = (
    "    cmd = [\n"
    "        \"kubectl\", \"exec\", \"-n\", namespace,\n"
    "        \"--kubeconfig\", kubeconfig,\n"
    "        pod_name, \"--\",\n"
    "        \"python\", \"-m\", \"pytest\",\n"
    "        f\"tests/{suite}/\",\n"
    "        \"-q\", \"--tb=short\", \"--no-header\",\n"
    "        \"--color=no\",\n"
    "    ]"
)
NEW_CMD = (
    "    # Determine service directory inside the pod\n"
    "    svc_dir = f\"/app/services/{service_name}\" if service_name else \"/app\"\n"
    "    pytest_cmd = (\n"
    "        f\"cd {svc_dir} && \"\n"
    "        f\"python -m pytest tests/{suite}/ \"\n"
    "        \"-q --tb=short --no-header --color=no\"\n"
    "    )\n"
    "    cmd = [\n"
    "        \"kubectl\", \"exec\", \"-n\", namespace,\n"
    "        \"--kubeconfig\", kubeconfig,\n"
    "        pod_name, \"--\",\n"
    "        \"sh\", \"-c\", pytest_cmd,\n"
    "    ]"
)
assert OLD_CMD in src, "ERROR: old cmd construction not found"
src = src.replace(OLD_CMD, NEW_CMD, 1)
print("Fix 2: cmd construction updated to use sh -c cd && pytest")

# ── Fix 3: call site — pass svc_name ─────────────────────────────────────────
OLD_CALL = "        sr = run_suite_in_pod(kubeconfig, namespace, pod_name, suite, timeout=suite_timeout)"
NEW_CALL = "        sr = run_suite_in_pod(kubeconfig, namespace, pod_name, suite, service_name=svc_name, timeout=suite_timeout)"
assert OLD_CALL in src, "ERROR: old call site not found"
src = src.replace(OLD_CALL, NEW_CALL, 1)
print("Fix 3: call site updated to pass svc_name")

with open(path, 'w') as f:
    f.write(src)

print(f"\nPatched {path}")
import py_compile
py_compile.compile(path, doraise=True)
print("Syntax check: OK")

import subprocess
result = subprocess.run(['wc', '-l', path], capture_output=True, text=True)
print(f"Line count: {result.stdout.strip()}")
