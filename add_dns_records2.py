#!/usr/bin/env python3
"""Add A records using the known domain ID from zone creation."""
import os, json
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

# Domain ID from successful create_dns_domain call
DOMAIN_ID = "89083a5c-b648-474a-0000-00000015cabb"

client = Client(KEY, SECRET, url=URL)

print(f"Using domain_id={DOMAIN_ID}")

# Try to get the domain directly
try:
    d = client.get_dns_domain(id=DOMAIN_ID)
    print(f"Domain: {d}")
except Exception as e:
    print(f"get_dns_domain: {e}")

# Add A records
records = [
    {"name": "",    "label": DOMAIN},
    {"name": "www", "label": f"www.{DOMAIN}"},
]

for rec in records:
    try:
        r = client.create_dns_domain_record(
            id=DOMAIN_ID,
            name=rec["name"],
            type="A",
            content=LB_IP,
            ttl=300,
        )
        print(f"  Created {rec['label']} A {LB_IP}: {r}")
    except Exception as e:
        print(f"  {rec['label']} id= attempt: {e}")
        # try domain_id=
        try:
            r = client.create_dns_domain_record(
                domain_id=DOMAIN_ID,
                name=rec["name"],
                type="A",
                content=LB_IP,
                ttl=300,
            )
            print(f"  Created {rec['label']} A {LB_IP}: {r}")
        except Exception as e2:
            print(f"  {rec['label']} domain_id= attempt: {e2}")

# List available methods
print("\nAvailable DNS methods:")
for m in sorted(dir(client)):
    if "dns" in m.lower():
        print(f"  {m}")
