#!/usr/bin/env python3
"""Add A records to the existing jobtrackerpro.ch zone in the deploy account."""
import os, time
from pathlib import Path

for line in Path(__file__).parent.joinpath(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client

KEY    = os.environ["EXO_API_KEY"]
SECRET = os.environ["EXO_API_SECRET"]
URL    = "https://api-ch-dk-2.exoscale.com/v2"
DOMAIN = "jobtrackerpro.ch"
LB_IP  = "159.100.248.98"

client = Client(KEY, SECRET, url=URL)

# --- Step 1: find domain ID ---
print("Looking up domain ID...")
time.sleep(2)  # brief wait for zone to be fully provisioned
r = client.list_dns_domains()
domains = r.get("dns_domains", [])
print(f"Domains in account: {[d.get('unicode_name') for d in domains]}")
domain = next((d for d in domains if d.get("unicode_name") == DOMAIN), None)
if not domain:
    print(f"ERROR: {DOMAIN} not found in deploy account. Domains: {domains}")
    import sys; sys.exit(1)

domain_id = domain["id"]
print(f"Found: {DOMAIN} id={domain_id}")

# --- Step 2: add A records ---
records = [
    {"name": "",    "label": DOMAIN,         "ttl": 300},
    {"name": "www", "label": f"www.{DOMAIN}", "ttl": 300},
]

for rec in records:
    try:
        client.create_dns_domain_record(
            domain_id=domain_id,
            name=rec["name"],
            type="A",
            content=LB_IP,
            ttl=rec["ttl"],
        )
        print(f"  Created: {rec['label']}  A  {LB_IP}")
    except Exception as e:
        print(f"  {rec['label']}: {e}")

# --- Step 3: verify ---
print("\nFinal records:")
r2 = client.list_dns_domain_records(domain_id=domain_id)
for rec in r2.get("dns_domain_records", []):
    if rec.get("type") not in ("NS", "SOA"):
        print(f"  {rec.get('type')}  {rec.get('name') or '@'}  {rec.get('content')}  TTL={rec.get('ttl')}")

print("\nDone. Wait ~60s for DNS propagation then verify with: python3 check_dns_records.py")
