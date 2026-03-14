#!/bin/bash
cd /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit
python3 << 'EOF'
import urllib.request, json

tests = [
    "access-control-service",
    "gamification-frontend",
    "credits-redemption-frontend",
    "neural-network-processor",
    "subscription-service",
    "auth-service",
    "onboarding-frontend",
    "payment-billing-frontend",
]

print("=== Service Health Spot Check ===")
ok = 0
for svc in tests:
    try:
        req = urllib.request.urlopen(f"https://jobtrackerpro.ch/api/{svc}/health", timeout=6)
        d = json.loads(req.read())
        status = d.get("status", "?")
        print(f"  {req.status} {svc}: {status}")
        if req.status == 200:
            ok += 1
    except Exception as e:
        print(f"  ERR {svc}: {e}")

print(f"\n{ok}/{len(tests)} healthy")
EOF
