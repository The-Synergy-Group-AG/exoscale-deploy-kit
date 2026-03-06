#!/usr/bin/env python3
"""
Patch teardown.py to use the correct Exoscale resource deletion sequence:
  1. Delete Load Balancer   (was Step 4 — moved to Step 3)
  2. Delete SKS Node Pools  (was Step 3a — now Step 3b)
  3. Delete SKS Clusters    (was Step 3b — now Step 3c)
  4. Delete Security Groups (was Step 5 — now Step 4)

LESSON 43 (User-confirmed correct sequence, 2026-03-06):
  Delete LB first → prevents cloud-controller from blocking nodepool/cluster deletion.
  Nodepools before clusters → Exoscale API requirement.
  SGs last → VMs must be fully released first.
"""
from pathlib import Path

f = Path(__file__).parent / "teardown.py"
original = f.read_text()

# ── Patch 1: Update module-level docstring sequence (lines 11-14) ──────────
old_docstring_seq = """  2. SKS Nodepools (must be deleted before cluster)
  3. SKS Cluster
\x20\x20\x20\x20(NLBs are cleaned up by Exoscale automatically when cluster is deleted)
  5. Security Groups (with retry — clusters must fully release SG locks first)"""

new_docstring_seq = """  2. Load Balancer (FIRST — must be deleted before nodepools/cluster, LESSON 43)
  3. SKS Nodepools  (must be deleted before cluster)
  4. SKS Cluster
  5. Security Groups (with retry — clusters must fully release SG locks first)"""

# ── Patch 2: Swap Step 3 (Clusters) and Step 4 (LBs) blocks ────────────────
old_step3_to_end = """    # ── Step 3: Delete SKS Clusters + Nodepools ───────────────────────────
    # LESSON 40: Uses _delete_nodepool_robust for each nodepool (poll + backoff).
    # Each nodepool gets up to 12 min patience. After all nodepools are handled,
    # cluster deletion is attempted regardless of nodepool deletion outcome.
    section("Step 3: SKS Cluster Teardown")
    for cl in proj_clusters:
        cluster_id   = cl.get("id")
        cluster_name = cl.get("name")
        nps          = cl.get("nodepools", [])

        # Delete nodepools first (required before cluster deletion)
        for np in nps:
            _delete_nodepool_robust(c, cluster_id, np.get("id"), np.get("name", np.get("id")), results)

        # Delete cluster — attempt even if nodepool deletion partially failed,
        # Exoscale will reject with 400 if nodepools remain (error captured below).
        log(f"Deleting SKS cluster: {cluster_name} ({cluster_id})...")
        try:
            op    = c.delete_sks_cluster(id=cluster_id)
            op_id = op.get("id")
            if op_id:
                log(f"  Waiting for cluster deletion (op:{op_id})...")
                c.wait(op_id, max_wait_time=600)
            ok(f"SKS cluster deleted: {cluster_name}")
            results["deleted"].append({"type": "sks_cluster", "id": cluster_id, "name": cluster_name})
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not found" in err_str.lower():
                ok(f"Cluster already deleted: {cluster_name}")
                results["deleted"].append({"type": "sks_cluster", "id": cluster_id, "name": cluster_name})
            else:
                warn(f"Cluster {cluster_name}: {err_str[:100]}")
                results["errors"].append({"type": "sks_cluster", "id": cluster_id, "error": err_str[:100]})

    # ── Step 4: Delete Network Load Balancers ─────────────────────────────
    section("Step 4: Load Balancer Teardown")
    for nlb in proj_nlbs:
        nlb_id   = nlb.get("id")
        nlb_name = nlb.get("name")
        log(f"Deleting NLB: {nlb_name} ({nlb_id})...")
        try:
            op    = c.delete_load_balancer(id=nlb_id)
            op_id = op.get("id")
            if op_id:
                c.wait(op_id, max_wait_time=120)
            ok(f"Load balancer deleted: {nlb_name}")
            results["deleted"].append({"type": "load_balancer", "id": nlb_id, "name": nlb_name})
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not found" in err_str.lower():
                # 404 = K8s cloud controller already deleted NLB when cluster was torn down
                # LESSON 6: NLB is managed by cloud controller — 404 here is expected and OK
                ok(f"NLB already cleaned up (auto-deleted by cloud controller): {nlb_name}")
                results["deleted"].append({"type": "load_balancer", "id": nlb_id, "name": nlb_name})
            else:
                warn(f"NLB {nlb_name}: {err_str[:100]}")
                results["errors"].append({"type": "load_balancer", "id": nlb_id, "error": err_str[:100]})

    # ── Steps 5+6: Delete Security Groups with robust retry (LESSON 40c) ──
    # _delete_sgs_robust handles both first attempt + retries internally,
    # replacing the old Step 5 (10s wait + single attempt) + Step 6 (30s retry).
    _delete_sgs_robust(c, proj_sgs, results)"""

