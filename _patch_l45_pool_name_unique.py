#!/usr/bin/env python3
"""
L45 Patch: deploy_pipeline.py — add timestamp suffix to POOL_NAME.

Root cause: POOL_NAME = f"{_slug}-workers" is a FIXED name, unlike CLUSTER_N
which includes TS[-6:].  When a previous nodepool named 'jtp-test1-workers' is
still locked (Instance Pool locked in Exoscale console), creating a new pool
with the same name in a NEW cluster raises 409 "Nodepool name is already in use".

Fix: POOL_NAME = f"{_slug}-workers-{TS[-6:]}" — matches the CLUSTER_N pattern.
     Teardown discovers pools by cluster UUID (not by name), so this is safe.
"""
import sys
from pathlib import Path

TARGET = Path(__file__).parent / "deploy_pipeline.py"
text   = TARGET.read_text(encoding="utf-8")

OLD = 'POOL_NAME = f"{_slug}-workers"'
NEW = 'POOL_NAME = f"{_slug}-workers-{TS[-6:]}"  # L45: unique suffix like CLUSTER_N'

if OLD not in text:
    print(f"ERROR: SEARCH block not found in {TARGET.name} — aborting")
    sys.exit(1)

patched = text.replace(OLD, NEW, 1)
TARGET.write_text(patched, encoding="utf-8")
print(f"OK  patched {TARGET} ({TARGET.stat().st_size} bytes)")
print(f"    {OLD!r}")
print(f" -> {NEW!r}")
