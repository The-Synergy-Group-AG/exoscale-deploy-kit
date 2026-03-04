#!/usr/bin/env python3
"""
Create DNS zone for jobtrackerpro.ch in the current Exoscale account
and add A records pointing to the nginx-ingress LoadBalancer IP.
"""
import os
from pathlib import Path
for line in Path(__file__).parent.joinpath(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client

KEY    = os.environ["EXO_API_KEY"]
SECRET = os.environ["EXO_API_SECRET"]
URL    = "https://api-ch-dk-2.exoscale.com/v2"
DOMAIN = "jobtrackerpro.ch"
LB_IP  = "159.100.248.98"

client = Client(KEY, SECRET, url=URL)

print(f"Creating DNS zone: {DOMAIN}")
try:
    resp = client.create_dns_domain(unicode_name=DOMAIN)
    print(f"Zone created: {resp}")
    domain_id = resp.get("id") or resp.get("dns_domain", {}).get("id")
except Exception as e:
    print(f"Zone create failed (may already exist): {e}")
    # Try to get zone anyway
    try:
        r = client.list_dns_domains()
        d = next((x for x in r.get("dns_domains", []) if x.get("unicode_name") == DOMAIN), None)
        if d:
            domain_id = d["id"]
            print(f"Zone already exists: id={domain_id}")
        else:
            print("Zone still not found after create attempt."); import sys; sys.exit(1)
    except Exception as e2:
        print(f"Fatal: {e2}"); import sys; sys.exit(1)

print(f"\nAdding A records (domain_id={domain_id}):")
records = [
    {"name": "",    "label": DOMAIN},
    {"name": "www", "label": f"www.{DOMAIN}"},
]
for rec in records:
    try:
        r = client.create_dns_domain_record(
            domain_id=domain_id,
            name=rec["name"],
            type="A",
            content=LB_IP,
            ttl=300
        )
        print(f"  Created: {rec['label']} A {LB_IP}")
    except Exception as e:
        print(f"  {rec['label']}: {e} — trying update...")
        try:
            existing = client.list_dns_domain_records(domain_id=domain_id)
            match = next((x for x in existing.get("dns_domain_records", [])
                         if x.get("type") == "A" and (x.get("name") or "") == rec["name"]), None)
            if match:
                client.update_dns_domain_record(
                    domain_id=domain_id,
                    dns_domain_record_id=match["id"],
                    content=LB_IP, ttl=300
                )
                print(f"  Updated: {rec['label']} A {LB_IP}")
        except Exception as e2:
            print(f"  Update also failed: {e2}")

print("\nFinal A records:")
r2 = client.list_dns_domain_records(domain_id=domain_id)
for rec in r2.get("dns_domain_records", []):
    if rec.get("type") == "A":
        n = rec.get("name") or ""
        label = DOMAIN if not n else f"{n}.{DOMAIN}"
        ok = "OK" if rec.get("content") == LB_IP else "!!"
        print(f"  [{ok}] {label} A {rec.get('content')} TTL={rec.get('ttl')}")

print(f"\nDone. Once DNS propagates, https://{DOMAIN} will work.")
