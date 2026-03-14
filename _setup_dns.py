#!/usr/bin/env python3
"""
Create jobtrackerpro.ch DNS zone + A records pointing to current LB IP.
Run after each deployment to ensure DNS is configured correctly.
"""
import os, sys, time
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client

DOMAIN  = "jobtrackerpro.ch"
LB_IP   = sys.argv[1] if len(sys.argv) > 1 else "159.100.251.14"
API_URL = "https://api-ch-dk-2.exoscale.com/v2"
TTL     = 300

c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"], url=API_URL)

print(f"=== DNS Setup: {DOMAIN} → {LB_IP} ===")

# Step 1: Create or find zone — use ID from create response (list may lag)
domain_id = None
doms = c.list_dns_domains().get("dns_domains", [])
existing = next((d for d in doms if d.get("unicode_name") == DOMAIN), None)

if existing:
    print(f"[OK] Zone exists: {DOMAIN} (id={existing['id']})")
    domain_id = existing["id"]
else:
    print(f"[CREATE] Zone not found — creating {DOMAIN}...")
    try:
        result = c.create_dns_domain(unicode_name=DOMAIN)
        print(f"  API response: {result}")
        # Extract domain ID from reference in create response
        ref = result.get("reference", {})
        domain_id = ref.get("id")
        if domain_id:
            print(f"  [OK] Zone created, domain_id={domain_id}")
        else:
            # Wait and retry list
            print(f"  Waiting 3s for zone to propagate...")
            time.sleep(3)
            doms2 = c.list_dns_domains().get("dns_domains", [])
            existing2 = next((d for d in doms2 if d.get("unicode_name") == DOMAIN), None)
            if existing2:
                domain_id = existing2["id"]
                print(f"  [OK] Zone confirmed via list: id={domain_id}")
            else:
                print(f"  [ERR] Could not confirm zone — cannot add A records")
                sys.exit(1)
    except Exception as e:
        if "already" in str(e).lower() or "409" in str(e):
            # Zone exists in another account — cannot manage here
            print(f"  [ERR] Zone conflict: {e}")
            print(f"  → Delete the zone from the other Exoscale org first")
            sys.exit(1)
        print(f"  [ERR] Create failed: {e}")
        sys.exit(1)

# Step 2: List current records
try:
    recs = c.list_dns_domain_records(domain_id).get("dns_domain_records", [])
    print(f"\nExisting records ({len(recs)}):")
    for r in recs:
        print(f"  {r.get('name') or '@':<25} {r.get('type'):<8} {r.get('content')}  TTL={r.get('ttl')}")
except Exception as e:
    print(f"[WARN] Could not list records (zone may still be provisioning): {e}")
    recs = []

# Step 3: Upsert A records for @ and www
for name in ["", "www"]:
    display = name if name else "@"
    existing_a = next(
        (r for r in recs if r.get("type") == "A" and r.get("name", "") == name),
        None
    )
    if existing_a:
        if existing_a.get("content") == LB_IP:
            print(f"[OK] A record {display} already → {LB_IP}")
        else:
            old_ip = existing_a.get("content")
            print(f"[UPDATE] A record {display}: {old_ip} → {LB_IP}")
            try:
                c.update_dns_domain_record(domain_id, existing_a["id"], content=LB_IP, ttl=TTL)
                print(f"  [OK] Updated")
            except Exception as e:
                print(f"  [ERR] {e}")
    else:
        print(f"[CREATE] A record {display} → {LB_IP}")
        try:
            c.create_dns_domain_record(domain_id, name=name, type="A", content=LB_IP, ttl=TTL)
            print(f"  [OK] Created")
        except Exception as e:
            print(f"  [ERR] {e}")

# Step 4: Final state
try:
    recs2 = c.list_dns_domain_records(domain_id).get("dns_domain_records", [])
    print(f"\nFinal records ({len(recs2)}):")
    for r in recs2:
        print(f"  {r.get('name') or '@':<25} {r.get('type'):<8} {r.get('content')}  TTL={r.get('ttl')}")
    ns_recs = [r for r in recs2 if r.get("type") == "NS"]
except Exception as e:
    print(f"[WARN] Could not read final records: {e}")
    ns_recs = []

print(f"\n=== ACTION REQUIRED AT DOMAIN REGISTRAR ===")
print(f"Point {DOMAIN} nameservers to Exoscale:")
if ns_recs:
    for r in ns_recs:
        print(f"  {r.get('content')}")
else:
    print("  ns1.exoscale.net")
    print("  ns2.exoscale.net")
    print("  ns3.exoscale.net")
    print("  ns4.exoscale.net")
print(f"\nOnce nameservers propagate → {DOMAIN} resolves to {LB_IP}")
print(f"SSL cert auto-provisions via Let's Encrypt (HTTP-01 challenge)")
