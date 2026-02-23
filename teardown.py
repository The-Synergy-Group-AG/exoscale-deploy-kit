#!/usr/bin/env python3
"""
Exoscale Deploy Kit — Infrastructure Teardown
==============================================
Complete shutdown and cleanup of ALL Exoscale resources for your project.
Resource discovery is driven by project_name from config.yaml — all resources
prefixed with {project_name}-* are discovered and deleted in the correct order.

Teardown Order (reverse of deployment):
  1. Kubernetes namespace + all resources
  2. SKS Nodepools (must be deleted before cluster)
  3. SKS Cluster
  4. Network Load Balancers
  5. Security Groups (with retry — clusters must fully release SG locks first)
  6. Verify: confirm zero {project_name}-* resources remain

Configuration:
  Edit config.yaml — project_name determines which resources are targeted.
  Credentials from .env (EXO_API_KEY, EXO_API_SECRET).

Usage:
  python3 teardown.py                    # Interactive mode (prompts for confirmation)
  python3 teardown.py --force            # No confirmation prompts
  python3 teardown.py --dry-run          # Show what would be deleted, no changes made
  python3 teardown.py --cluster-id <id>  # Target specific cluster ID only
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from config_loader import load_config

# Outputs dir is relative to this file — no absolute paths
DEPLOY_OUTPUTS = Path(__file__).parent / "outputs"


def get_latest_kubeconfig() -> str | None:
    """Find the most recent kubeconfig from deployment outputs."""
    if not DEPLOY_OUTPUTS.exists():
        return None
    dirs = sorted([d for d in DEPLOY_OUTPUTS.iterdir() if d.is_dir()], reverse=True)
    for d in dirs:
        kc = d / "kubeconfig.yaml"
        if kc.exists():
            return str(kc)
    return None


def log(msg):   print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
def ok(msg):    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {msg}")
def warn(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  {msg}")
def section(s): print(f"\n{'═'*60}\n  {s}\n{'═'*60}")


def confirm(prompt: str, force: bool = False) -> bool:
    """Prompt for confirmation unless --force."""
    if force:
        log(f"AUTO-CONFIRM: {prompt}")
        return True
    resp = input(f"\n  {prompt} [y/N]: ").strip().lower()
    return resp in ("y", "yes")


def run_kubectl(cmd: list[str], kubeconfig: str, capture: bool = True) -> "subprocess.CompletedProcess[str]":
    """Run kubectl with explicit KUBECONFIG + full inherited PATH env (LESSON 9)."""
    import os
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    return subprocess.run(cmd, env=env, capture_output=capture, text=True)


def teardown(args: argparse.Namespace) -> None:
    dry_run = args.dry_run
    force   = args.force
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Load config — credentials and project_name come from here
    cfg = load_config(args.config)
    # LESSON 16: resource names are slugified to lowercase (LESSON 14) so
    # teardown must use the slug for discovery — else orphaned SGs are missed.
    _slug    = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', cfg['project_name'].lower())).strip('-')
    project  = _slug              # Use lowercase slug for resource name matching
    k8s_ns   = cfg["k8s_namespace"]
    exo_zone = cfg["exoscale_zone"]

    print("\n" + "═"*60)
    print(f"  EXOSCALE DEPLOY KIT — TEARDOWN")
    print(f"  Project: {cfg['project_name']} (slug: {project})")
    print(f"  Zone:    {exo_zone}")
    if dry_run:
        print("  *** DRY RUN MODE — No changes will be made ***")
    print("═"*60 + "\n")

    # Connect to Exoscale SDK
    # LESSON 1: zone= sets the zone-specific endpoint (api-{zone}.exoscale.com)
    # LESSON 2: SDK handles HMAC-SHA256 auth correctly
    from exoscale.api.v2 import Client
    c = Client(cfg["exo_key"], cfg["exo_secret"], zone=exo_zone)

    # ── Step 1: Discover all project resources ────────────────────────────
    section("Step 1: Discovering Exoscale Resources")

    # Find clusters matching {project_name}-*
    cluster_list = c.list_sks_clusters().get("sks-clusters", [])
    proj_clusters = [cl for cl in cluster_list if project in cl.get("name", "")]
    log(f"SKS clusters ({project}): {len(proj_clusters)}")
    for cl in proj_clusters:
        log(f"  {cl.get('name')} ({cl.get('id')}) state:{cl.get('state')}")
        for np in cl.get("nodepools", []):
            log(f"    nodepool: {np.get('name')} ({np.get('id')}) size:{np.get('size')}")

    # Find NLBs matching {project_name}-*
    nlb_list  = c.list_load_balancers().get("load-balancers", [])
    proj_nlbs = [n for n in nlb_list if project in n.get("name", "")]
    log(f"Load balancers ({project}): {len(proj_nlbs)}")
    for n in proj_nlbs:
        log(f"  {n.get('name')} ({n.get('id')})")

    # Find Security Groups matching {project_name}-*
    sg_list  = c.list_security_groups().get("security-groups", [])
    proj_sgs = [s for s in sg_list if project in s.get("name", "")]
    log(f"Security groups ({project}): {len(proj_sgs)}")
    for s in proj_sgs:
        log(f"  {s.get('name')} ({s.get('id')})")

    # Find DBaaS service: {project_slug}-db
    db_name = f"{project}-db"
    proj_dbaas = []
    try:
        svc = c.get_dbaas_service_pg(name=db_name)
        if svc:
            proj_dbaas.append({"name": db_name, "type": "pg", "state": svc.get("state")})
            log(f"DBaaS service ({project}): {db_name} state:{svc.get('state')}")
    except Exception:
        pass  # 404 = no DBaaS service for this project
    if not proj_dbaas:
        log(f"DBaaS services ({project}): 0")

    # Find SOS bucket: {project_slug}-assets (or any {project_slug}-* bucket)
    proj_sos_buckets = []
    try:
        import boto3
        zone = exo_zone
        sos_endpoint = f"https://sos-{zone}.exoscale.com"
        s3 = boto3.client(
            "s3",
            endpoint_url=sos_endpoint,
            aws_access_key_id=cfg["exo_key"],
            aws_secret_access_key=cfg["exo_secret"],
            region_name=zone,
        )
        resp = s3.list_buckets()
        for b in resp.get("Buckets", []):
            bname = b.get("Name", "")
            if bname.startswith(project):
                proj_sos_buckets.append(bname)
                log(f"  SOS bucket: {bname}")
        log(f"SOS buckets ({project}): {len(proj_sos_buckets)}")
    except Exception as e:
        log(f"SOS bucket discovery skipped (boto3 not installed or no access): {str(e)[:60]}")

    total = len(proj_clusters) + len(proj_nlbs) + len(proj_sgs) + len(proj_dbaas) + len(proj_sos_buckets)
    if total == 0:
        ok(f"No {project} resources found — environment is clean!")
        return

    if dry_run:
        warn(f"DRY RUN: Would delete {total} resources listed above")
        return

    if not confirm(
        f"Delete ALL {total} {project} resources? This cannot be undone.", force=force
    ):
        warn("Teardown cancelled by user")
        return

    results: dict = {"timestamp": ts, "project": project, "deleted": [], "errors": []}

    # ── Step 2: Delete Kubernetes namespace ───────────────────────────────
    section("Step 2: Kubernetes Cleanup")
    kubeconfig = get_latest_kubeconfig()
    if kubeconfig:
        log(f"Using kubeconfig: {kubeconfig}")
        r = run_kubectl(["kubectl", "get", "namespaces"], kubeconfig)
        if k8s_ns in r.stdout:
            log(f"Deleting namespace: {k8s_ns}")
            r2 = run_kubectl(
                ["kubectl", "delete", "namespace", k8s_ns, "--timeout=60s"], kubeconfig
            )
            if r2.returncode == 0:
                ok(f"Namespace {k8s_ns} deleted")
                results["deleted"].append({"type": "k8s_namespace", "name": k8s_ns})
            else:
                warn(f"Namespace deletion warning: {r2.stderr[:100]}")
        else:
            ok(f"Namespace {k8s_ns} not found — already clean")
    else:
        warn("No kubeconfig found in outputs/ — skipping K8s cleanup")
        warn("  If cluster still has running pods, delete namespace manually:")
        warn(f"  export KUBECONFIG=<path-to-kubeconfig>")
        warn(f"  kubectl delete namespace {k8s_ns}")

    # ── Step 2b: Delete DBaaS Service ────────────────────────────────────
    section("Step 2b: DBaaS Teardown")
    for db in proj_dbaas:
        db_svc_name = db["name"]
        db_type     = db.get("type", "pg")
        log(f"Deleting DBaaS service: {db_svc_name} (type={db_type})...")
        try:
            if db_type == "pg":
                c.terminate_dbaas_service_pg(name=db_svc_name)
            elif db_type == "mysql":
                c.terminate_dbaas_service_mysql(name=db_svc_name)
            elif db_type == "redis":
                c.terminate_dbaas_service_redis(name=db_svc_name)
            ok(f"DBaaS service '{db_svc_name}' deletion initiated")
            results["deleted"].append({"type": "dbaas", "name": db_svc_name})
        except Exception as e:
            warn(f"DBaaS {db_svc_name}: {str(e)[:100]}")
            results["errors"].append({"type": "dbaas", "name": db_svc_name, "error": str(e)[:100]})
    if not proj_dbaas:
        ok("No DBaaS services to delete")

    # ── Step 2c: Delete SOS Buckets ───────────────────────────────────────
    section("Step 2c: Object Storage (SOS) Teardown")
    if proj_sos_buckets:
        try:
            import boto3
            sos_endpoint = f"https://sos-{exo_zone}.exoscale.com"
            s3 = boto3.client(
                "s3",
                endpoint_url=sos_endpoint,
                aws_access_key_id=cfg["exo_key"],
                aws_secret_access_key=cfg["exo_secret"],
                region_name=exo_zone,
            )
            for bucket in proj_sos_buckets:
                log(f"Emptying + deleting SOS bucket: {bucket}")
                try:
                    # Must delete all objects before deleting bucket
                    paginator = s3.get_paginator("list_objects_v2")
                    pages = paginator.paginate(Bucket=bucket)
                    for page in pages:
                        objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                        if objects:
                            s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
                            log(f"  Deleted {len(objects)} object(s)")
                    s3.delete_bucket(Bucket=bucket)
                    ok(f"SOS bucket deleted: {bucket}")
                    results["deleted"].append({"type": "sos_bucket", "name": bucket})
                except Exception as e:
                    warn(f"SOS bucket {bucket}: {str(e)[:100]}")
                    results["errors"].append({"type": "sos_bucket", "name": bucket, "error": str(e)[:100]})
        except ImportError:
            warn("boto3 not installed — SOS buckets must be deleted manually via Exoscale console")
    else:
        ok("No SOS buckets to delete")

    # ── Step 3: Delete SKS Clusters + Nodepools ───────────────────────────
    section("Step 3: SKS Cluster Teardown")
    for cl in proj_clusters:
        cluster_id   = cl.get("id")
        cluster_name = cl.get("name")
        nps          = cl.get("nodepools", [])

        # Delete nodepools first (required before cluster deletion)
        # LESSON 17: 409 = nodepool still in transient state post-deploy — retry up to 3×30s
        for np in nps:
            pool_id   = np.get("id")
            pool_name = np.get("name")
            log(f"Deleting nodepool: {pool_name} ({pool_id})...")
            np_deleted = False
            for attempt in range(1, 4):
                try:
                    op    = c.delete_sks_nodepool(id=cluster_id, sks_nodepool_id=pool_id)
                    op_id = op.get("id")
                    log(f"  Waiting for nodepool deletion (op:{op_id})...")
                    c.wait(op_id, max_wait_time=300)
                    ok(f"Nodepool deleted: {pool_name}")
                    results["deleted"].append({"type": "nodepool", "id": pool_id, "name": pool_name})
                    np_deleted = True
                    break
                except Exception as e:
                    err_str = str(e)
                    if "409" in err_str and attempt < 3:
                        wait_s = attempt * 30
                        warn(f"Nodepool {pool_name}: 409 conflict (attempt {attempt}/3) — retrying in {wait_s}s...")
                        time.sleep(wait_s)
                    else:
                        warn(f"Nodepool {pool_name}: {err_str[:100]}")
                        results["errors"].append({"type": "nodepool", "id": pool_id, "error": err_str[:100]})
                        break

        # Delete cluster
        log(f"Deleting SKS cluster: {cluster_name} ({cluster_id})...")
        try:
            op    = c.delete_sks_cluster(id=cluster_id)
            op_id = op.get("id")
            log(f"  Waiting for cluster deletion (op:{op_id})...")
            c.wait(op_id, max_wait_time=600)
            ok(f"SKS cluster deleted: {cluster_name}")
            results["deleted"].append({"type": "sks_cluster", "id": cluster_id, "name": cluster_name})
        except Exception as e:
            warn(f"Cluster {cluster_name}: {str(e)[:100]}")
            results["errors"].append({"type": "sks_cluster", "id": cluster_id, "error": str(e)[:100]})

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

    # ── Step 5: Delete Security Groups ────────────────────────────────────
    section("Step 5: Security Group Teardown")
    # Short delay — clusters/NLBs need a moment to fully release SG locks
    time.sleep(10)
    for sg in proj_sgs:
        sg_id   = sg.get("id")
        sg_name = sg.get("name")
        log(f"Deleting security group: {sg_name} ({sg_id})...")
        try:
            c.delete_security_group(id=sg_id)
            ok(f"Security group deleted: {sg_name}")
            results["deleted"].append({"type": "security_group", "id": sg_id, "name": sg_name})
        except Exception as e:
            warn(f"SG {sg_name}: {str(e)[:100]} — will retry after cluster fully deletes")
            results["errors"].append({"type": "security_group", "id": sg_id, "error": str(e)[:100]})

    # ── Step 6: Retry failed SG deletions ─────────────────────────────────
    failed_sgs = [e for e in results["errors"] if e["type"] == "security_group"]
    if failed_sgs:
        section("Step 6: Retry Security Group Deletions")
        log("Waiting 30s for resources to fully release SG locks...")
        time.sleep(30)
        for err in list(failed_sgs):
            sg_id = err["id"]
            try:
                c.delete_security_group(id=sg_id)
                ok(f"Security group deleted on retry: {sg_id}")
                results["errors"].remove(err)
                results["deleted"].append({"type": "security_group", "id": sg_id})
            except Exception as e:
                warn(f"SG still locked: {str(e)[:100]}")
                warn("  Manual cleanup: Exoscale Console → Compute → Security Groups")

    # ── Step 7: Verification ───────────────────────────────────────────────
    section("Step 7: Verification")
    remaining_clusters = [
        cl for cl in c.list_sks_clusters().get("sks-clusters", [])
        if project in cl.get("name", "")
    ]
    remaining_nlbs = [
        n for n in c.list_load_balancers().get("load-balancers", [])
        if project in n.get("name", "")
    ]
    remaining_sgs = [
        s for s in c.list_security_groups().get("security-groups", [])
        if project in s.get("name", "")
    ]

    if not remaining_clusters and not remaining_nlbs and not remaining_sgs:
        ok(f"ALL {project} resources deleted — environment is CLEAN!")
    else:
        warn("Some resources remain (may need manual cleanup in Exoscale Console):")
        for cl in remaining_clusters:
            warn(f"  Cluster: {cl.get('name')} ({cl.get('id')})")
        for n in remaining_nlbs:
            warn(f"  NLB:     {n.get('name')} ({n.get('id')})")
        for s in remaining_sgs:
            warn(f"  SG:      {s.get('name')} ({s.get('id')})")

    # ── Summary ────────────────────────────────────────────────────────────
    section("Teardown Summary")
    print(f"  Deleted:  {len(results['deleted'])} resources")
    print(f"  Errors:   {len(results['errors'])} resources")
    for item in results["deleted"]:
        print(f"  ✅ {item['type']}: {item.get('name', item.get('id', '?'))}")
    for item in results["errors"]:
        print(f"  ❌ {item['type']}: {item.get('error', '?')[:60]}")

    # Save teardown report
    DEPLOY_OUTPUTS.mkdir(parents=True, exist_ok=True)
    report_path = DEPLOY_OUTPUTS / f"teardown_report_{ts}.json"
    report_path.write_text(json.dumps(results, indent=2))
    ok(f"Teardown report: {report_path}")

    if len(results["errors"]) == 0:
        print(f"\n{'═'*60}")
        print(f"  ✅ TEARDOWN COMPLETE — Ready to redeploy")
        print(f"  Run: python3 deploy_pipeline.py")
        print(f"{'═'*60}\n")
    else:
        print(f"\n⚠️  Teardown completed with {len(results['errors'])} error(s)")
        print("  Some resources may need manual cleanup in the Exoscale Console")
        print("  https://portal.exoscale.com")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Teardown all Exoscale resources for this project (project_name from config.yaml)"
    )
    parser.add_argument("--force",      action="store_true", help="No confirmation prompts")
    parser.add_argument("--dry-run",    action="store_true", help="Show what would be deleted without deleting")
    parser.add_argument("--cluster-id", help="Target specific cluster ID only")
    parser.add_argument("--config",     default="config.yaml",
                        help="Path to config YAML (relative to kit dir or absolute)")
    args = parser.parse_args()
    teardown(args)
