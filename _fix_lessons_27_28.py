#!/usr/bin/env python3
"""
LESSON 27: Add helm to Stage 0 preflight (fail fast instead of FileNotFoundError at Stage 5c)
LESSON 28: Fix DBaaS method typo  create_dbaas_service_mysq  →  create_dbaas_service_mysql
Run once: python3 _fix_lessons_27_28.py
"""
from pathlib import Path

TARGET = Path(__file__).parent / "deploy_pipeline.py"
src = TARGET.read_text(encoding="utf-8")
applied = []

# ─── LESSON 27: helm preflight check ──────────────────────────────────────────
OLD_KUBECTL_BLOCK = """\
    if r.returncode == 0:
        ok("kubectl: available")
    else:
        failures.append(
            "kubectl not found or not working -- "
            "install kubectl: https://kubernetes.io/docs/tasks/tools/"
        )

    if cfg.get("exo_key") and cfg.get("exo_secret"):"""

NEW_KUBECTL_BLOCK = """\
    if r.returncode == 0:
        ok("kubectl: available")
    else:
        failures.append(
            "kubectl not found or not working -- "
            "install kubectl: https://kubernetes.io/docs/tasks/tools/"
        )

    # LESSON 27: helm required for Stage 5c (ingress-nginx + cert-manager via Helm)
    # Without this check the pipeline crashes with FileNotFoundError mid-run (after
    # spending ~3 minutes provisioning Exoscale infrastructure).
    r_helm = subprocess.run(
        ["helm", "version", "--short"],
        capture_output=True, text=True, timeout=10
    )
    if r_helm.returncode == 0:
        helm_ver = r_helm.stdout.strip().split("\\n")[0]
        ok(f"helm: available ({helm_ver})")
    else:
        ingress_cfg = cfg.get("ingress", {})
        if ingress_cfg.get("enabled", False):
            failures.append(
                "helm not found -- required for Stage 5c (ingress-nginx + cert-manager). "
                "Install: curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"
            )
        else:
            warn("helm not found (OK -- ingress disabled, Stage 5c will be skipped)")

    if cfg.get("exo_key") and cfg.get("exo_secret"):"""

if OLD_KUBECTL_BLOCK in src:
    src = src.replace(OLD_KUBECTL_BLOCK, NEW_KUBECTL_BLOCK, 1)
    applied.append("LESSON 27: helm preflight check added")
else:
    print("  WARN: LESSON 27 anchor not found — already patched or source changed")

# ─── LESSON 28: DBaaS method name typo ────────────────────────────────────────
OLD_DBAAS = "            c.create_dbaas_service_mysq("
NEW_DBAAS  = "            c.create_dbaas_service_mysql(  # LESSON 28: was 'mysq' (typo fixed)"

if OLD_DBAAS in src:
    src = src.replace(OLD_DBAAS, NEW_DBAAS, 1)
    applied.append("LESSON 28: DBaaS typo fixed (mysq → mysql)")
else:
    print("  WARN: LESSON 28 anchor not found — already patched or source changed")

TARGET.write_text(src, encoding="utf-8")
print(f"Applied {len(applied)} fix(es):")
for fix in applied:
    print(f"  - {fix}")
print(f"New file size: {len(src)} bytes")
