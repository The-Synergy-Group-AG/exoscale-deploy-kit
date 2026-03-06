#!/usr/bin/env python3
"""Check current LB IPs and DNS A records for jobtrackerpro.ch."""
import os
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client
c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"],
           url="https://api-ch-dk-2.exoscale.com/v2")

# Check LBs
lbs = c.list_load_balancers().get("load_balancers", [])
print("=== Load Balancers ===")
for lb in lbs:
    print(f"  {lb['name']}  ip={lb.get('ip-address','?')}  state={lb.get('state','?')}")
if not lbs:
    print("  (none)")

# Check DNS
print("\n=== DNS Records: jobtrackerpro.ch ===")
doms = c.list_dns_domains().get("dns_domains", [])
dom = next((d for d in doms if d.get("unicode_name") == "jobtrackerpro.ch"), None)
if dom:
    recs = c.list_dns_domain_records(dom["id"]).get("dns_domain_records", [])
    for r in recs:
        if r.get("type") in ("A", "CNAME", "ALIAS"):
            print(f"  {r.get('name','@'):<30} {r.get('type'):<6} {r.get('content')}  (id={r.get('id','')})")
else:
    print("  Domain not found in Exoscale DNS")
