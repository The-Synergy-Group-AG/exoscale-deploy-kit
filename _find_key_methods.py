#!/usr/bin/env python3
"""Find correct API key deletion method and attempt SG deletion."""
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

# Find all methods related to API keys
key_methods = sorted([m for m in dir(c) if "api_key" in m.lower() and not m.startswith("_")])
print(f"api_key methods: {key_methods}")

iam_methods = sorted([m for m in dir(c) if "iam" in m.lower() and not m.startswith("_")])
print(f"iam methods: {iam_methods}")

role_methods = sorted([m for m in dir(c) if "role" in m.lower() and not m.startswith("_")])
print(f"role methods: {role_methods}")

# List CCM keys
keys = c.list_api_keys().get("api-keys", [])
ccm_keys = [k2 for k2 in keys if k2.get("name","").startswith("sks-ccm-")]
print(f"\nCCM keys: {[k2['name'] for k2 in ccm_keys]}")

# Try to delete CCM keys
for k2 in ccm_keys:
    key_val = k2.get("key", "")
    print(f"\nDeleting {k2['name']}...")
    # Try delete_api_key with 'key' parameter (the key string itself)
    for fn_name in ["delete_api_key"]:
        fn = getattr(c, fn_name, None)
        if fn:
            for param in [{"api_key": key_val}, {"key": key_val}, {"id": key_val}]:
                try:
                    fn(**param)
                    print(f"  [OK] {fn_name}({param})")
                    break
                except Exception as e:
                    print(f"  [{fn_name}({param})] → {str(e)[:80]}")

# One final SG attempt after CCM key deletion
print("\n--- Final SG attempt ---")
time.sleep(5)
sgs = [s for s in c.list_security_groups().get("security-groups", [])
       if "jtp" in s.get("name","").lower()]
for sg in sgs:
    try:
        c.delete_security_group(id=sg["id"])
        print(f"  [OK] {sg['name']}")
    except Exception as e:
        print(f"  [FAIL] {sg['name']}: {str(e)[:80]}")
