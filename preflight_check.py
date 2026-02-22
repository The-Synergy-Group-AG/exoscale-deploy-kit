#!/usr/bin/env python3
"""Pre-flight check — verify config loads correctly before deploying."""
from config_loader import load_config

cfg = load_config()
print("=== Config Loaded ===")
print(f"  project_name:    {cfg['project_name']}")
print(f"  service_name:    {cfg['service_name']}")
print(f"  service_version: {cfg['service_version']}")
print(f"  docker_hub_user: {cfg['docker_hub_user']}")
print(f"  exoscale_zone:   {cfg['exoscale_zone']}")
print(f"  k8s_namespace:   {cfg['k8s_namespace']}")
print(f"  k8s_nodeport:    {cfg['k8s_nodeport']}")
print(f"  node_count:      {cfg['node_count']}")
print(f"  exo_key:         {cfg['exo_key'][:12]}...")
print(f"  exo_secret:      {cfg['exo_secret'][:8]}...")
print(f"  docker_hub_token:{cfg['docker_hub_token'][:12]}...")
print()
image = f"{cfg['docker_hub_user']}/{cfg['service_name']}:{cfg['service_version']}"
print(f"  Image will be:   {image}")
print()
print("All config keys present — READY TO DEPLOY")
