#!/usr/bin/env python3
"""
gen_deploy_v6.py — Generate deploy-v6.yaml from deploy-v5.yaml
================================================================
Changes:
  - image: iandrewitz/docker-jtp:5  → iandrewitz/docker-jtp:6
  - plan: "120"                      → plan: "121"

Usage:
    python3 gen_deploy_v6.py
"""
from pathlib import Path

src = Path(__file__).parent / "deploy-v5.yaml"
dst = Path(__file__).parent / "deploy-v6.yaml"

content = src.read_text()
content = content.replace('image: iandrewitz/docker-jtp:5', 'image: iandrewitz/docker-jtp:6')
content = content.replace('plan: "120"', 'plan: "121"')

dst.write_text(content)
print(f"✅ Generated {dst}")
print(f"   {content.count('docker-jtp:6')} image references updated to :6")
print(f"   {content.count('plan: \"121\"')} plan labels updated to 121")
