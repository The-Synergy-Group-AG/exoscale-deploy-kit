#!/usr/bin/env python3
"""
LESSON 31: Stage 5c applies Ingress YAML to namespace 'exo-jtp-prod' BEFORE
Stage 5 (K8s manifests) has created that namespace, causing:
  Error from server (NotFound): namespaces "exo-jtp-prod" not found

Fix: Add `kubectl create namespace <namespace>` (idempotent) inside
stage_5c_ingress_tls() immediately before the ingress YAML apply.

Run once: python3 _fix_lesson_31.py
"""
from pathlib import Path

TARGET = Path(__file__).parent / "deploy_pipeline.py"
src = TARGET.read_text(encoding="utf-8")

# ── LESSON 31 fix ─────────────────────────────────────────────────────────────
OLD = '    _run(["kubectl", "--insecure-skip-tls-verify", "apply", "-f", ingress_file])\n    ok(f"ClusterIssuer + Ingress applied (manifest: {ingress_file})")'

NEW = (
    '    # LESSON 31: Ensure application namespace exists before applying ingress YAML\n'
    '    # Stage 5c runs before Stage 5 (K8s manifests) which normally creates namespaces.\n'
    '    try:\n'
    '        _ns_r = subprocess.run(\n'
    '            ["kubectl", "--insecure-skip-tls-verify", "create", "namespace", namespace],\n'
    '            env=env, check=False, capture_output=True, text=True\n'
    '        )\n'
    '        if _ns_r.returncode == 0:\n'
    '            ok(f"Namespace pre-created for ingress: {namespace}")\n'
    '        elif "already exists" in (_ns_r.stderr or ""):\n'
    '            log(f"Namespace already exists: {namespace} (OK)")\n'
    '        else:\n'
    '            warn(f"Namespace create note: {_ns_r.stderr.strip() or _ns_r.stdout.strip()}")\n'
    '    except Exception as _ns_e:\n'
    '        warn(f"Namespace pre-create error (non-fatal): {_ns_e}")\n'
    '\n'
    '    _run(["kubectl", "--insecure-skip-tls-verify", "apply", "-f", ingress_file])\n'
    '    ok(f"ClusterIssuer + Ingress applied (manifest: {ingress_file})")'
)

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    TARGET.write_text(src, encoding="utf-8")
    print(f"LESSON 31 fix applied. New file size: {len(src)} bytes")
elif "LESSON 31" in src:
    print("Already patched — nothing to do.")
else:
    print("ERROR: anchor not found. Manual patch required.")
    exit(1)
