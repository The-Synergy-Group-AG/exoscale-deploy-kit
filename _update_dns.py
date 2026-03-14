#!/usr/bin/env python3
"""
Update jobtrackerpro.ch DNS A records to point to the current LB IP.

Lesson 50: Exoscale SDK list_dns_domains() returns empty — use raw REST.
Lesson 50: Always delete stale A records; duplicate A records cause round-robin
           to dead IPs, making the site intermittently unreachable.

Usage:
    python3 _update_dns.py <LB_IP>
"""
import os, sys, json
from pathlib import Path

# Load .env
for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

# Inject venv site-packages so exoscale_auth is available
_venv = Path(__file__).parent.parent / "venv/lib/python3.12/site-packages"
if _venv.exists():
    sys.path.insert(0, str(_venv))

import exoscale_auth, requests as _req

NEW_IP    = sys.argv[1] if len(sys.argv) > 1 else None
DOMAIN    = "jobtrackerpro.ch"
DOMAIN_ID = "89083a5c-b648-474a-0000-00000015cf47"
BASE      = "https://api-ch-dk-2.exoscale.com/v2"
TTL       = 300

if not NEW_IP:
    print("Usage: python3 _update_dns.py <LB_IP>", file=sys.stderr)
    sys.exit(1)

auth = exoscale_auth.ExoscaleV2Auth(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"])

print(f"=== DNS Update: {DOMAIN} → {NEW_IP} ===")

# Fetch current records (raw REST — SDK list_dns_domains is broken, L50)
r = _req.get(f"{BASE}/dns-domain/{DOMAIN_ID}/record", auth=auth, timeout=10)
r.raise_for_status()
recs = r.json().get("dns-domain-records", [])

print(f"Current A records ({sum(1 for r in recs if r.get('type')=='A')}):")
for rec in recs:
    if rec.get("type") == "A":
        print(f"  {rec.get('name') or '@':<10} → {rec.get('content')}  id={rec['id']}")

# Separate wanted from stale
wanted  = {n: None for n in ["", "www"]}   # name → record id if already correct
stale   = []                                 # record ids to delete

for rec in recs:
    if rec.get("type") != "A":
        continue
    name = rec.get("name", "")
    if name not in wanted:
        continue
    if rec.get("content") == NEW_IP:
        wanted[name] = rec["id"]   # already correct — keep
    else:
        stale.append(rec["id"])    # wrong IP — delete

# Delete stale records first (L50: avoid duplicate A records)
for rec_id in stale:
    resp = _req.delete(f"{BASE}/dns-domain/{DOMAIN_ID}/record/{rec_id}", auth=auth, timeout=10)
    if resp.status_code == 200:
        print(f"[DELETE] stale A record {rec_id} → OK")
    else:
        print(f"[WARN]   DELETE {rec_id} → {resp.status_code}: {resp.text[:100]}")

# Create missing records
for name, existing_id in wanted.items():
    display = name or "@"
    if existing_id:
        print(f"[OK]     A {display} already → {NEW_IP}")
    else:
        resp = _req.post(
            f"{BASE}/dns-domain/{DOMAIN_ID}/record",
            auth=auth,
            json={"name": name, "type": "A", "content": NEW_IP, "ttl": TTL},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            print(f"[CREATE] A {display} → {NEW_IP}  OK")
        else:
            print(f"[ERR]    CREATE A {display} → {resp.status_code}: {resp.text[:200]}")
            sys.exit(1)

# Verify final state
r2 = _req.get(f"{BASE}/dns-domain/{DOMAIN_ID}/record", auth=auth, timeout=10)
final_a = [rec for rec in r2.json().get("dns-domain-records", []) if rec.get("type") == "A"]
print(f"\nFinal A records ({len(final_a)}):")
for rec in final_a:
    print(f"  {rec.get('name') or '@':<10} → {rec.get('content')}  TTL={rec.get('ttl')}")

if any(rec.get("content") != NEW_IP for rec in final_a):
    print("[ERR] Some A records still point to wrong IP", file=sys.stderr)
    sys.exit(1)

print(f"\n[OK] {DOMAIN} → {NEW_IP}  (TTL={TTL}s — propagates in ~5 min)")
