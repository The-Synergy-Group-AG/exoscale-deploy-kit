#!/usr/bin/env python3
"""
Nuke ALL JTP Exoscale resources.

LESSON 43 — Correct teardown sequence (user-confirmed 2026-03-06):
  1. Delete Load Balancer   (FIRST — before nodepools/cluster)
  2. Delete SKS Node Pools  (before cluster)
  3. Delete SKS Clusters
  4. Delete Security Groups (last — SG locks released only after VMs fully stop)
"""
import os, time
from pathlib import Path

for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from exoscale.api.v2 import Client

ZONE    = "ch-dk-2"
API_URL = f"https://api-{ZONE}.exoscale.com/v2"
c = Client(os.environ["EXO_API_KEY"], os.environ["EXO_API_SECRET"], url=API_URL)

def wait_op(op_id: str, label: str, max_wait: int = 300) -> bool:
    for _ in range(max_wait // 5):
        try:
            op = c.get_operation(id=op_id)
            state = op.get("state", "pending")
            if state == "success":
                print(f"  [OK] {label}")
                return True
            if state in ("failure", "timeout"):
                print(f"  [FAIL] {label}: {state}")
                return False
        except Exception:
            pass
        time.sleep(5)
    print(f"  [TIMEOUT] {label}")
    return False

print("=== LISTING ALL RESOURCES ===")
clusters = c.list_sks_clusters().get("sks-clusters", [])
lbs      = c.list_load_balancers().get("load_balancers", [])
sgs      = [s for s in c.list_security_groups().get("security-groups", []) if "jtp" in s.get("name","").lower()]
print(f"Clusters: {len(clusters)}  LBs: {len(lbs)}  SGs(jtp): {len(sgs)}\n")

print("=== STEP 1: Delete Load Balancers ===")
for lb in lbs:
    print(f"Deleting LB: {lb['name']} ({lb['id']})...")
    try:
        op = c.delete_load_balancer(id=lb["id"])
        op_id = op.get("id") or op.get("reference", {}).get("id")
        if op_id:
            wait_op(op_id, f"delete LB {lb['name']}")
        else:
            print(f"  LB delete initiated")
    except Exception as e:
        print(f"  ERR: {e}")

print("\n=== STEP 2: Delete SKS Node Pools ===")
for cl in clusters:
    for np in cl.get("nodepools", []):
        print(f"Deleting nodepool: {np['name']} from cluster {cl['name']}...")
        try:
            op = c.delete_sks_nodepool(id=cl["id"], sks_nodepool_id=np["id"])
            op_id = op.get("id") or op.get("reference", {}).get("id")
            if op_id:
                wait_op(op_id, f"delete pool {np['name']}", max_wait=600)
        except Exception as e:
            print(f"  ERR: {e}")

print("\n=== STEP 3: Delete SKS Clusters ===")
for cl in clusters:
    print(f"Deleting cluster: {cl['name']} ({cl['id']})...")
    try:
        op = c.delete_sks_cluster(id=cl["id"])
        op_id = op.get("id") or op.get("reference", {}).get("id")
        if op_id:
            wait_op(op_id, f"delete cluster {cl['name']}", max_wait=600)
    except Exception as e:
        print(f"  ERR: {e}")

print("\n=== STEP 4: Delete Security Groups ===")
print("Waiting 30s for VMs to release SG locks...")
time.sleep(30)
sgs = [s for s in c.list_security_groups().get("security-groups", []) if "jtp" in s.get("name","").lower()]
for s in sgs:
    for attempt in range(1, 6):
        try:
            c.delete_security_group(id=s["id"])
            print(f"  [OK] Deleted SG: {s['name']}")
            break
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                print(f"  [OK] SG already gone: {s['name']}")
                break
            if attempt < 5:
                print(f"  Attempt {attempt}/5: {str(e)[:60]} — waiting 60s")
                time.sleep(60)
            else:
                print(f"  [FAIL] {s['name']}: {str(e)[:80]}")

print("\n=== FINAL CHECK ===")
clusters_r = c.list_sks_clusters().get("sks-clusters", [])
lbs_r      = c.list_load_balancers().get("load_balancers", [])
instances_r = c.list_instances().get("instances", [])
sgs_r      = [s for s in c.list_security_groups().get("security-groups", []) if "jtp" in s.get("name","").lower()]
print(f"Clusters: {len(clusters_r)}  LBs: {len(lbs_r)}  Instances: {len(instances_r)}  SGs: {len(sgs_r)}")
if not clusters_r and not lbs_r and not sgs_r:
    print("[OK] ALL RESOURCES TORN DOWN")
else:
    print("[WARN] Some resources remain — check Exoscale Console")
