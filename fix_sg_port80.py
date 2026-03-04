#!/usr/bin/env python3
"""Find cluster SG and ensure TCP 80/443 open from 0.0.0.0/0."""
import os, sys
from pathlib import Path
from datetime import datetime

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# CRLF-safe .env loader
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

EXO_KEY    = os.environ.get("EXO_API_KEY", "").strip()
EXO_SECRET = os.environ.get("EXO_API_SECRET", "").strip()

if not EXO_KEY:
    log("ERROR: EXO_API_KEY not found"); sys.exit(1)

log(f"API key: {EXO_KEY[:8]}...")

from exoscale.api.v2 import Client

for zone_name in ["ch-dk-2", "ch-gva-2"]:
    log(f"\n--- Zone: {zone_name} ---")
    try:
        c = Client(EXO_KEY, EXO_SECRET, zone=zone_name)
        sgs = c.list_security_groups().get("security-groups", [])
        log(f"  Found {len(sgs)} SGs")

        for sg in sgs:
            sg_id   = sg.get("id", "")
            sg_name = sg.get("name", "")
            rules   = sg.get("rules", [])

            has_80  = any(r.get("flow-direction") == "ingress" and
                          r.get("protocol") == "tcp" and
                          r.get("start-port", 999) <= 80 <= r.get("end-port", 0) and
                          r.get("network") == "0.0.0.0/0"
                          for r in rules)
            has_443 = any(r.get("flow-direction") == "ingress" and
                          r.get("protocol") == "tcp" and
                          r.get("start-port", 999) <= 443 <= r.get("end-port", 0) and
                          r.get("network") == "0.0.0.0/0"
                          for r in rules)

            log(f"  '{sg_name}' ({sg_id[:8]}): port80={'OK' if has_80 else 'MISSING'} port443={'OK' if has_443 else 'MISSING'}")

            if not has_80:
                log(f"    → Adding TCP 80 ingress 0.0.0.0/0...")
                try:
                    c.add_rule_to_security_group(
                        id=sg_id,
                        flow_direction="ingress",
                        protocol="tcp",
                        network="0.0.0.0/0",
                        start_port=80,
                        end_port=80,
                        description="HTTP ACME/LetsEncrypt",
                    )
                    log("    ✓ TCP 80 added!")
                except Exception as e2:
                    if "already" in str(e2).lower():
                        log("    already exists — OK")
                    else:
                        log(f"    FAILED: {e2}")

            if not has_443:
                log(f"    → Adding TCP 443 ingress 0.0.0.0/0...")
                try:
                    c.add_rule_to_security_group(
                        id=sg_id,
                        flow_direction="ingress",
                        protocol="tcp",
                        network="0.0.0.0/0",
                        start_port=443,
                        end_port=443,
                        description="HTTPS",
                    )
                    log("    ✓ TCP 443 added!")
                except Exception as e2:
                    if "already" in str(e2).lower():
                        log("    already exists — OK")
                    else:
                        log(f"    FAILED: {e2}")

    except Exception as e:
        log(f"  Zone {zone_name} error: {e}")

log("\nDone.")
