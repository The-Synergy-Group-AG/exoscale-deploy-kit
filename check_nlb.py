#!/usr/bin/env python3
"""Check Exoscale NLB configuration and ACLs."""
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

from exoscale.api.v2 import Client

TARGET_IP = "159.100.248.98"

for zone_name in ["ch-dk-2", "ch-gva-2"]:
    log(f"\n--- Zone: {zone_name} ---")
    try:
        c = Client(EXO_KEY, EXO_SECRET, zone=zone_name)
        nlbs = c.list_load_balancers().get("load-balancers", [])
        log(f"  Found {len(nlbs)} NLBs")
        for nlb in nlbs:
            nlb_ip = nlb.get("ip", "")
            nlb_name = nlb.get("name", "")
            nlb_id = nlb.get("id", "")
            log(f"  NLB '{nlb_name}' IP={nlb_ip}")
            if nlb_ip == TARGET_IP or True:  # check all
                # Get full NLB detail
                detail = c.get_load_balancer(id=nlb_id)
                for svc in detail.get("services", []):
                    svc_name = svc.get("name","")
                    svc_port = svc.get("port","?")
                    svc_id   = svc.get("id","")
                    # Check for ACL
                    svc_detail = c.get_load_balancer_service(id=nlb_id, service_id=svc_id)
                    acl = svc_detail.get("healthcheck",{})
                    ingress_acl = svc_detail.get("ingress-acl", [])
                    egress_acl  = svc_detail.get("egress-acl", [])
                    log(f"    Service '{svc_name}' port={svc_port}")
                    log(f"      ingress-acl: {ingress_acl}")
                    log(f"      egress-acl: {egress_acl}")
                    log(f"      healthcheck: {acl}")
    except Exception as e:
        log(f"  Error in {zone_name}: {e}")

log("\nDone.")