new_step3_to_end = """    # ── Step 3: Delete Network Load Balancers ────────────────────────────
    # LESSON 43: LB must be deleted FIRST — before nodepools and cluster.
    # This is the correct Exoscale teardown sequence confirmed 2026-03-06:
    #   1. Delete LB  2. Delete NodePools  3. Delete Cluster  4. Delete SGs
    section("Step 3: Load Balancer Teardown")
    for nlb in proj_nlbs:
        nlb_id   = nlb.get("id")
        nlb_name = nlb.get("name")
        log(f"Deleting NLB: {nlb_name} ({nlb_id})...")
        try:
            op    = c.delete_load_balancer(id=nlb_id)
            op_id = op.get("id")
            if op_id:
                c.wait(op_id, max_wait_time=120)
            ok(f"Load balancer deleted: {nlb_name}")
            results["deleted"].append({"type": "load_balancer", "id": nlb_id, "name": nlb_name})
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not found" in err_str.lower():
                ok(f"NLB already gone: {nlb_name}")
                results["deleted"].append({"type": "load_balancer", "id": nlb_id, "name": nlb_name})
            else:
                warn(f"NLB {nlb_name}: {err_str[:100]}")
                results["errors"].append({"type": "load_balancer", "id": nlb_id, "error": err_str[:100]})

    # ── Step 3b: Delete SKS Node Pools ────────────────────────────────────
    # LESSON 40: Uses _delete_nodepool_robust for each nodepool (poll + backoff).
    # Each nodepool gets up to 12 min patience.
    # LESSON 43: Nodepools after LB, before cluster.
    section("Step 3b: SKS Node Pool Teardown")
    for cl in proj_clusters:
        cluster_id   = cl.get("id")
        cluster_name = cl.get("name")
        nps          = cl.get("nodepools", [])
        for np in nps:
            _delete_nodepool_robust(c, cluster_id, np.get("id"), np.get("name", np.get("id")), results)

    # ── Step 3c: Delete SKS Clusters ──────────────────────────────────────
    # LESSON 43: Cluster after all nodepools are deleted.
    # Exoscale will reject with 400 if nodepools remain (error captured below).
    section("Step 3c: SKS Cluster Teardown")
    for cl in proj_clusters:
        cluster_id   = cl.get("id")
        cluster_name = cl.get("name")
        log(f"Deleting SKS cluster: {cluster_name} ({cluster_id})...")
        try:
            op    = c.delete_sks_cluster(id=cluster_id)
            op_id = op.get("id")
            if op_id:
                log(f"  Waiting for cluster deletion (op:{op_id})...")
                c.wait(op_id, max_wait_time=600)
            ok(f"SKS cluster deleted: {cluster_name}")
            results["deleted"].append({"type": "sks_cluster", "id": cluster_id, "name": cluster_name})
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not found" in err_str.lower():
                ok(f"Cluster already deleted: {cluster_name}")
                results["deleted"].append({"type": "sks_cluster", "id": cluster_id, "name": cluster_name})
            else:
                warn(f"Cluster {cluster_name}: {err_str[:100]}")
                results["errors"].append({"type": "sks_cluster", "id": cluster_id, "error": err_str[:100]})

    # ── Step 4: Delete Security Groups (LESSON 40c + 43) ──────────────────
    # _delete_sgs_robust handles retries: 5 attempts × 60s patience.
    # Must come after cluster + nodepools are fully deleted (SG lock released).
    _delete_sgs_robust(c, proj_sgs, results)"""

# ── Also update module docstring if present ────────────────────────────────
old_module_line = "  2. SKS Nodepools (must be deleted before cluster)"
new_module_lines = "  2. Load Balancer (FIRST — before nodepools, LESSON 43)"

# Apply patches
patched = original

# Patch the main execution block (step swap)
if old_step3_to_end in patched:
    patched = patched.replace(old_step3_to_end, new_step3_to_end)
    print("[OK] Patch 1: Swapped Step 3 (clusters) ↔ Step 4 (LBs) → correct sequence")
else:
    print("[WARN] Patch 1: Target block not found — check for whitespace/line ending differences")

# Patch module docstring
old_doc = "  2. SKS Nodepools (must be deleted before cluster)\n  3. SKS Cluster\n    (NLBs are cleaned up by Exoscale automatically when cluster is deleted)\n  5. Security Groups (with retry — clusters must fully release SG locks first)"
new_doc = "  2. Load Balancer  (FIRST — before nodepools/cluster, LESSON 43)\n  3. SKS Nodepools  (must be deleted before cluster)\n  4. SKS Cluster\n  5. Security Groups (with retry — clusters must fully release SG locks first)"
if old_doc in patched:
    patched = patched.replace(old_doc, new_doc)
    print("[OK] Patch 2: Updated module docstring sequence")
else:
    # Try simpler replacement of just line 11
    simple_old = "  2. SKS Nodepools (must be deleted before cluster)"
    simple_new = "  2. Load Balancer  (FIRST — before nodepools/cluster, LESSON 43)\n  2b. SKS Nodepools  (must be deleted before cluster)"
    if simple_old in patched:
        patched = patched.replace(simple_old, simple_new)
        print("[OK] Patch 2 (simple): Updated module docstring line")
    else:
        print("[WARN] Patch 2: Docstring line not found — manual update needed")

# Write result
if patched != original:
    f.write_text(patched)
    print(f"[OK] teardown.py updated")
else:
    print("[WARN] No changes made — patches may not have matched")

# Verify line count
import subprocess
result = subprocess.run(["wc", "-l", str(f)], capture_output=True, text=True)
print(f"Line count: {result.stdout.strip()}")
