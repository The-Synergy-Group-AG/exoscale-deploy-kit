#!/usr/bin/env python3
"""
Delete all rules from jtp SGs first (removes self-references),
then delete the empty SGs.
"""
import os, time
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client
c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"],
           url="https://api-ch-dk-2.exoscale.com/v2")

sgs = [s for s in c.list_security_groups().get("security-groups", [])
       if "jtp" in s.get("name", "").lower()]
print(f"Found {len(sgs)} jtp SGs\n")

# Step 1: Delete all rules from each SG
for sg in sgs:
    sg_id = sg["id"]
    sg_name = sg["name"]
    # Re-fetch to get rules
    full = c.get_security_group(id=sg_id)
    rules = full.get("rules", [])
    print(f"SG: {sg_name} — {len(rules)} rules")
    for rule in rules:
        rule_id = rule.get("id")
        if not rule_id:
            continue
        try:
            c.delete_security_group_rule(id=rule_id)
            print(f"  Deleted rule {rule_id} ({rule.get('flow_direction','?')} {rule.get('protocol','?')})")
        except Exception as e:
            print(f"  ERR rule {rule_id}: {e}")
    print()

print("Waiting 5s after rule deletion...")
time.sleep(5)

# Step 2: Delete the SGs
print("=== Deleting SGs ===")
for sg in sgs:
    for attempt in range(4):
        try:
            c.delete_security_group(id=sg["id"])
            print(f"  [OK] Deleted: {sg['name']}")
            break
        except Exception as e:
            if attempt < 3:
                print(f"  Retry {attempt+1}: {e} — waiting 10s")
                time.sleep(10)
            else:
                print(f"  [FAIL] {sg['name']}: {e}")

# Final check
remaining = [s for s in c.list_security_groups().get("security-groups", [])
             if "jtp" in s.get("name", "").lower()]
print(f"\nSGs remaining: {len(remaining)}")
if not remaining:
    print("[OK] ALL JTP SGs DELETED")
else:
    for s in remaining:
        print(f"  STILL EXISTS: {s['name']}")
