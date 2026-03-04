#!/usr/bin/env python3
"""Check NLB state and fix target-ports via correct API."""
import os, sys, inspect
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from exoscale.api.v2 import Client
c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"], zone="ch-dk-2")

# Current NLB state
nlbs = c.list_load_balancers().get("load-balancers", [])
nlb = next(n for n in nlbs if n.get("name") == "docker-jtp-nlb")
detail = c.get_load_balancer(id=nlb["id"])
print("=== Current NLB services ===")
for svc in detail.get("services", []):
    print(f"  port {svc.get('port')}: target={svc.get('target-port')}  hc={svc.get('healthcheck',{}).get('port')}")

print("\n=== update_load_balancer_service signature ===")
sig = inspect.signature(c.update_load_balancer_service)
print(sig)
for name, param in sig.parameters.items():
    print(f"  {name}: {param.default}")

# DNS check via exoscale CLI-style
print("\n=== DNS methods on Client ===")
dns_methods = [m for m in dir(c) if "dns" in m.lower()]
print(dns_methods)
