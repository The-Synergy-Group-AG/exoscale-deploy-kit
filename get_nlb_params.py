#!/usr/bin/env python3
"""Dump valid parameters for update_load_balancer_service."""
import os
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

fn = c.update_load_balancer_service
# Inspect closures to find normalized_names and body
try:
    cells = fn.__closure__
    if cells:
        for i, cell in enumerate(cells):
            try:
                val = cell.cell_contents
                if isinstance(val, (dict, list, set)):
                    print(f"closure[{i}]: {type(val).__name__} = {val}")
            except ValueError:
                pass
except Exception as e:
    print(f"closure error: {e}")

# Also try create_load_balancer_service to compare
fn2 = c.create_load_balancer_service
try:
    cells2 = fn2.__closure__
    if cells2:
        print("\ncreate_load_balancer_service closures:")
        for i, cell in enumerate(cells2):
            try:
                val = cell.cell_contents
                if isinstance(val, (dict, list, set)):
                    print(f"  closure[{i}]: {type(val).__name__} = {val}")
            except ValueError:
                pass
except Exception as e:
    print(f"closure2 error: {e}")
