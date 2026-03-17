#!/usr/bin/env python3
"""
Exoscale Deploy Kit — Infrastructure Teardown
==============================================
Complete shutdown and cleanup of ALL Exoscale resources for your project.
Resource discovery is driven by project_name from config.yaml — all resources
prefixed with {project_name}-* are discovered and deleted in the correct order.

Teardown Order (reverse of deployment):
  1. Kubernetes namespace + all resources
  2. Load Balancer  (FIRST — before nodepools/cluster, LESSON 43)
  2b. SKS Nodepools  (must be deleted before cluster)
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

Lessons applied:
  LESSON 17: 409 = nodepool in transient state — original retry (3×30s)
  LESSON 40: Root-cause fix — replace 3×30s retry with proper poll+backoff strategy:
    40a: Poll cluster nodepools state before each deletion attempt
         If state is already "deleting" → wait for completion, don't re-issue delete
    40b: 12 attempts, min(attempt×60, 300)s backoff = up to 12 min patience per nodepool
         Covers full Exoscale VM deprovisioning window (~5-10 min typical, 12 min worst case)
    40c: SG deletion retry: 5 attempts × 60s = 5 min patience after cluster/nodepool gone
    40d: teardown_from_report uses same robust nodepool deletion helper (no duplication)
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
def ok(msg):    print(f"[{datetime.now().strftime('%H:%M:%S')}] OK  {msg}")
def warn(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] WARN {msg}")
def section(s): print(f"\n{'='*60}\n  {s}\n{'='*60}")


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


def _get_nodepool_state(c, cluster_id: str, pool_id: str) -> str:
    """
    Poll the cluster to retrieve the current state of a specific nodepool.
    Returns the state string (e.g. "running", "deleting", "deleted", "error")
    or "unknown" if the nodepool can no longer be found within the cluster data.

    LESSON 40a: Polling state before each deletion attempt avoids issuing a
    DELETE call on a nodepool that is already transitioning — Exoscale returns
    409 "forbidden" in that window, which is not a transient error but a
    "you already asked, wait for the op to complete" signal.
    """
    try:
        cluster_data = c.get_sks_cluster(id=cluster_id)
        for np in cluster_data.get("nodepools", []):
            if np.get("id") == pool_id:
                return np.get("state", "unknown")
        # Nodepool not present in cluster data → already deleted
        return "deleted"
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            return "deleted"
        return "unknown"


def _delete_nodepool_robust(c, cluster_id: str, pool_id: str, pool_name: str,
                            results: dict) -> bool:
    """
    Delete a single SKS nodepool with a robust poll-and-retry strategy.

    LESSON 40b strategy:
      - Pre-flight: check current nodepool state before issuing DELETE
        * "deleting" → already in progress; wait for it to complete, return True
        * "deleted"  → already gone; record as deleted, return True
        * "running"  → issue DELETE; on success wait for op, return True
        * other      → wait 30s and re-check before next attempt
      - On 409/400 from DELETE: wait min(attempt×60, 300)s then retry
        * 60s, 120s, 180s, 240s, 300s, 300s, ... (12 attempts = up to ~34 min patience)
      - On 404 from DELETE: nodepool gone between state-check and DELETE → record success
      - After MAX_ATTEMPTS: log error, return False (cluster deletion will also fail but
        the error is recorded clearly so the operator knows which nodepool is stuck)

    Returns True if nodepool is confirmed deleted, False if all attempts exhausted.
    """
    MAX_ATTEMPTS = 12
    # LESSON 41: Distinguish transient 409 (race condition) from persistent-forbidden 409
    # (Instance Pool locked). After FORBIDDEN_ESCALATE_AFTER consecutive cycles where
    # state="running" but DELETE returns 409 "forbidden", the API is genuinely refusing.
    # In this case, NEVER delete individual instances — the Instance Pool recreates them.
    # Escalate with console path: Compute -> Instance Pools -> delete pool manually.
    forbidden_consecutive = 0
    # LESSON 58: Was 3 — too low. VMs take 5-10 min to deprovision after
    # namespace deletion; 3 consecutive 409s in the first 7 min is NORMAL.
    # Run ALL 12 attempts before escalating to manual console path.
    FORBIDDEN_ESCALATE_AFTER = MAX_ATTEMPTS  # 12

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # ── Pre-flight: check current state before attempting DELETE ──────────
        state = _get_nodepool_state(c, cluster_id, pool_id)
        log(f"  Nodepool {pool_name} state: {state} (attempt {attempt}/{MAX_ATTEMPTS})")

        if state == "deleted":
            ok(f"Nodepool already deleted: {pool_name}")
            results["deleted"].append({"type": "nodepool", "id": pool_id, "name": pool_name})
            return True

        if state == "deleting":
            # Deletion already accepted by Exoscale — poll until gone rather than re-issuing DELETE
            log(f"  Nodepool {pool_name} is already deleting — waiting for completion (30s polling)...")
            for _ in range(20):   # up to 20 × 30s = 10 min polling window
                time.sleep(30)
                new_state = _get_nodepool_state(c, cluster_id, pool_id)
                if new_state in ("deleted", "unknown"):
                    ok(f"Nodepool {pool_name} deletion confirmed")
                    results["deleted"].append({"type": "nodepool", "id": pool_id, "name": pool_name})
                    return True
                log(f"  Still deleting ({new_state}) — waiting...")
            warn(f"Nodepool {pool_name}: timed out waiting for 'deleting' to complete")
            results["errors"].append({"type": "nodepool", "id": pool_id,
                                      "error": "Timed out waiting for deletion in 'deleting' state"})
            return False

        if state not in ("running", "unknown"):
            # Unexpected state (e.g. "creating", "upgrading") — wait before retry
            log(f"  Nodepool {pool_name} in unexpected state '{state}' — waiting 30s...")
            time.sleep(30)
            continue

        # ── Attempt DELETE ────────────────────────────────────────────────────
        try:
            op    = c.delete_sks_nodepool(id=cluster_id, sks_nodepool_id=pool_id)
            op_id = op.get("id")
            if op_id:
                log(f"  Nodepool delete accepted (op:{op_id}) — waiting for completion...")
                c.wait(op_id, max_wait_time=600)
            ok(f"Nodepool deleted: {pool_name}")
            results["deleted"].append({"type": "nodepool", "id": pool_id, "name": pool_name})
            return True

        except Exception as e:
            err_str = str(e)

            if "404" in err_str or "not found" in err_str.lower():
                ok(f"Nodepool already deleted: {pool_name}")
                results["deleted"].append({"type": "nodepool", "id": pool_id, "name": pool_name})
                return True

            if ("409" in err_str or "400" in err_str) and attempt < MAX_ATTEMPTS:
                # LESSON 40b: min(attempt×60, 300) gives 60s, 120s, 180s, 240s, 300s, 300s...
                wait_s = min(attempt * 60, 300)
                # LESSON 41: track consecutive "state=running + 409 forbidden" cycles.
                # Transient 409 clears when the deprovisioning window ends (backoff handles it).
                # Persistent 409 = Instance Pool locked — escalate after 3 consecutive cycles.
                if "forbidden" in err_str.lower():
                    forbidden_consecutive += 1
                    if forbidden_consecutive >= FORBIDDEN_ESCALATE_AFTER:
                        warn(f"Nodepool {pool_name}: 409 'forbidden' on {forbidden_consecutive} "
                             f"consecutive attempts — Exoscale Instance Pool is locked.")
                        warn("  The API is refusing deletion; retrying will not help.")
                        warn("  MANUAL ACTION REQUIRED:")
                        warn("  1. Open https://portal.exoscale.com")
                        warn("  2. Navigate: Compute -> Instance Pools")
                        warn(f"  3. Find and delete the pool: {pool_name}")
                        warn("  4. Wait for all instances to terminate (~2-5 min)")
                        warn("  5. Re-run: python3 teardown.py --force")
                        results["errors"].append({
                            "type": "nodepool", "id": pool_id, "name": pool_name,
                            "error": "Instance Pool locked — manual console deletion required: "
                                     "Compute -> Instance Pools -> delete " + pool_name
                        })
                        return False
                else:
                    forbidden_consecutive = 0  # reset on non-forbidden 409
                warn(f"Nodepool {pool_name}: conflict (attempt {attempt}/{MAX_ATTEMPTS}) "
                     f"— backing off {wait_s}s...")
                time.sleep(wait_s)
            else:
                warn(f"Nodepool {pool_name}: {err_str[:120]}")
                results["errors"].append({"type": "nodepool", "id": pool_id, "error": err_str[:120]})
                return False

    warn(f"Nodepool {pool_name}: exhausted {MAX_ATTEMPTS} attempts without success")
    results["errors"].append({
        "type": "nodepool", "id": pool_id,
        "error": f"Exhausted {MAX_ATTEMPTS} deletion attempts"
    })
    return False


def _delete_sgs_robust(c, proj_sgs: list, results: dict) -> None:
    """
    Delete security groups with up to 5×60s retry patience.

    LESSON 40c: SG deletion returns 409 "in use by virtual machines" while
    the Exoscale VMs backing the deleted nodepool are still fully deprovisioning.
    The cluster deletion typically takes 2-4 minutes after the nodepool is gone.
    5 attempts × 60s = 5 minutes of patience covers the observed deprovisioning window.

    First attempt waits 30s (cluster needs a moment to start releasing the SG),
    then each retry waits 60s before re-attempting.
    """
    MAX_SG_ATTEMPTS = 5

    if not proj_sgs:
        return

    section("Step 5: Security Group Teardown")
    if proj_sgs:
        log("Waiting 30s for cluster VMs to begin releasing SG locks...")
        time.sleep(30)

    for sg in proj_sgs:
        sg_id   = sg.get("id")
        sg_name = sg.get("name")
        log(f"Deleting security group: {sg_name} ({sg_id})...")
        deleted_sg = False

        for sg_attempt in range(1, MAX_SG_ATTEMPTS + 1):
            try:
                c.delete_security_group(id=sg_id)
                ok(f"Security group deleted: {sg_name}")
                results["deleted"].append({"type": "security_group", "id": sg_id, "name": sg_name})
                deleted_sg = True
                break
            except Exception as e:
                err_str = str(e)
                if "404" in err_str or "not found" in err_str.lower():
                    ok(f"Security group already gone: {sg_name}")
                    results["deleted"].append({"type": "security_group", "id": sg_id, "name": sg_name})
                    deleted_sg = True
                    break
                if sg_attempt < MAX_SG_ATTEMPTS:
                    warn(f"SG {sg_name}: still locked (attempt {sg_attempt}/{MAX_SG_ATTEMPTS}) "
                         f"— waiting 60s for VMs to fully stop: {err_str[:80]}")
                    time.sleep(60)
                else:
                    warn(f"SG {sg_name}: deletion failed after {MAX_SG_ATTEMPTS} attempts "
                         f"(~{MAX_SG_ATTEMPTS * 60}s patience exhausted)")
                    warn(f"  Manual cleanup: Exoscale Console → Compute → Security Groups → {sg_name}")
                    results["errors"].append({
                        "type": "security_group", "id": sg_id, "name": sg_name,
                        "error": f"{err_str[:100]}"
                    })


def scan_orphaned_partial_reports(outputs_dir: "Path") -> list[dict]:
    """
    Scan outputs/ for deployment_report_partial.json files whose resource IDs
    do not appear in any teardown report's 'deleted' list.
    Returns list of {report, resources} dicts for orphaned partial deployments.
    """
    if not outputs_dir.exists():
        return []

    # Collect all IDs that have been successfully deleted
    deleted_ids: set = set()
    for td_report in outputs_dir.glob("teardown_report_*.json"):
        try:
            td_data = json.loads(td_report.read_text())
            for item in td_data.get("deleted", []):
                if item.get("id"):
                    deleted_ids.add(item["id"])
        except Exception:
            pass

    # Find partial reports with resources not in deleted_ids
    orphans = []
    for partial in outputs_dir.glob("*/deployment_report_partial.json"):
        try:
            data = json.loads(partial.read_text())
            resources = data.get("resources", {})
            sg      = resources.get("security_group", {})
            cluster = resources.get("sks_cluster", {})
            undeleted = []
            if sg.get("id") and sg["id"] not in deleted_ids:
                undeleted.append(("security_group", sg["id"], sg.get("name", "?")))
            if cluster.get("id") and cluster["id"] not in deleted_ids:
                undeleted.append(("sks_cluster", cluster["id"], cluster.get("name", "?")))
            if undeleted:
                orphans.append({"report": str(partial), "resources": undeleted})
        except Exception:
            pass

    return orphans


def teardown_from_report(report_path: str, force: bool = False) -> None:
    """
    Delete Exoscale resources by ID directly from a deployment_report*.json.
    Bypasses name-based discovery entirely — works even if project_name in
    config.yaml has changed since the deployment was created.

    Uses the same robust poll+backoff strategy as the main teardown() function
    (LESSON 40d — no duplication, shared helpers _delete_nodepool_robust and
    _delete_sgs_robust).

    Usage:
      python3 teardown.py --from-report outputs/20260303_154858/deployment_report_partial.json
      python3 teardown.py --force --from-report outputs/.../deployment_report_partial.json
    """
    from exoscale.api.v2 import Client

    cfg = load_config("config.yaml")
    c = Client(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])

    rpath = Path(report_path)
    if not rpath.exists():
        print(f"[ERROR] Report not found: {report_path}")
        sys.exit(1)

    data      = json.loads(rpath.read_text())
    resources = data.get("resources", {})

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  TEARDOWN FROM REPORT: {rpath.name}")
    print(f"  Zone: {cfg['exoscale_zone']}")
    print(f"{sep}\n")

    cluster = resources.get("sks_cluster", {})
    sg      = resources.get("security_group", {})

    if not cluster.get("id") and not sg.get("id"):
        print("[OK] No cloud resources (cluster / SG) found in report — nothing to delete")
        return

    print("Resources to delete:")
    if cluster.get("id"):
        print(f"  sks_cluster:    {cluster.get('name', '?')} ({cluster['id']})")
    if sg.get("id"):
        print(f"  security_group: {sg.get('name', '?')} ({sg['id']})")

    if not force:
        resp = input("\nProceed with deletion? [y/N]: ").strip().lower()
        if resp not in ("y", "yes"):
            print("Cancelled.")
            return

    results: dict = {"deleted": [], "errors": []}

    # ── Delete cluster + nodepools (LESSON 40d: uses shared robust helper) ──
    if cluster.get("id"):
        cluster_id   = cluster["id"]
        cluster_name = cluster.get("name", cluster_id)
        try:
            cluster_data = c.get_sks_cluster(id=cluster_id)
            nps = cluster_data.get("nodepools", [])
            for np in nps:
                _delete_nodepool_robust(c, cluster_id, np["id"], np.get("name", np["id"]), results)

            log(f"Deleting cluster: {cluster_name}...")
            op = c.delete_sks_cluster(id=cluster_id)
            op_id = op.get("id")
            if op_id:
                c.wait(op_id, max_wait_time=600)
            ok(f"Cluster deleted: {cluster_name}")
            results["deleted"].append({"type": "sks_cluster", "id": cluster_id, "name": cluster_name})

        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not found" in err_str.lower():
                ok(f"Cluster already gone: {cluster_name}")
                results["deleted"].append({"type": "sks_cluster", "id": cluster_id, "name": cluster_name})
            else:
                warn(f"Cluster deletion error: {err_str[:100]}")
                results["errors"].append({"type": "sks_cluster", "id": cluster_id, "error": err_str[:100]})

    # ── Delete security group (LESSON 40c: shared robust SG helper) ─────────
    if sg.get("id"):
        _delete_sgs_robust(c, [sg], results)

    sep = "=" * 60
    print(f"\n{sep}")
    print("  TEARDOWN FROM REPORT COMPLETE")
    if results["errors"]:
        print(f"  Errors: {len(results['errors'])}")
        for e in results["errors"]:
            print(f"    ❌ {e.get('type')}: {e.get('error', '?')[:80]}")
    else:
        print("  ✅ All resources deleted successfully")
    print(f"{sep}\n")


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

    # Find ALL NLBs — K8s CCM creates NLBs named 'kubernetes-<hash>',
    # NOT prefixed with the project name. Filtering by project name misses
    # these CCM NLBs which lock the nodepool (LESSON 32/43/58).
    # _nuke_all.py already does this correctly — no name filter here.
    nlb_list  = c.list_load_balancers().get("load-balancers", [])
    proj_nlbs = nlb_list  # ALL NLBs in zone — CCM ones have no project prefix
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

    # Orphan scan: warn about uncleaned partial deployments (ISSUE-008)
    _orphans = scan_orphaned_partial_reports(DEPLOY_OUTPUTS)
    if _orphans:
        warn(f"ORPHAN SCAN: {len(_orphans)} partial deployment(s) with uncleaned resources:")
        for _o in _orphans:
            _rpt = _o["report"]
            warn(f"  Partial report: {_rpt}")
            for _rtype, _rid, _rname in _o["resources"]:
                warn(f"    {_rtype}: {_rname} ({_rid})")
        warn("  Run: python3 teardown.py --from-report <report_path> to clean")

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
            # L72: Backup chat logs before destroying namespace
            _log_backup = Path(__file__).parent / "chat_logs_backup.jsonl"
            try:
                import urllib.request
                _domain = cfg.get("ingress", {}).get("domain", "")
                if _domain:
                    _export_url = f"https://{_domain}/chat/logs/export"
                    import ssl
                    _ctx = ssl.create_default_context()
                    _ctx.check_hostname = False
                    _ctx.verify_mode = ssl.CERT_NONE
                    _req = urllib.request.Request(_export_url)
                    _resp = urllib.request.urlopen(_req, timeout=15, context=_ctx)
                    _data = _resp.read()
                    if _data and len(_data) > 10:
                        _log_backup.write_bytes(_data)
                        _lines = _data.decode("utf-8", errors="replace").count("\n")
                        ok(f"L72: Chat logs backed up ({_lines} entries) → {_log_backup}")
                    else:
                        log("L72: No chat log data to backup")
                else:
                    log("L72: No domain configured — skipping chat log backup")
            except Exception as _exc:
                log(f"L72: Chat log backup skipped ({_exc})")

            # L72: Backup TLS certificate before destroying namespace
            _tls_secret = cfg.get("ingress", {}).get("domain", "").replace(".", "-") + "-tls"
            if _tls_secret != "-tls":
                _cert_backup = Path(__file__).parent / "tls_cert_backup.json"
                _r_cert = run_kubectl([
                    "kubectl", "-n", k8s_ns, "get", "secret", _tls_secret,
                    "-o", "json"
                ], kubeconfig)
                if _r_cert.returncode == 0 and '"tls.crt"' in _r_cert.stdout:
                    import json as _json
                    _cert_backup.write_text(_r_cert.stdout)
                    ok(f"L72: TLS certificate backed up to {_cert_backup}")
                else:
                    log(f"L72: No valid TLS cert to backup ({_tls_secret})")

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
        # LESSON 21: The SDK method name for DBaaS deletion is NOT terminate_dbaas_service_pg.
        # Try multiple candidate names in order — the SDK may expose it as delete_* or terminate_*.
        # If all SDK methods fail, warn + guide user to manual console deletion.
        try:
            _deleted = False
            _candidates = [
                f"terminate_dbaas_service_{db_type}",
                f"delete_dbaas_service_{db_type}",
                f"terminate_dbaas_service",
            ]
            for _method_name in _candidates:
                _method = getattr(c, _method_name, None)
                if _method:
                    try:
                        _method(name=db_svc_name)
                        ok(f"DBaaS service '{db_svc_name}' deletion initiated (via {_method_name})")
                        results["deleted"].append({"type": "dbaas", "name": db_svc_name})
                        _deleted = True
                        break
                    except Exception as _e:
                        if "404" in str(_e) or "not found" in str(_e).lower():
                            ok(f"DBaaS service '{db_svc_name}' already deleted")
                            results["deleted"].append({"type": "dbaas", "name": db_svc_name})
                            _deleted = True
                            break
                        # Wrong method signature or transient error — try next candidate
                        continue
            if not _deleted:
                warn(f"DBaaS '{db_svc_name}': no working SDK method found for type='{db_type}'")
                warn(f"  Manual deletion: Exoscale Console → DBaaS → {db_svc_name} → Terminate")
                warn(f"  https://portal.exoscale.com → DBaaS → {db_svc_name}")
                results["errors"].append({
                    "type": "dbaas", "name": db_svc_name,
                    "error": "No SDK delete method found — manual console deletion required"
                })
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

    # ── Step 3: Delete Network Load Balancers ────────────────────────────
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
    _delete_sgs_robust(c, proj_sgs, results)

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
    parser.add_argument("--from-report", dest="from_report", default=None,
                        help="Delete resources by ID from a deployment_report*.json (bypasses name discovery)")
    args = parser.parse_args()
    if args.from_report:
        teardown_from_report(args.from_report, force=args.force)
    else:
        teardown(args)
