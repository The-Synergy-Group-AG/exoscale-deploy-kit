#!/usr/bin/env python3
"""
Delete 3 orphaned jtp SGs with 60s patience per attempt (Lesson 40c).
Also tries to find and delete orphaned CCM API keys.
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

# Find correct method name for API key deletion
key_methods = [m for m in dir(c) if "key" in m.lower() and not m.startswith("_")]
print(f"Client key-related methods: {key_methods}")

# Try to delete CCM API keys using whatever method name exists
keys = c.list_api_keys().get("api-keys", [])
ccm_keys = [k2 for k2 in keys if k2.get("name","").startswith("sks-ccm-")]
print(f"\nCCM keys to delete: {len(ccm_keys)}")
for k2 in ccm_keys:
    key_id = k2.get("key", k2.get("id", ""))
    print(f"  Trying to delete CCM key: {k2['name']} ({key_id[:20]}...)")
    # Try different method names
    for method in ["revoke_api_key", "delete_api_key", "delete_api_key_v2"]:
        fn = getattr(c, method, None)
        if fn:
            try:
                fn(api_key=key_id)
                print(f"    [OK] via {method}")
                break
            except Exception as e:
                print(f"    [{method}] failed: {e}")
    else:
        # Try with 'id' parameter
        for method in ["revoke_api_key", "delete_api_key"]:
            fn = getattr(c, method, None)
            if fn:
                try:
                    fn(id=key_id)
                    print(f"    [OK] via {method}(id=...)")
                    break
                except Exception as e:
                    pass

time.sleep(5)

# Now delete SGs with 60s patience (Lesson 40c)
print("\n=== Patient SG deletion (60s intervals, 8 attempts) ===")
sgs = [s for s in c.list_security_groups().get("security-groups", [])
       if "jtp" in s.get("name", "").lower()]
print(f"SGs to delete: {len(sgs)}")

for sg in sgs:
    print(f"\nDeleting {sg['name']} ({sg['id']})...")
    for attempt in range(1, 9):
        try:
            c.delete_security_group(id=sg["id"])
            print(f"  [OK] Deleted on attempt {attempt}")
            break
        except Exception as e:
            err = str(e)
            if "404" in err or "not found" in err.lower():
                print(f"  [OK] Already gone")
                break
            if attempt < 8:
                print(f"  Attempt {attempt}/8: {err[:80]} — waiting 60s")
                time.sleep(60)
            else:
                print(f"  [FAIL] after 8 attempts: {err[:80]}")
                print(f"  Manual: Exoscale Console → Compute → Security Groups → {sg['name']}")

# Final
print("\n=== Final Status ===")
remaining = [s for s in c.list_security_groups().get("security-groups", [])
             if "jtp" in s.get("name","").lower()]
rem_keys = [k2 for k2 in c.list_api_keys().get("api-keys",[]) if k2.get("name","").startswith("sks-ccm-")]
print(f"jtp SGs:  {len(remaining)}")
print(f"CCM keys: {len(rem_keys)}")
if not remaining and not rem_keys:
    print("[OK] FULLY CLEAN")
else:
    for s in remaining: print(f"  SG: {s['name']}")
    for k2 in rem_keys: print(f"  KEY: {k2['name']}")
