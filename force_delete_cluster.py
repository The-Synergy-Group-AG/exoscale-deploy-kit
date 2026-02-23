"""Direct cluster/nodepool deletion — bypasses teardown.py wrapper.

Usage:
  python -X utf8 force_delete_cluster.py --cluster-id <UUID>
  python -X utf8 force_delete_cluster.py   # uses IDs hard-coded below
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import load_config
from exoscale.api.v2 import Client  # correct import for exoscale==0.16.x

# ---------------------------------------------------------------------------
# Parse optional CLI arguments so teardown.py can pass the cluster ID
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Force-delete a locked SKS cluster")
parser.add_argument("--cluster-id",  default="8afee073-dd84-4057-8c75-43a0896f8579")
parser.add_argument("--nodepool-id", default="f1bff676-5694-4c1e-93c7-ca80533c1178")
parser.add_argument("--nlb-id",      default="542c67ac-4f34-4287-9ccf-aee27d03bb19",
                    help="NLB locking the Instance Pool (must be deleted first)")
args = parser.parse_args()

CLUSTER_ID  = args.cluster_id
NODEPOOL_ID = args.nodepool_id
NLB_ID      = args.nlb_id

# ---------------------------------------------------------------------------
# Load config — keys are exo_key / exo_secret (see config_loader.py)
# ---------------------------------------------------------------------------
cfg = load_config()

# Signature: Client(key, secret, zone=...) — matches teardown.py usage
c = Client(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])

# --- 1. Check cluster state ---
# The SDK returns raw dicts (not model objects) — use dict access throughout
print(f"\nChecking cluster {CLUSTER_ID} ...")
try:
    cluster = c.get_sks_cluster(id=CLUSTER_ID)
    state = cluster.get("state", "unknown") if isinstance(cluster, dict) else "unknown"
    print(f"  State : {state}")
    for np in (cluster.get("node-pools") or cluster.get("nodepools") or [] if isinstance(cluster, dict) else []):
        np_id   = np.get("id", "?") if isinstance(np, dict) else str(np)
        np_st   = np.get("state", "?") if isinstance(np, dict) else "?"
        np_size = np.get("size", "?") if isinstance(np, dict) else "?"
        print(f"  Nodepool {np_id}  state={np_st}  size={np_size}")
except Exception as e:
    print(f"  ⚠️  Could not inspect cluster (proceeding to delete anyway): {e}")

# --- 2. Delete the NLB that is locking the Instance Pool / Nodepool ---
if NLB_ID:
    print(f"\nDeleting NLB {NLB_ID} (unlocks the Instance Pool) ...")
    try:
        c.delete_load_balancer(id=NLB_ID)
        print("  ✅ NLB delete accepted")
    except Exception as e:
        print(f"  ⚠️  NLB delete: {e}")
    import time
    print("  Waiting 10 s for NLB deletion to propagate ...")
    time.sleep(10)

# --- 3. Delete nodepool ---
print(f"\nDeleting nodepool {NODEPOOL_ID} ...")
try:
    c.delete_sks_nodepool(id=CLUSTER_ID, sks_nodepool_id=NODEPOOL_ID)
    print("  ✅ Nodepool delete accepted")
except Exception as e:
    print(f"  ⚠️  Nodepool delete: {e}")

# --- 4. Delete cluster ---
print(f"\nDeleting cluster {CLUSTER_ID} ...")
try:
    c.delete_sks_cluster(id=CLUSTER_ID)
    print("  ✅ Cluster delete accepted")
except Exception as e:
    print(f"  ⚠️  Cluster delete: {e}")

print("\nDone. Check portal.exoscale.com to confirm deletion.")
