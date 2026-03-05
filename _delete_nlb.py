#!/usr/bin/env python3
"""
Emergency NLB deletion — deletes NLB by ID to unblock SKS nodepool teardown.
LESSON 32: NLB created by K8s CCM locks the nodepool. Must delete NLB first.

Usage:
  python3 _delete_nlb.py [--nlb-id <id>] [--project jtp-test1]
"""
import argparse, os, sys, time
from pathlib import Path

# Manual .env loader (no extra dependencies)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())

try:
    from exoscale.api.v2 import Client
except ImportError:
    print("ERROR: exoscale package not installed (pip install exoscale)")
    sys.exit(1)

EXO_KEY    = os.environ.get("EXO_API_KEY", "")
EXO_SECRET = os.environ.get("EXO_API_SECRET", "")
ZONE       = os.environ.get("EXO_ZONE", "ch-dk-2")

if not EXO_KEY or not EXO_SECRET:
    print("ERROR: EXO_API_KEY / EXO_API_SECRET not set in .env")
    sys.exit(1)

parser = argparse.ArgumentParser()
parser.add_argument("--nlb-id",  help="Specific NLB ID to delete")
parser.add_argument("--project", help="Delete all NLBs matching this project prefix")
args = parser.parse_args()

c = Client(EXO_KEY, EXO_SECRET, zone=ZONE)

all_nlbs = (c.list_load_balancers() or {}).get("load-balancers", [])
print(f"Found {len(all_nlbs)} NLB(s) total")

to_delete = []
if args.nlb_id:
    to_delete = [n for n in all_nlbs if n["id"] == args.nlb_id]
elif args.project:
    to_delete = [n for n in all_nlbs if args.project.lower() in n.get("name", "").lower()]
else:
    to_delete = all_nlbs

if not to_delete:
    print("No matching NLBs found.")
    for nlb in all_nlbs:
        print(f"  Available: {nlb.get('name')} ({nlb.get('id')[:8]}...) IP={nlb.get('ip')}")
    sys.exit(0)

print(f"\nDeleting {len(to_delete)} NLB(s):")
for nlb in to_delete:
    nlb_id   = nlb["id"]
    nlb_name = nlb.get("name", "?")
    nlb_ip   = nlb.get("ip", "?")
    print(f"  Deleting NLB: {nlb_name} ({nlb_id[:8]}...) IP={nlb_ip}")
    try:
        c.delete_load_balancer(id=nlb_id)
        print(f"  OK  NLB deletion initiated")
        time.sleep(5)
    except Exception as e:
        print(f"  ERR {e}")

print("\nDone. Wait 15-30s then retry: python3 teardown.py --force")
