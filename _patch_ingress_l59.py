#!/usr/bin/env python3
"""
Patch deploy_pipeline.py — Lesson 59 fix for nginx-ingress helm timeout.

BUG — helm pre-install webhook job times out on fresh Exoscale clusters:
  helm upgrade --install ingress-nginx ingress-nginx ... --wait --timeout 5m
  fails with: "failed pre-install: 1 error occurred: * timed out waiting for the condition"

ROOT CAUSE:
  ingress-nginx helm chart v4.11.3 installs an admission webhook certificate
  generator Job as a pre-install hook. On a fresh Exoscale SKS cluster the Job
  scheduler hasn't fully settled — the admission webhook call-back to the Job
  fails and helm times out at 5 min waiting for the pre-install hook to complete.

FIX:
  1. Add --set controller.admissionWebhooks.enabled=false to disable the
     pre-install admission webhook Job entirely. The admission webhook validates
     Ingress objects — it's useful but not required for our pipeline (the ingress
     objects are generated correctly by the pipeline itself).
  2. Raise --timeout from 5m to 10m as a belt-and-suspenders safety margin for
     environments where webhook is left enabled in the future.
"""

from pathlib import Path

DEPLOY = Path(__file__).parent / "deploy_pipeline.py"
src = DEPLOY.read_text(encoding="utf-8")
orig = src

OLD_HELM = (
    '    _run([\n'
    '        "helm", "upgrade", "--install", "ingress-nginx", "ingress-nginx",\n'
    '        "--repo", "https://kubernetes.github.io/ingress-nginx",\n'
    '        "--namespace", "ingress-nginx", "--create-namespace",\n'
    '        "--set", "controller.service.type=LoadBalancer",\n'
    '        "--version", "4.11.3", "--wait", "--timeout", "5m"\n'
    '    ])'
)

NEW_HELM = (
    '    _run([\n'
    '        "helm", "upgrade", "--install", "ingress-nginx", "ingress-nginx",\n'
    '        "--repo", "https://kubernetes.github.io/ingress-nginx",\n'
    '        "--namespace", "ingress-nginx", "--create-namespace",\n'
    '        "--set", "controller.service.type=LoadBalancer",\n'
    '        # LESSON 59: admissionWebhooks.enabled=false removes the pre-install\n'
    '        # webhook cert-generator Job that times out on fresh Exoscale clusters.\n'
    '        "--set", "controller.admissionWebhooks.enabled=false",\n'
    '        "--version", "4.11.3", "--wait", "--timeout", "10m"\n'
    '    ])'
)

assert OLD_HELM in src, "Old helm command not found — already patched?"
src = src.replace(OLD_HELM, NEW_HELM, 1)

DEPLOY.write_text(src, encoding="utf-8")

if src != orig:
    print("deploy_pipeline.py patched successfully (Lesson 59)")
    print("  FIX: admissionWebhooks.enabled=false (removes pre-install hook)")
    print("  FIX: --timeout raised from 5m to 10m")
else:
    print("ERROR: no changes made")
    raise SystemExit(1)
