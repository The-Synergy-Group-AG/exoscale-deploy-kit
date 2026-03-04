#!/usr/bin/env python3
"""Dump all rules for jtp-test1-sg-085857 and check NodePort range."""
import os, sys, json
from pathlib import Path
from datetime import datetime

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

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

from exoscale.api.v2 import Client
c = Client(EXO_KEY, EXO_SECRET, zone="ch-dk-2")

sgs = c.list_security_groups().get("security-groups", [])
for sg in sgs:
    if "jtp-test1" in sg.get("name", ""):
        log(f"SG: {sg['name']} ({sg['id'][:8]})")
        rules = sg.get("rules", [])
        log(f"Total rules: {len(rules)}")
        for r in rules:
            flow    = r.get("flow-direction", "?")
            proto   = r.get("protocol", "?")
            network = r.get("network", r.get("security-group", {}).get("name", "SG"))
            sport   = r.get("start-port", "*")
            eport   = r.get("end-port", "*")
            desc    = r.get("description", "")
            print(f"  {flow:8} {proto:5} {str(network):20} :{sport}-{eport}  {desc}")

        # Check NodePort range
        has_nodeport = any(
            r.get("flow-direction") == "ingress" and
            r.get("protocol") == "tcp" and
            r.get("start-port", 99999) <= 30095 <= r.get("end-port", 0) and
            r.get("network") in ("0.0.0.0/0", "::/0")
            for r in rules
        )
        log(f"\nNodePort 30095 accessible from 0.0.0.0/0: {'YES' if has_nodeport else 'NO - MISSING RULE!'}")

        if not has_nodeport:
            log("→ Adding TCP 30000-32767 ingress from 0.0.0.0/0...")
            try:
                c.add_rule_to_security_group(
                    id=sg["id"],
                    flow_direction="ingress",
                    protocol="tcp",
                    network="0.0.0.0/0",
                    start_port=30000,
                    end_port=32767,
                    description="NodePort services (NLB backend access)",
                )
                log("  ✓ NodePort rule added!")
            except Exception as e:
                if "already" in str(e).lower():
                    log("  already exists — OK")
                else:
                    log(f"  FAILED: {e}")
