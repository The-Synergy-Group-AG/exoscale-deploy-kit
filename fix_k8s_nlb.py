#!/usr/bin/env python3
"""
Fix K8s NLB (k8s-a14f546f, 159.100.248.98):
  port 80  healthcheck/target: 30615 -> 30095 (nginx-ingress HTTP NodePort)
  port 443 healthcheck/target: 30615 -> 31473 (nginx-ingress HTTPS NodePort)
"""
import os, sys
from pathlib import Path
from datetime import datetime

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

env_file = Path(__file__).parent / ".env"
for raw in env_file.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from exoscale.api.v2 import Client
c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"], zone="ch-dk-2")

K8S_NLB_NAME    = "k8s-a14f546f-c80a-48b0-8661-a6429793edba"
NGINX_HTTP_PORT  = 30095
NGINX_HTTPS_PORT = 31473

# Find NLB
nlbs = c.list_load_balancers().get("load-balancers", [])
nlb  = next((n for n in nlbs if n.get("name") == K8S_NLB_NAME), None)
if not nlb:
    log(f"ERROR: NLB '{K8S_NLB_NAME}' not found")
    log(f"Available: {[n.get('name') for n in nlbs]}")
    sys.exit(1)

nlb_id = nlb["id"]
nlb_ip = nlb["ip"]
log(f"K8s NLB: {nlb_id[:8]} IP={nlb_ip}")

detail   = c.get_load_balancer(id=nlb_id)
services = detail.get("services", [])
log(f"Services: {[(s.get('port'), s.get('target-port'), s.get('healthcheck',{}).get('port')) for s in services]}")

for svc in services:
    port    = svc.get("port")
    svc_id  = svc.get("id")
    cur_hc  = svc.get("healthcheck", {}).get("port")

    if port == 80:
        if cur_hc == NGINX_HTTP_PORT:
            log(f"  port 80 already -> {NGINX_HTTP_PORT} OK")
        else:
            log(f"  port 80: hc={cur_hc} -> {NGINX_HTTP_PORT}")
            try:
                c.update_load_balancer_service(
                    id=nlb_id, service_id=svc_id,
                    protocol="tcp",
                    target_port=NGINX_HTTP_PORT,
                    healthcheck={"port": NGINX_HTTP_PORT, "mode": "tcp", "interval": 10, "timeout": 5, "retries": 1},
                )
                log("  Updated port 80 OK")
            except Exception as e:
                log(f"  ERROR port 80: {e}")

    elif port == 443:
        if cur_hc == NGINX_HTTPS_PORT:
            log(f"  port 443 already -> {NGINX_HTTPS_PORT} OK")
        else:
            log(f"  port 443: hc={cur_hc} -> {NGINX_HTTPS_PORT}")
            try:
                c.update_load_balancer_service(
                    id=nlb_id, service_id=svc_id,
                    protocol="tcp",
                    target_port=NGINX_HTTPS_PORT,
                    healthcheck={"port": NGINX_HTTPS_PORT, "mode": "tcp", "interval": 10, "timeout": 5, "retries": 1},
                )
                log("  Updated port 443 OK")
            except Exception as e:
                log(f"  ERROR port 443: {e}")

log("\n=== Verify ===")
d2 = c.get_load_balancer(id=nlb_id)
for svc in d2.get("services", []):
    log(f"  port {svc.get('port')}: target={svc.get('target-port')}  hc={svc.get('healthcheck',{}).get('port')}")

log("\nDone! Next: wait ~60s then test curl http://159.100.248.98/")
