#!/usr/bin/env python3
"""Check and fix NLB target-port / healthcheck-port mismatch."""
import os, sys, json
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

from exoscale.api.v2 import Client

NLB_IP = "159.100.248.98"
# nginx-ingress NodePorts (from kubectl get svc)
HTTP_NODEPORT  = 30095  # port 80 → 30095/TCP
HTTPS_NODEPORT = 31473  # port 443 → 31473/TCP

ZONE = "ch-dk-2"
c = Client(EXO_KEY, EXO_SECRET, zone=ZONE)

# Find our NLB
nlbs = c.list_load_balancers().get("load-balancers", [])
target_nlb = next((n for n in nlbs if n.get("ip") == NLB_IP), None)
if not target_nlb:
    log(f"ERROR: NLB with IP {NLB_IP} not found!"); sys.exit(1)

nlb_id   = target_nlb["id"]
nlb_name = target_nlb["name"]
log(f"Found NLB '{nlb_name}' ({nlb_id[:8]})")

detail = c.get_load_balancer(id=nlb_id)
log(f"\nFull NLB services:")
log(json.dumps(detail.get("services", []), indent=2))
