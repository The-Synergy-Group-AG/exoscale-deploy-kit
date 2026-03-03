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

# ── Cluster capacity check (LESSON 120-6) ────────────────────────────────────
# Lesson learned: 220 uvicorn pods x ~60MB actual = 13GB exceeds 3-node cluster.
# Python/uvicorn services require ~50-80MB actual RAM at runtime regardless of
# Docker memory requests. Over-scheduling causes cascade OOM on all nodes.
NODE_RAM_BY_SIZE = {
    'small':  2600,   # s.2: ~2.6GB usable after OS
    'medium': 5600,   # s.4: ~5.6GB usable after OS
    'large':  11600,  # s.8: ~11.6GB usable after OS
}
UVICORN_RAM_Mi = 60   # realistic minimum per Python/FastAPI service pod
node_count = int(cfg.get('node_count', 3))
node_ram_usable = NODE_RAM_BY_SIZE.get(node_size, 2600)
cluster_capacity_Mi = node_count * node_ram_usable
service_count = int(cfg.get('service_count', 220))
max_safe_pods = cluster_capacity_Mi // UVICORN_RAM_Mi
if service_count > max_safe_pods:
    errors.append(
        f"CLUSTER CAPACITY INSUFFICIENT (Lesson 120-6):\n"
        f"     {service_count} services x {UVICORN_RAM_Mi}Mi actual RAM = "
        f"{service_count * UVICORN_RAM_Mi}Mi needed\n"
        f"     {node_count} nodes x {node_ram_usable}Mi usable = {cluster_capacity_Mi}Mi available\n"
        f"     Max safe pods: {max_safe_pods}  (deficit: {service_count - max_safe_pods} pods)\n"
        f"     FIX: Increase node_count to {-(-service_count * UVICORN_RAM_Mi // node_ram_usable)} "
        f"nodes, OR reduce service_count to {max_safe_pods}, "
        f"OR upgrade node_type_size to 'medium'/'large'"
    )
elif service_count > max_safe_pods * 0.8:
    warnings.append(
        f"Cluster near capacity: {service_count}/{max_safe_pods} safe pods "
        f"({int(100*service_count/max_safe_pods)}% utilized). "
        f"Consider adding 1-2 nodes for headroom."
    )

print("=== Config Loaded ===")
print(f"  project_name:    {raw_name}  ->  slug: {_slug}")
print(f"  service_name:    {cfg['service_name']}")
print(f"  service_version: {cfg['service_version']}")
print(f"  docker_hub_user: {cfg['docker_hub_user']}")
print(f"  exoscale_zone:   {cfg['exoscale_zone']}")
print(f"  k8s_namespace:   {cfg['k8s_namespace']}")
print(f"  k8s_nodeport:    {cfg['k8s_nodeport']}")
print(f"  node_count:      {node_count}")
print(f"  node_type_size:  {node_size}")
print(f"  service_count:   {service_count}")
print(f"  exo_key:         {cfg['exo_key'][:12]}...")
print(f"  exo_secret:      {cfg['exo_secret'][:8]}...")
print(f"  docker_hub_token:{cfg['docker_hub_token'][:12]}...")
print()
image = f"{cfg['docker_hub_user']}/{cfg['service_name']}:{cfg['service_version']}"
print(f"  Image will be:        {image}")
print(f"  Resource prefix will: {_slug}-*")
print()
print(f"  Cluster capacity:     {cluster_capacity_Mi}Mi  ({node_count} x {node_ram_usable}Mi)")
print(f"  Max safe pods:        {max_safe_pods}  (at {UVICORN_RAM_Mi}Mi/pod)")
print(f"  Requested services:   {service_count}")
print()

for w in warnings:
    print(f"  WARNING: {w}")
for e in errors:
    print(f"  ERROR:   {e}")

if errors:
    print("\nPREFLIGHT FAILED -- fix errors above before deploying.")
    sys.exit(1)
elif warnings:
    print("Preflight complete with warnings -- review above before deploying.")
else:
    print("All config keys present -- READY TO DEPLOY")
