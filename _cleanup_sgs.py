#!/usr/bin/env python3
"""Delete all orphaned jtp security groups."""
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

print(f"Found {len(sgs)} jtp security groups to delete")
for s in sgs:
    for attempt in range(6):
        try:
            c.delete_security_group(id=s["id"])
            print(f"  [OK] Deleted SG: {s['name']} ({s['id']})")
            break
        except Exception as e:
            if attempt < 5:
                print(f"  Attempt {attempt+1}/6: {e} — waiting 10s")
                time.sleep(10)
            else:
                print(f"  [FAIL] {s['name']}: {e}")

# Final check
remaining = [s for s in c.list_security_groups().get("security-groups", [])
             if "jtp" in s.get("name", "").lower()]
print(f"\nSGs remaining: {len(remaining)}")
if not remaining:
    print("[OK] All jtp SGs deleted")
else:
    for s in remaining:
        print(f"  STILL EXISTS: {s['name']} {s['id']}")
