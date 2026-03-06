#!/usr/bin/env python3
"""
Patch 13 failing services in-pod (Option A quick fix).

Backend (2 services):  rename async def config(): → get_config():
Frontend (11 services): add "endpoint": "/" to first GET / return dict
"""

import subprocess

KUBECONFIG = "outputs/20260306_104844/kubeconfig.yaml"
NAMESPACE  = "exo-jtp-prod"

BACKEND_SERVICES = [
    ("configuration-management",   "configuration_management"),
    ("template-ecosystem-manager", "template_ecosystem_manager"),
]

FRONTEND_SERVICES = [
    "ai-conversation-frontend",
    "credits-redemption-frontend",
    "frontend-api-gateway",
    "gamification-frontend",
    "interview-prep-frontend",
    "networking-frontend",
    "notifications-center-frontend",
    "onboarding-frontend",
    "payment-billing-frontend",
    "rav-compliance-frontend",
    "shared-components-library-frontend",
]

# ── helpers ──────────────────────────────────────────────────────────────────

def kubectl_exec(deployment, cmd):
    full = [
        "kubectl",
        f"--kubeconfig={KUBECONFIG}",
        "--insecure-skip-tls-verify",
        f"-n={NAMESPACE}",
        "exec", f"deployment/{deployment}",
        "--", "sh", "-c", cmd,
    ]
    r = subprocess.run(full, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

# ── backend fix ───────────────────────────────────────────────────────────────

def patch_backend(deployment, svc_dir):
    path = f"/app/services/{svc_dir}/main.py"
    rc, out, err = kubectl_exec(deployment,
        f"sed -i 's/async def config():/async def get_config():/g' {path}")
    if rc == 0:
        print(f"  ✅ {deployment} — renamed config() → get_config()")
    else:
        print(f"  ❌ {deployment} — FAILED: {err}")
    return rc == 0

# ── frontend fix ──────────────────────────────────────────────────────────────

def patch_frontend(deployment):
    """
    The first GET / handler returns a dict that has:
        "type": "frontend",
    We add "endpoint": "/" right after it using sed (first occurrence only).
    sed '0,/pattern/s/pattern/replacement/' replaces first occurrence in file.
    """
    path = f"/app/services/{deployment}/main.py"
    # Replace first occurrence of '"type": "frontend",'  →  add endpoint key
    sed_cmd = (
        "sed -i "
        "'" + r'0,/"type": "frontend",/s/"type": "frontend",/"type": "frontend", "endpoint": "\/",/' + "'"
        f" {path}"
    )
    rc, out, err = kubectl_exec(deployment, sed_cmd)
    if rc == 0:
        # Verify the key is now present in the file
        rc2, out2, _ = kubectl_exec(deployment,
            f"grep -c '\"endpoint\": \"/\"' {path}")
        count = int(out2) if out2.isdigit() else 0
        if count >= 1:
            print(f"  ✅ {deployment} — added endpoint key ({count} occurrences)")
        else:
            print(f"  ⚠️  {deployment} — sed ran but key not found (may already differ)")
    else:
        print(f"  ❌ {deployment} — FAILED: {err}")
    return rc == 0

# ── quick per-service verification ───────────────────────────────────────────

def verify(deployment, svc_dir, test_name):
    cmd = (
        f"cd /app/services/{svc_dir} && "
        f"python -m pytest tests/unit/ -k {test_name} "
        f"--tb=line --no-header -q --color=no 2>&1 | tail -2"
    )
    rc, out, err = kubectl_exec(deployment, cmd)
    passed = "passed" in out and "failed" not in out
    print(f"    {'✅' if passed else '❌'} verify [{test_name}]: {out}")
    return passed

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n── PATCHING BACKEND SERVICES ────────────────────────────────────")
    for deployment, svc_dir in BACKEND_SERVICES:
        ok = patch_backend(deployment, svc_dir)
        if ok:
            verify(deployment, svc_dir, "test_root_endpoint")

    print("\n── PATCHING FRONTEND SERVICES ───────────────────────────────────")
    for svc in FRONTEND_SERVICES:
        ok = patch_frontend(svc)
        if ok:
            verify(svc, svc, "test_endpoint_get_root")

    print("\n── DONE ─────────────────────────────────────────────────────────")

if __name__ == "__main__":
    main()
