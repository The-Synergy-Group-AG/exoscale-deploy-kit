#!/usr/bin/env python3
"""Check security groups for port 80 rules and open if needed."""
import os, sys, yaml

# Load credentials
api_key = os.environ.get("EXOSCALE_API_KEY", "")
api_secret = os.environ.get("EXOSCALE_API_SECRET", "")

if not api_key:
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    api_key = cfg.get("exoscale_api_key", "")
    api_secret = cfg.get("exoscale_api_secret", "")

if not api_key:
    print("ERROR: No API key found")
    sys.exit(1)

print(f"API key loaded: {api_key[:8]}...")

import exoscale
exo = exoscale.Exoscale(api_key=api_key, api_secret=api_secret)
zone = exo.compute.get_zone("ch-gva-2")

print("\n=== Security Groups ===")
for sg in exo.compute.list_security_groups(zone=zone):
    print(f"\nSG: {sg.name}")
    rules_80 = []
    rules_443 = []
    for r in sg.ingress_rules:
        start = getattr(r, "start_port", None)
        end = getattr(r, "end_port", None)
        cidr = getattr(r, "cidr", None)
        if start is not None and end is not None:
            if start <= 80 <= end:
                rules_80.append(f"  TCP {start}-{end} from {cidr}")
            if start <= 443 <= end:
                rules_443.append(f"  TCP {start}-{end} from {cidr}")
    
    if rules_80:
        print(f"  Port 80 rules: {rules_80}")
    else:
        print(f"  Port 80: NO RULE (blocked!)")
    
    if rules_443:
        print(f"  Port 443 rules: {rules_443}")
    else:
        print(f"  Port 443: NO RULE (blocked!)")
