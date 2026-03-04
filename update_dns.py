#!/usr/bin/env python3
"""
Update Exoscale DNS A records for jobtrackerpro.ch -> nginx-ingress LB IP.
Uses exoscale.api.v2 Client (same pattern as deploy_pipeline.py).

Usage:
  python3 update_dns.py                      # uses hardcoded default IP
  python3 update_dns.py --ip 159.100.248.98  # override target IP (pipeline use)

Task 5.2 (Plan 123-P5 ISSUE-015): Added --ip argument so deploy_pipeline.py
Stage 5c can call this script with the dynamically discovered ingress LB IP.
"""
import argparse
import os, sys, traceback
from pathlib import Path

# ── Argument parsing (Task 5.2 — ISSUE-015) ──────────────────────────────────
_parser = argparse.ArgumentParser(
    description="Update Exoscale DNS A records for the nginx-ingress LB IP"
)
_parser.add_argument(
    "--ip",
    default=None,
    help="Target A record IP (e.g. 159.100.248.98). Overrides the hardcoded default."
)
_args = _parser.parse_args()

# ── Load credentials from .env ───────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

API_KEY    = os.environ.get("EXO_API_KEY", "")
API_SECRET = os.environ.get("EXO_API_SECRET", "")
if not API_KEY or not API_SECRET:
    print("ERROR: EXO_API_KEY or EXO_API_SECRET not set"); sys.exit(1)

# ── Config ───────────────────────────────────────────────────────────────────
DOMAIN       = "jobtrackerpro.ch"
# NGINX_LB_IP: use --ip arg if provided, else fall back to last known IP.
# When called from deploy_pipeline.py Stage 5c, --ip is always passed.
NGINX_LB_IP  = _args.ip if _args.ip else "159.100.248.98"
ZONE         = "ch-dk-2"
API_URL      = f"https://api-{ZONE}.exoscale.com/v2"

from exoscale.api.v2 import Client
client = Client(API_KEY, API_SECRET, url=API_URL)

print(f"\nExoscale DNS Update -- {DOMAIN}")
print(f"  Target IP : {NGINX_LB_IP}")
print(f"  API URL   : {API_URL}\n")

# ── Find the DNS domain ───────────────────────────────────────────────────────
try:
    resp    = client.list_dns_domains()
    domains = resp.get("dns_domains", [])
    domain  = next((d for d in domains if d.get("unicode_name") == DOMAIN), None)
    if not domain:
        print(f"ERROR: '{DOMAIN}' not found. Available: {[d.get('unicode_name') for d in domains]}")
        sys.exit(1)
    domain_id = domain["id"]
    print(f"Found zone: {domain.get('unicode_name')} (id={domain_id})")
except Exception as e:
    print(f"ERROR listing domains: {e}"); traceback.print_exc(); sys.exit(1)

# ── List current A records ────────────────────────────────────────────────────
try:
    r2       = client.list_dns_domain_records(domain_id=domain_id)
    all_recs = r2.get("dns_domain_records", [])
    a_recs   = [r for r in all_recs if r.get("type") == "A"]
    print(f"\nCurrent A records:")
    for r in a_recs:
        print(f"  {r.get('name') or '@'} -> {r.get('content')} TTL={r.get('ttl')} id={r.get('id')}")
except Exception as e:
    print(f"ERROR listing records: {e}"); traceback.print_exc(); sys.exit(1)

# ── Update / create records ───────────────────────────────────────────────────
targets = [
    {"name": "",    "label": DOMAIN,             "ip": NGINX_LB_IP, "ttl": 300},
    {"name": "www", "label": f"www.{DOMAIN}",    "ip": NGINX_LB_IP, "ttl": 300},
]
print()
for t in targets:
    existing = next((r for r in a_recs if (r.get("name") or "") == t["name"]), None)
    try:
        if existing:
            if existing.get("content") == t["ip"]:
                print(f"OK  {t['label']} -> {t['ip']} (no change)")
            else:
                print(f"UPD {t['label']}: {existing.get('content')} -> {t['ip']}")
                client.update_dns_domain_record(
                    domain_id=domain_id,
                    dns_domain_record_id=existing["id"],
                    content=t["ip"],
                    ttl=t["ttl"]
                )
                print(f"    Done.")
        else:
            print(f"NEW {t['label']} -> {t['ip']}")
            client.create_dns_domain_record(
                domain_id=domain_id,
                name=t["name"],
                type="A",
                content=t["ip"],
                ttl=t["ttl"]
            )
            print(f"    Done.")
    except Exception as e:
        print(f"ERR {t['label']}: {e}"); traceback.print_exc()

# ── Verify ────────────────────────────────────────────────────────────────────
print("\nFinal A records:")
r3 = client.list_dns_domain_records(domain_id=domain_id)
for r in r3.get("dns_domain_records", []):
    if r.get("type") == "A":
        name  = r.get("name") or ""
        label = DOMAIN if not name else f"{name}.{DOMAIN}"
        ok    = "OK" if r.get("content") == NGINX_LB_IP else "!!"
        print(f"  [{ok}] {label} A {r.get('content')} TTL={r.get('ttl')}")

print("\nDone. Propagation ~5 min (TTL=300).")
print("cert-manager will auto-issue TLS cert once DNS propagates.")
