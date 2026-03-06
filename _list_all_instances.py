#!/usr/bin/env python3
"""List ALL instances in the account (no filter)."""
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

instances = c.list_instances().get("instances", [])
print(f"Total instances: {len(instances)}")
for i in instances:
    sgs = [s.get("id","") for s in i.get("security-groups", [])]
    print(f"  {i['name']:<40} state={i.get('state','?'):<12} SGs={sgs}")

if not instances:
    print("  (none)")

# Also try listing instance-pools directly
print("\n--- Instance Pools ---")
try:
    pools = c.list_instance_pools().get("instance-pools", [])
    for p in pools:
        print(f"  POOL: {p['name']} state={p.get('state')} id={p['id']}")
    if not pools:
        print("  (none)")
except Exception as e:
    print(f"  ERROR: {e}")
