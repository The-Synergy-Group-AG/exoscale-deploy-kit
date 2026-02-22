#!/usr/bin/env python3
"""Pre-flight check — verify config loads correctly before deploying."""
import re
import sys
from config_loader import load_config

cfg = load_config()
errors   = []
warnings = []

# ── Slug check (LESSONS 14 + 16) ─────────────────────────────────────────────
raw_name = cfg['project_name']
_slug    = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', raw_name.lower())).strip('-')
if raw_name != _slug:
    warnings.append(
        f"project_name '{raw_name}' will be auto-slugified to '{_slug}' for Exoscale resource names.\n"
        f"     Consider updating config.yaml: project_name: {_slug}"
    )

# ── Node size check (LESSON 13) ───────────────────────────────────────────────
node_size = cfg.get('node_type_size', 'medium')
if node_size in ('tiny', 'micro'):
    errors.append(
        f"node_type_size '{node_size}' is NOT supported by SKS node pools (Exoscale API restriction).\n"
        f"     Update config.yaml: node_type_size: small  (minimum supported size)"
    )

print("=== Config Loaded ===")
print(f"  project_name:    {raw_name}  →  slug: {_slug}")
print(f"  service_name:    {cfg['service_name']}")
print(f"  service_version: {cfg['service_version']}")
print(f"  docker_hub_user: {cfg['docker_hub_user']}")
print(f"  exoscale_zone:   {cfg['exoscale_zone']}")
print(f"  k8s_namespace:   {cfg['k8s_namespace']}")
print(f"  k8s_nodeport:    {cfg['k8s_nodeport']}")
print(f"  node_count:      {cfg['node_count']}")
print(f"  node_type_size:  {node_size}")
print(f"  exo_key:         {cfg['exo_key'][:12]}...")
print(f"  exo_secret:      {cfg['exo_secret'][:8]}...")
print(f"  docker_hub_token:{cfg['docker_hub_token'][:12]}...")
print()
image = f"{cfg['docker_hub_user']}/{cfg['service_name']}:{cfg['service_version']}"
print(f"  Image will be:        {image}")
print(f"  Resource prefix will: {_slug}-*")
print()

for w in warnings:
    print(f"  ⚠️  WARNING: {w}")
for e in errors:
    print(f"  ❌ ERROR:   {e}")

if errors:
    print("\nPREFLIGHT FAILED — fix errors above before deploying.")
    sys.exit(1)
elif warnings:
    print("Preflight complete with warnings — review above before deploying.")
else:
    print("All config keys present — READY TO DEPLOY")
