#!/usr/bin/env python3
"""DNS diagnostic - check zone via multiple endpoint approaches."""
import os
from pathlib import Path

env_file = Path(__file__).parent / ".env"
for raw in env_file.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from exoscale.api.v2 import Client

KEY    = os.environ["EXO_API_KEY"]
SECRET = os.environ["EXO_API_SECRET"]
ZONE   = "ch-dk-2"

urls_to_try = [
    f"https://api-{ZONE}.exoscale.com/v2",
    "https://api.exoscale.com/v2",
]

for url in urls_to_try:
    try:
        c = Client(KEY, SECRET, url=url)
        r = c.list_dns_domains()
        domains = r.get("dns_domains", [])
        print(f"URL {url}: {[d.get('unicode_name') for d in domains]}")
    except Exception as e:
        print(f"URL {url}: ERROR {e}")

# Also try zone= parameter
try:
    c2 = Client(KEY, SECRET, zone=ZONE)
    r2 = c2.list_dns_domains()
    domains2 = r2.get("dns_domains", [])
    print(f"zone={ZONE}: {[d.get('unicode_name') for d in domains2]}")
except Exception as e:
    print(f"zone={ZONE}: ERROR {e}")
