#!/usr/bin/env python3
"""
L46 Patch: gen_service_manifests.py — define DEPLOY_RESOURCES module constant.

Root cause: The L43 patch added `result = DEPLOY_RESOURCES.copy()` in
load_service_resources() but forgot to define DEPLOY_RESOURCES at module
level, causing NameError when Stage 5e runs gen_service_manifests.py.

Fix: Insert DEPLOY_RESOURCES dict constant immediately after SERVICES_DIR.
"""
import sys
from pathlib import Path

TARGET = Path(__file__).parent / "gen_service_manifests.py"
text   = TARGET.read_text(encoding="utf-8")

OLD = 'SERVICES_DIR = SCRIPT_DIR / "service" / "services"'
NEW = '''\
SERVICES_DIR = SCRIPT_DIR / "service" / "services"

# L46: deploy-time safe resource defaults (see L43 for rationale).
# Requests are kept small so all 219 services fit a 3-node cluster.
# Limits are generous — individual services may burst, but won't starve others.
DEPLOY_RESOURCES: dict = {
    "cpu_request":    "10m",
    "memory_request": "64Mi",
    "cpu_limit":      "500m",
    "memory_limit":   "256Mi",
}'''

if OLD not in text:
    print(f"ERROR: anchor not found in {TARGET.name} — aborting")
    sys.exit(1)

patched = text.replace(OLD, NEW, 1)
TARGET.write_text(patched, encoding="utf-8")
print(f"OK  patched {TARGET} ({TARGET.stat().st_size} bytes)")
print(f"    added DEPLOY_RESOURCES after SERVICES_DIR (line 53)")
