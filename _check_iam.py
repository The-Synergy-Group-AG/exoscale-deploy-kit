#!/usr/bin/env python3
"""Check current API key IAM permissions."""
import os, json
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client
c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"],
           url="https://api-ch-dk-2.exoscale.com/v2")

print("=== API Key Info ===")
try:
    r = c.get_api_key(api_key_fingerprint=os.environ["EXO_API_KEY"][:16])
    print(json.dumps(r, indent=2)[:500])
except Exception as e:
    print(f"get_api_key: {e}")

print("\n=== IAM Org Policy ===")
try:
    r = c.get_iam_organization_policy()
    print(json.dumps(r, indent=2)[:1000])
except Exception as e:
    print(f"get_iam_organization_policy: {e}")

print("\n=== Current API Key IAM ===")
try:
    r = c.list_api_keys()
    for k2 in r.get("api-keys", []):
        print(f"  key={k2.get('key','')} name={k2.get('name','')} role={k2.get('role-id','')}")
except Exception as e:
    print(f"list_api_keys: {e}")
