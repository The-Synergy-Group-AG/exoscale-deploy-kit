#!/usr/bin/env python3
"""Quick status check: clusters + instances remaining."""
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

clusters = c.list_sks_clusters().get("sks-clusters", [])
lbs      = c.list_load_balancers().get("load_balancers", [])
instances = c.list_instances().get("instances", [])
pool_inst = [i for i in instances if "pool-" in i.get("name", "").lower()]
sgs = [s for s in c.list_security_groups().get("security-groups", []) if "jtp" in s.get("name","").lower()]

print(f"Clusters:          {len(clusters)}")
print(f"LBs:               {len(lbs)}")
print(f"Instances (pool-): {len(pool_inst)}")
print(f"SGs (jtp):         {len(sgs)}")

for cl in clusters:
    print(f"  CLUSTER: {cl['name']} state={cl.get('state')} id={cl['id']}")
    for np in cl.get("nodepools", []):
        print(f"    POOL: {np['name']} size={np.get('size')} id={np['id']}")
for lb in lbs:
    print(f"  LB: {lb['name']} ip={lb.get('ip-address','?')}")
for i in pool_inst:
    print(f"  INST: {i['name']} state={i.get('state')}")
for s in sgs:
    print(f"  SG: {s['name']}")

if not clusters and not lbs and not pool_inst:
    print("\n[OK] ALL CLEAN — zero instances/clusters/LBs")
else:
    print(f"\n[WARN] Resources still exist — teardown in progress or manual action needed")
