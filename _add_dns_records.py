#!/usr/bin/env python3
"""
Add A records to existing jobtrackerpro.ch DNS zone.
Domain created in Run 8: id=89083a5c-b648-474a-0000-00000015cf47
Correct kwarg signatures from update_dns.py:
  list_dns_domain_records(domain_id=...)
  create_dns_domain_record(domain_id=..., name=..., type=..., content=..., ttl=...)
  update_dns_domain_record(domain_id=..., dns_domain_record_id=..., content=..., ttl=...)
"""
import os, sys
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client

DOMAIN_ID = "89083a5c-b648-474a-0000-00000015cf47"
DOMAIN    = "jobtrackerpro.ch"
LB_IP     = sys.argv[1] if len(sys.argv) > 1 else "159.100.251.14"
API_URL   = "https://api-ch-dk-2.exoscale.com/v2"
TTL       = 300

c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"], url=API_URL)
print(f"=== Adding DNS records: {DOMAIN} → {LB_IP} ===")

# List existing records using correct kwarg
recs = c.list_dns_domain_records(domain_id=DOMAIN_ID).get("dns_domain_records", [])
print(f"Existing records ({len(recs)}):")
for r in recs:
    print(f"  {r.get('name') or '@':<25} {r.get('type'):<8} {r.get('content')}  TTL={r.get('ttl')}")

# Upsert A records for @ and www
for name in ["", "www"]:
    display = name if name else "@"
    existing_a = next(
        (r for r in recs if r.get("type") == "A" and r.get("name", "") == name),
        None
    )
    if existing_a:
        if existing_a.get("content") == LB_IP:
            print(f"[OK] A {display} already → {LB_IP}")
        else:
            print(f"[UPDATE] A {display}: {existing_a.get('content')} → {LB_IP}")
            try:
                c.update_dns_domain_record(
                    domain_id=DOMAIN_ID,
                    dns_domain_record_id=existing_a["id"],
                    content=LB_IP,
                    ttl=TTL,
                )
                print(f"  [OK] Updated")
            except Exception as e:
                print(f"  [ERR] {e}")
    else:
        print(f"[CREATE] A {display} → {LB_IP}")
        try:
            c.create_dns_domain_record(
                domain_id=DOMAIN_ID,
                name=name,
                type="A",
                content=LB_IP,
                ttl=TTL,
            )
            print(f"  [OK] Created")
        except Exception as e:
            print(f"  [ERR] {e}")

# Final state
recs2 = c.list_dns_domain_records(domain_id=DOMAIN_ID).get("dns_domain_records", [])
print(f"\nFinal records ({len(recs2)}):")
for r in recs2:
    print(f"  {r.get('name') or '@':<25} {r.get('type'):<8} {r.get('content')}  TTL={r.get('ttl')}")

ns = [r.get("content") for r in recs2 if r.get("type") == "NS"]
print(f"\n=== ACTION REQUIRED AT DOMAIN REGISTRAR ===")
print(f"Point {DOMAIN} nameservers to Exoscale:")
for n in ns or ["ns1.exoscale.net", "ns2.exoscale.net", "ns3.exoscale.net", "ns4.exoscale.net"]:
    print(f"  {n}")
print(f"\nAfter propagation: {DOMAIN} → {LB_IP} → SSL auto-provisions")
