#!/usr/bin/env python3
"""Delete orphaned sks-ccm-* API keys and then retry SG deletion."""
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

# 1. Delete orphaned sks-ccm-* API keys
print("=== Deleting orphaned sks-ccm API keys ===")
try:
    keys = c.list_api_keys().get("api-keys", [])
    ccm_keys = [k2 for k2 in keys if k2.get("name","").startswith("sks-ccm-")]
    print(f"Found {len(ccm_keys)} sks-ccm keys")
    for k2 in ccm_keys:
        try:
            c.revoke_api_key(api_key=k2["key"])
            print(f"  [OK] Revoked: {k2['name']} ({k2['key'][:20]}...)")
        except Exception as e:
            print(f"  [ERR] {k2['name']}: {e}")
except Exception as e:
    print(f"ERROR: {e}")

time.sleep(5)

# 2. Now delete orphaned JTP SGs
print("\n=== Deleting orphaned jtp security groups ===")
sgs = [s for s in c.list_security_groups().get("security-groups", [])
       if "jtp" in s.get("name", "").lower()]
print(f"Found {len(sgs)} jtp SGs")
for s in sgs:
    for attempt in range(4):
        try:
            c.delete_security_group(id=s["id"])
            print(f"  [OK] Deleted: {s['name']}")
            break
        except Exception as e:
            if attempt < 3:
                print(f"  Retry {attempt+1}: {e} — waiting 10s")
                time.sleep(10)
            else:
                print(f"  [FAIL] {s['name']}: {e}")

# Final state
print("\n=== Final State ===")
remaining_sgs = [s for s in c.list_security_groups().get("security-groups", [])
                 if "jtp" in s.get("name","").lower()]
remaining_keys = [k2 for k2 in c.list_api_keys().get("api-keys", [])
                  if k2.get("name","").startswith("sks-ccm-")]
print(f"jtp SGs remaining:    {len(remaining_sgs)}")
print(f"sks-ccm keys remaining: {len(remaining_keys)}")
if not remaining_sgs and not remaining_keys:
    print("[OK] ALL CLEAN")
else:
    for s in remaining_sgs:
        print(f"  SG: {s['name']}")
    for k2 in remaining_keys:
        print(f"  CCM key: {k2['name']}")
