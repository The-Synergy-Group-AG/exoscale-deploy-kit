#!/usr/bin/env python3
import os, sys
from pathlib import Path
for line in Path(__file__).parent.joinpath(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client

key    = os.environ["EXO_API_KEY"]
secret = os.environ["EXO_API_SECRET"]

for url in [
    "https://api-ch-dk-2.exoscale.com/v2",
    "https://api.exoscale.com/v2",
    "https://api-ch-gva-2.exoscale.com/v2",
]:
    c = Client(key, secret, url=url)
    try:
        r = c.list_dns_domains()
        domains = r.get("dns_domains", [])
        print(f"{url}: {len(domains)} zones: {[d.get('unicode_name') for d in domains]}")
    except Exception as e:
        print(f"{url}: ERROR {e}")
