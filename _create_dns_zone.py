#!/usr/bin/env python3
"""
Create jobtrackerpro.ch DNS zone in Exoscale if it doesn't exist.
Shows the Exoscale nameservers so the domain registrar can be updated.
"""
import os
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client

DOMAIN  = "jobtrackerpro.ch"
API_URL = "https://api-ch-dk-2.exoscale.com/v2"

c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"], url=API_URL)

# Check if already exists
doms = c.list_dns_domains().get("dns_domains", [])
existing = next((d for d in doms if d.get("unicode_name") == DOMAIN), None)

if existing:
    print(f"FOUND: {DOMAIN} already exists (id={existing['id']})")
    domain_id = existing["id"]
else:
    print(f"CREATE: {DOMAIN} not found — creating...")
    result = c.create_dns_domain(unicode_name=DOMAIN)
    print(f"  Created: {result}")
    # Re-fetch
    doms = c.list_dns_domains().get("dns_domains", [])
    existing = next((d for d in doms if d.get("unicode_name") == DOMAIN), None)
    if existing:
        domain_id = existing["id"]
        print(f"  Domain ID: {domain_id}")
    else:
        print("  ERROR: Could not confirm creation")
        import sys; sys.exit(1)

# Show all records
print(f"\nCurrent records for {DOMAIN}:")
recs = c.list_dns_domain_records(domain_id).get("dns_domain_records", [])
for r in recs:
    print(f"  {r.get('name') or '@':<20} {r.get('type'):<8} {r.get('content')}  TTL={r.get('ttl')}")

if not recs:
    print("  (empty — no records yet)")

print("\nNOTE: To activate Exoscale DNS for this domain,")
print("      update the domain registrar's nameservers to Exoscale's nameservers.")
print("      Typical Exoscale nameservers:")
print("      ns1.exoscale.net")
print("      ns2.exoscale.net")
print("      ns3.exoscale.net")
print("      ns4.exoscale.net")
