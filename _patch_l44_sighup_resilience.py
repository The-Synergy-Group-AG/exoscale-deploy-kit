#!/usr/bin/env python3
"""
L44 Patch: run_deploy.sh — ignore SIGHUP/SIGPIPE so Stage 5e batch apply
survives when the hosting terminal (e.g. Cline background terminal) closes
or times out mid-run.

Without this, the SIGHUP delivered to the bash process kills the script after
the 30-second Cline terminal timeout, leaving Stage 5e incomplete at whatever
batch it was processing (observed: killed after ~107/219 services).

Fix: insert `trap '' HUP PIPE` immediately after `set -euo pipefail`.
"""
import sys
from pathlib import Path

TARGET = Path(__file__).parent / "run_deploy.sh"
text   = TARGET.read_text(encoding="utf-8")

OLD = "set -euo pipefail\n"
NEW = (
    "set -euo pipefail\n"
    "# L44: ignore SIGHUP/SIGPIPE — survive terminal close / Cline background timeout\n"
    "trap '' HUP PIPE\n"
)

if OLD not in text:
    print("ERROR: 'set -euo pipefail' not found in run_deploy.sh — aborting")
    sys.exit(1)

# Only patch the first occurrence
patched = text.replace(OLD, NEW, 1)
TARGET.write_text(patched, encoding="utf-8")
print(f"OK  patched {TARGET} ({TARGET.stat().st_size} bytes)")
