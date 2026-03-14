#!/bin/bash
cd /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit
python3 -c "
import socket, subprocess, sys

domain = 'jobtrackerpro.ch'
lb_ip = '159.100.251.14'

# DNS resolution via system
print('=== DNS Resolution Check ===')
try:
    ip = socket.gethostbyname(domain)
    print(f'System DNS: {domain} → {ip}')
    if ip == lb_ip:
        print(f'[OK] Matches LB IP {lb_ip}')
    else:
        print(f'[WARN] Expected {lb_ip}, got {ip}')
except Exception as e:
    print(f'[FAIL] {domain} does not resolve: {e}')

# Direct query via Exoscale nameserver using Python
print()
print('=== Query via ns1.exoscale.net ===')
try:
    # Use host command if available
    r = subprocess.run(['host', domain, 'ns1.exoscale.net'], capture_output=True, text=True, timeout=5)
    print(r.stdout.strip() or r.stderr.strip())
except Exception as e:
    print(f'host not available: {e}')

# HTTP reachability check
print()
print('=== HTTP Reachability ===')
try:
    import urllib.request, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.urlopen(f'http://{lb_ip}/', timeout=5, context=None)
    print(f'HTTP {lb_ip} → {req.status} (direct IP works)')
except Exception as e:
    print(f'HTTP direct: {e}')
"
