#!/usr/bin/env python3
"""Probe DNS access across Exoscale API variants."""
import os, sys
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

key    = os.environ["EXO_API_KEY"]
secret = os.environ["EXO_API_SECRET"]

from exoscale.api.v2 import Client

# Try multiple zones + global
endpoints = [
    "https://api-ch-dk-2.exoscale.com/v2",
    "https://api-ch-gva-2.exoscale.com/v2",
    "https://api-at-vie-1.exoscale.com/v2",
    "https://api-de-fra-1.exoscale.com/v2",
    "https://api-de-muc-1.exoscale.com/v2",
    "https://api-bg-sof-1.exoscale.com/v2",
]
for url in endpoints:
    try:
        c = Client(key, secret, url=url)
        resp = c.list_dns_domains()
        doms = resp.get("dns_domains", [])
        if doms:
            print(f"FOUND via {url}:")
            for d in doms:
                print(f"  {d.get('unicode_name')} id={d.get('id')}")
        else:
            print(f"  {url}: empty")
    except Exception as e:
        print(f"  {url}: ERROR {e}")
