#!/usr/bin/env python3
"""
Repurpose docker-jtp-nlb (159.100.250.135) to route port 80/443
to nginx-ingress NodePorts. Update DNS A records to 159.100.250.135.

NLB client: zone=ZONE (works for NLB discovery)
DNS client: url=API_URL (matches update_dns.py pattern)

nginx-ingress NodePorts:  80->30095  443->31473
"""
import os, sys
from pathlib import Path
from datetime import datetime

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

EXO_KEY    = os.environ.get("EXO_API_KEY", "").strip()
EXO_SECRET = os.environ.get("EXO_API_SECRET", "").strip()
ZONE       = "ch-dk-2"
API_URL    = f"https://api-{ZONE}.exoscale.com/v2"

from exoscale.api.v2 import Client
nlb_c = Client(EXO_KEY, EXO_SECRET, zone=ZONE)       # NLB client
dns_c = Client(EXO_KEY, EXO_SECRET, url=API_URL)     # DNS client

NLB_NAME             = "docker-jtp-nlb"
NGINX_HTTP_NODEPORT  = 30095
NGINX_HTTPS_NODEPORT = 31473

# ---------- Find NLB ----------
nlbs = nlb_c.list_load_balancers().get("load-balancers", [])
log(f"All NLBs: {[n.get('name') for n in nlbs]}")
nlb = next((n for n in nlbs if n.get("name") == NLB_NAME), None)
if not nlb:
    log(f"ERROR: NLB '{NLB_NAME}' not found"); sys.exit(1)

nlb_id = nlb["id"]
nlb_ip = nlb["ip"]
log(f"Found '{NLB_NAME}' ({nlb_id[:8]}) IP={nlb_ip}")

detail   = nlb_c.get_load_balancer(id=nlb_id)
services = detail.get("services", [])
log(f"Services: {[(s.get('port'), s.get('target-port')) for s in services]}")

# ---------- Update port 80 -> 30095 ----------
for svc in services:
    svc_port   = svc.get("port")
    svc_id     = svc.get("id")
    cur_target = svc.get("target-port")

    if svc_port == 80:
        if cur_target == NGINX_HTTP_NODEPORT:
            log(f"  port 80 already -> {NGINX_HTTP_NODEPORT} OK")
        else:
            log(f"  port 80: {cur_target} -> {NGINX_HTTP_NODEPORT}")
            try:
                nlb_c.update_load_balancer_service(
                    id=nlb_id, service_id=svc_id,
                    protocol="tcp",
                    target_port=NGINX_HTTP_NODEPORT,
                    healthcheck={"port": NGINX_HTTP_NODEPORT},
                )
                log("  Updated port 80 OK")
            except Exception as e:
                log(f"  ERROR port 80: {e}")

    elif svc_port == 443:
        if cur_target == NGINX_HTTPS_NODEPORT:
            log(f"  port 443 already -> {NGINX_HTTPS_NODEPORT} OK")
        else:
            log(f"  port 443: {cur_target} -> {NGINX_HTTPS_NODEPORT}")
            try:
                nlb_c.update_load_balancer_service(
                    id=nlb_id, service_id=svc_id,
                    protocol="tcp",
                    target_port=NGINX_HTTPS_NODEPORT,
                    healthcheck={"port": NGINX_HTTPS_NODEPORT},
                )
                log("  Updated port 443 OK")
            except Exception as e:
                log(f"  ERROR port 443: {e}")
    else:
        log(f"  port {svc_port}: unchanged")

# ---------- Verify NLB ----------
log("\n=== NLB after update ===")
d2 = nlb_c.get_load_balancer(id=nlb_id)
for svc in d2.get("services", []):
    log(f"  port {svc.get('port')}: target={svc.get('target-port')}")

# ---------- Update DNS via dns_c (url-based client) ----------
log("\n=== Updating DNS to " + nlb_ip + " ===")
DOMAIN = "jobtrackerpro.ch"
try:
    resp    = dns_c.list_dns_domains()
    domains = resp.get("dns_domains", [])
    log(f"DNS domains: {[d.get('unicode_name') for d in domains]}")
    domain  = next((d for d in domains if d.get("unicode_name") == DOMAIN), None)
    if not domain:
        log(f"ERROR: DNS zone '{DOMAIN}' not found"); sys.exit(1)
    domain_id = domain["id"]

    r2     = dns_c.list_dns_domain_records(domain_id=domain_id)
    a_recs = [r for r in r2.get("dns_domain_records", []) if r.get("type") == "A"]

    for t_name, t_label in [("", DOMAIN), ("www", "www." + DOMAIN)]:
        existing = next((r for r in a_recs if (r.get("name") or "") == t_name), None)
        if existing:
            if existing.get("content") == nlb_ip:
                log(f"  {t_label} -> {nlb_ip} already OK")
            else:
                log(f"  {t_label}: {existing.get('content')} -> {nlb_ip}")
                dns_c.update_dns_domain_record(
                    domain_id=domain_id,
                    dns_domain_record_id=existing["id"],
                    content=nlb_ip, ttl=300,
                )
                log(f"  Updated {t_label}")
        else:
            dns_c.create_dns_domain_record(
                domain_id=domain_id, name=t_name,
                type="A", content=nlb_ip, ttl=300,
            )
            log(f"  Created {t_label} -> {nlb_ip}")

    log("Final A records:")
    for r in dns_c.list_dns_domain_records(domain_id=domain_id).get("dns_domain_records", []):
        if r.get("type") == "A":
            nm  = r.get("name") or ""
            lbl = DOMAIN if not nm else nm + "." + DOMAIN
            ok  = "OK" if r.get("content") == nlb_ip else "!!"
            log(f"  [{ok}] {lbl} A {r.get('content')}")
except Exception as e:
    import traceback; log(f"DNS error: {e}"); traceback.print_exc()

log("\n=== Done! ===")
