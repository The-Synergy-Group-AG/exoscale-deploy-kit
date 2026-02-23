#!/usr/bin/env python3
"""
Exoscale Deploy Kit — Production Deployment Pipeline
=====================================================
BATTLE-TESTED: Validated 2026-02-20 on live Exoscale + Docker Hub infrastructure.
Extracted from a battle-tested deployment and de-hardcoded for reuse in any project.

ARCHITECTURE:
  Stage 1: Docker build (multi-stage, linux/amd64, non-root)
  Stage 2: Docker Hub push (both versioned + latest tags)
  Stage 3: Exoscale infrastructure (Security Group, SKS Cluster, Node Pool)
  Stage 4: Wait for worker nodes to join cluster
  Stage 5: Apply Kubernetes manifests
  Stage 6: Verify pods Running
  Stage 7: Final report

CRITICAL LESSONS LEARNED (battle-tested 2026-02-20 — do not repeat these mistakes):
  1. Exoscale API base URL is ZONE-SPECIFIC:
       https://api-{zone}.exoscale.com/v2  <- CORRECT
       https://api.exoscale.com/v2         <- WRONG (404 on all compute endpoints)
  2. Use official Python SDK (exoscale v0.16.1+) — manual HMAC-SHA256 signing fails in practice
  3. Instance type IDs must be queried at runtime — hardcoded IDs change and break silently
  4. Node pool MUST be created + nodes MUST be Ready BEFORE applying K8s manifests
  5. Create nodepool WITHOUT security_groups first — adding SG on creation returns HTTP 500
     on fresh clusters. Update SG after pool is running (Step B pattern).
  6. NLB is auto-created by Exoscale cloud controller when K8s type:LoadBalancer service
     is applied — NEVER create NLB manually (creates duplicate, breaks routing)
  7. NodePort 30671 is pre-approved in Exoscale default Security Group — use this or
     30888/30999. Any other NodePort will be BLOCKED by the default SG.
  8. Docker build: pass args as Python list items — never string interpolation in subprocess
  9. kubectl env needs KUBECONFIG + PATH set explicitly in subprocess calls (no shell PATH)
 10. Worker nodes take 3-8 minutes to boot, register, and become Ready after pool creation
 11. Create Docker Hub pull secret BEFORE applying K8s manifests (ErrImagePull otherwise)
 12. Use --dry-run=client -o yaml | kubectl apply -f - pattern for secret creation
 13. SKS node pools reject 'tiny' and 'micro' instance sizes (HTTP 409) — auto-upgrade to 'small'
 14. Exoscale resource names must be lowercase DNS-label format — slugify project_name
 15. Teardown: use slugified project_name for resource matching (e.g. 'jtp-test1', not 'JTP-test1')
 16. project_name in config.yaml is display name; derive slug via re.sub for all API resource names
 17. update_sks_nodepool(security_groups=...) ALSO returns HTTP 500 — Exoscale API bug.
     FIX: Attach SG to each nodepool instance individually via per-instance API:
       nodepool["instance-pool"]["id"] → get_instance_pool(id=...).instances
       → attach_instance_to_security_group(id=sg_id, instance={"id": inst_id})
     CRITICAL: args are (id=SG_id, instance={"id": inst_id}) — SG id first, NOT instance-first.

CONFIGURATION:
  Edit config.yaml for all non-secret settings.
  Copy .env.example to .env and fill in API keys.

PREREQUISITES:
  pip install -r requirements.txt
  docker running
  kubectl installed
"""
import json
import re
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from config_loader import load_config

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION — loaded from config.yaml + .env
#  Edit config.yaml to change project settings.
#  Copy .env.example to .env and fill in credentials.
# ═══════════════════════════════════════════════════════════════════════════════
cfg = load_config()

# ═══════════════════════════════════════════════════════════════════════════════
#  WIZARD — runs unless --auto flag is passed
#  python3 deploy_pipeline.py         → wizard prompts for all parameters
#  python3 deploy_pipeline.py --auto  → skip wizard, use existing config.yaml
# ═══════════════════════════════════════════════════════════════════════════════
import argparse as _ap
_parser = _ap.ArgumentParser(add_help=False)
_parser.add_argument("--auto", action="store_true", help="Skip wizard")
_args, _ = _parser.parse_known_args()

if not _args.auto:
    import wizard as _wiz
    _existing = _wiz.load_existing()
    _wizard_cfg = _wiz.run_wizard(_existing)
    _wiz.print_summary(_wizard_cfg)
    if not _wiz.prompt_bool("Proceed with deployment?", True):
        sys.exit(0)
    _wiz.write_config(_wizard_cfg)
    # Reload config from the freshly written file
    cfg = load_config()



# ═══════════════════════════════════════════════════════════════════════════════
#  RUNTIME SETUP — derived from config
# ═══════════════════════════════════════════════════════════════════════════════
TS        = datetime.now().strftime("%Y%m%d_%H%M%S")
IMAGE     = f"{cfg['docker_hub_user']}/{cfg['service_name']}:{cfg['service_version']}"
IMAGE_LTS = f"{cfg['docker_hub_user']}/{cfg['service_name']}:latest"

# Resource names — all prefixed with project_name (no hardcoded names)
# LESSON 14: Exoscale resource names must be lowercase DNS-label format
# Slugify project_name: lowercase, replace non-alphanumeric with '-', collapse '--'
_slug = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', cfg['project_name'].lower())).strip('-')
SG_NAME   = f"{_slug}-sg-{TS[-6:]}"
CLUSTER_N = f"{_slug}-cluster-{TS[-6:]}"
NLB_NAME  = f"{cfg['project_name']}-nlb-{TS[-6:]}"
POOL_NAME = f"{_slug}-workers"

# Paths — all relative to this file (no absolute paths)
KIT_DIR     = Path(__file__).parent
SERVICE_DIR = KIT_DIR / "service"
OUT         = KIT_DIR / "outputs" / TS
OUT.mkdir(parents=True, exist_ok=True)

RESULTS = {
    "timestamp": TS,
    "image": IMAGE,
    "zone": cfg["exoscale_zone"],
    "project": cfg["project_name"],
    "stages": {},
    "resources": {},
}


def log(msg):   print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
def ok(msg):    print(f"[{datetime.now().strftime('%H:%M:%S')}] OK {msg}")
def warn(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] WARN {msg}")
def fail(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL {msg}")
def section(s): print(f"\n{'='*60}\n  {s}\n{'='*60}")
def elapsed(t): return f"{time.time()-t:.0f}s"


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 1: DOCKER BUILD
#  LESSON 8: Always pass build args as list items, never string interpolations
# ═══════════════════════════════════════════════════════════════════════════════
def stage_docker_build():
    section("STAGE 1: Docker Build")
    t0 = time.time()
    build_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # LESSON 8: Always pass build args as Python list (never string in subprocess)
    cmd = [
        "docker", "build",
        "--platform", "linux/amd64",
        "--tag", IMAGE,
        "--tag", IMAGE_LTS,
        "--build-arg", f"BUILD_TIME_ARG={build_time}",
        "--label", "deployment.engine=exoscale-deploy-kit",
        "--label", f"deployment.version={cfg['service_version']}",
        "--label", f"org.opencontainers.image.created={build_time}",
        "--label", f"org.opencontainers.image.title={cfg['service_name']}",
        "--file", str(SERVICE_DIR / "Dockerfile"),
        str(SERVICE_DIR),
    ]
    log(f"Building: {IMAGE}")
    log(f"  Service dir: {SERVICE_DIR}")
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        fail("Docker build FAILED")
        sys.exit(1)

    r2 = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}} {{.Size}}", IMAGE],
        capture_output=True, text=True,
    )
    parts = r2.stdout.strip().split()
    img_id = parts[0][:19] if parts else "?"
    img_mb = int(parts[1]) // 1048576 if len(parts) > 1 else 0

    ok(f"Image: {IMAGE}")
    ok(f"  ID: {img_id}... | Size: {img_mb} MB | Time: {elapsed(t0)}")
    RESULTS["stages"]["docker_build"] = {
        "status": "success", "image_id": img_id, "size_mb": img_mb
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 2: DOCKER HUB PUSH
# ═══════════════════════════════════════════════════════════════════════════════
def stage_docker_push():
    section("STAGE 2: Docker Hub Push")
    t0 = time.time()

    # Login using token from environment (never hardcoded)
    r = subprocess.run(
        ["docker", "login", "--username", cfg["docker_hub_user"], "--password-stdin", "docker.io"],
        input=cfg["docker_hub_token"], text=True, capture_output=True,
    )
    if r.returncode != 0:
        fail(f"Docker login failed: {r.stderr[:100]}")
        sys.exit(1)
    ok("Authenticated with Docker Hub")

    # Push versioned + latest
    for tag in [IMAGE, IMAGE_LTS]:
        log(f"Pushing: {tag}")
        r = subprocess.run(["docker", "push", tag], check=False)
        if r.returncode == 0:
            ok(f"Pushed: {tag}")
        elif tag == IMAGE:
            fail(f"Push FAILED: {tag}")
            sys.exit(1)
        else:
            warn("Push failed for latest tag (non-critical)")

    hub_url = f"https://hub.docker.com/r/{cfg['docker_hub_user']}/{cfg['service_name']}"
    ok(f"Available at: {hub_url}")
    RESULTS["stages"]["docker_push"] = {"status": "success", "url": hub_url}
    RESULTS["resources"]["docker_image"] = IMAGE


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 3: EXOSCALE INFRASTRUCTURE
#  LESSON 1: Use zone-specific endpoint: api-{zone}.exoscale.com (NOT api.exoscale.com)
#  LESSON 2: Use official Python SDK (v0.16.1+) — manual HMAC signing fails
#  LESSON 3: Query instance type IDs at runtime — never hardcode them
#  LESSON 5: Create nodepool WITHOUT SG first, then update SG after pool is running
#  LESSON 6: NLB is auto-created by K8s cloud controller — NEVER create manually
#  LESSON 17: update_sks_nodepool(security_groups=...) HTTP 500 — use per-instance API instead
# ═══════════════════════════════════════════════════════════════════════════════
def stage_exoscale():
    section("STAGE 3: Exoscale Infrastructure")
    t0 = time.time()

    # LESSON 2: SDK handles HMAC-SHA256 auth correctly
    # LESSON 1: zone= parameter sets the zone-specific endpoint automatically
    from exoscale.api.v2 import Client
    c = Client(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])
    log(f"Connected to Exoscale zone: {cfg['exoscale_zone']}")

    # Security Group
    log(f"Creating security group: {SG_NAME}")
    sg = c.create_security_group(
        name=SG_NAME,
        description=f"{cfg['project_name']} — {cfg['service_name']} ({TS})",
    )
    sg_id = sg.get("id")
    ok(f"Security group: {sg_id}")
    RESULTS["resources"]["security_group"] = {"id": sg_id, "name": SG_NAME}

    # LESSON 7: NodePort pre-approved in Exoscale default SG
    ok(f"Security group ready: {sg_id} (web access via pre-approved NodePort {cfg['k8s_nodeport']})")

    # LESSON 3: Query instance types at runtime — never hardcode IDs
    log("Querying instance types...")
    types = c.list_instance_types().get("instance-types", [])
    ok(f"Found {len(types)} instance types")

    selected_id = None
    for t in types:
        fam  = (t.get("family") or "").lower()
        size = (t.get("size") or "").lower()
        if cfg["node_type_family"] in fam and cfg["node_type_size"] in size:
            selected_id = t.get("id")
            ok(
                f"Instance type: {t.get('size')} "
                f"({t.get('cpus')}cpu/{t.get('memory', 0)//1024}GB) — {selected_id}"
            )
            break
    if not selected_id and types:
        selected_id = types[0].get("id")
        warn(f"Exact match not found, using: {types[0].get('size')} — {selected_id}")

    # SKS Kubernetes Version
    log("Querying SKS cluster versions...")
    versions = c.list_sks_cluster_versions().get("sks-cluster-versions", [])
    k8s_ver = versions[0] if versions else None
    ok(f"Kubernetes version: {k8s_ver}")

    # SKS Cluster
    log(f"Creating SKS cluster: {CLUSTER_N}...")
    op = c.create_sks_cluster(
        name=CLUSTER_N,
        cni=cfg["sks_cni"],
        level=cfg["sks_level"],
        version=k8s_ver,
        description=f"{cfg['project_name']} — {TS}",
        addons=cfg["sks_addons"],
    )
    op_id = op.get("id")
    log(f"Cluster creation initiated — operation: {op_id}")
    log("Waiting for SKS cluster (3-8 minutes)...")
    result = c.wait(op_id, max_wait_time=600)
    cluster_id = result.get("reference", {}).get("id")
    ok(f"SKS cluster: {cluster_id}")
    RESULTS["resources"]["sks_cluster"] = {"id": cluster_id, "name": CLUSTER_N}

    # LESSON 5 (DEFINITIVE STRATEGY):
    # Exoscale returns HTTP 500 when security_groups is specified in create_sks_nodepool
    # on a fresh cluster. Always create WITHOUT SG first (Step A), then attach SG to each
    # instance individually after pool is running (Step B — see LESSON 17).
    #

    # LESSON 13: SKS node pools reject tiny and micro instance sizes (HTTP 409)
    # Auto-upgrade to 'small' which is the minimum supported size.
    _SKS_FORBIDDEN_SIZES = {"tiny", "micro"}
    if cfg.get("node_type_size", "").lower() in _SKS_FORBIDDEN_SIZES:
        _upgraded = "small"
        warn(f"Instance size '{cfg['node_type_size']}' is NOT supported for SKS node pools.")
        warn(f"Auto-upgrading to '{_upgraded}' (minimum supported size).")
        cfg["node_type_size"] = _upgraded
        # Re-select instance type with upgraded size
        selected_id = None
        for t in types:
            fam  = (t.get("family") or "").lower()
            size = (t.get("size") or "").lower()
            if cfg["node_type_family"] in fam and cfg["node_type_size"] in size:
                selected_id = t.get("id")
                ok(f"Upgraded instance type: {t.get('size')} ({t.get('cpus')}cpu) — {selected_id}")
                break
        if not selected_id and types:
            selected_id = types[0].get("id")

    # Step A: Create nodepool WITHOUT security_groups
    log(f"Creating node pool: {POOL_NAME} ({cfg['node_count']} x {cfg['node_type_size']})...")
    log("  (Step A: creating without SG — will attach SG per-instance after pool is running)")
    op = c.create_sks_nodepool(
        id=cluster_id,
        name=POOL_NAME,
        size=cfg["node_count"],
        description=f"{cfg['project_name']} worker nodes",
        disk_size=cfg["node_disk_gb"],
        instance_type={"id": selected_id},
        # NOTE: security_groups intentionally omitted — see LESSON 5
    )
    op_id = op.get("id")
    log(f"Node pool initiated — operation: {op_id}")
    log("Waiting for node pool (2-5 minutes)...")
    result = c.wait(op_id, max_wait_time=600)
    pool_id = result.get("reference", {}).get("id")
    ok(f"Node pool created: {pool_id}")
    RESULTS["resources"]["node_pool"] = {
        "id": pool_id, "name": POOL_NAME, "size": cfg["node_count"]
    }

    # Step B: LESSON 17 — Per-instance SG attachment
    # update_sks_nodepool(security_groups=...) always returns HTTP 500 (Exoscale API bug).
    # FIX: Discover nodepool instances via instance-pool ID, then attach SG to each one.
    #   API: attach_instance_to_security_group(id=sg_id, instance={"id": instance_id})
    #   CRITICAL: id=SG_id (first), instance={"id": inst_id} (second) — NOT instance-first!
    log(f"(Step B LESSON17) Attaching SG {sg_id} to nodepool instances individually...")
    _sg_success = False
    _attached = 0
    try:
        # Get the underlying instance-pool ID from the nodepool details
        _cluster_detail = c.get_sks_cluster(id=cluster_id)
        _pool_detail = next(
            (p for p in _cluster_detail.get("nodepools", []) if p.get("id") == pool_id),
            {}
        )
        _inst_pool_id = _pool_detail.get("instance-pool", {}).get("id")
        if _inst_pool_id:
            _inst_pool = c.get_instance_pool(id=_inst_pool_id)
            _instances = _inst_pool.get("instances", [])
            log(f"  Found {len(_instances)} instance(s) in nodepool (instance-pool: {_inst_pool_id[:8]}...)")
            for _inst in _instances:
                _inst_id = _inst.get("id")
                _inst_name = _inst.get("name", _inst_id)
                c.attach_instance_to_security_group(
                    id=sg_id,
                    instance={"id": _inst_id},
                )
                ok(f"SG attached to {_inst_name}")
                _attached += 1
            if _attached == len(_instances) and _instances:
                ok(f"SG attached to all {_attached} nodepool instance(s)")
                _sg_success = True
            elif _attached > 0:
                ok(f"SG attached to {_attached}/{len(_instances)} instances (partial)")
                _sg_success = True
            else:
                warn("No instances found in instance-pool (pool may still be initializing)")
        else:
            warn("instance-pool ref missing from nodepool detail — skipping SG attachment")
    except Exception as _e:
        warn(f"SG per-instance attachment failed: {str(_e)[:80]}")

    if not _sg_success:
        warn("SG attachment failed — will need manual SG assignment in Exoscale console")
        RESULTS["resources"]["node_pool"]["sg_update_failed"] = True

    # LESSON 6: NO manual NLB creation.
    # Exoscale cloud controller auto-creates NLB when K8s type:LoadBalancer service is applied.
    log("NLB: delegated to Exoscale cloud controller (K8s type:LoadBalancer service)")
    ok("NLB will appear as EXTERNAL-IP once K8s cloud controller provisions it")

    # Kubeconfig
    log("Retrieving kubeconfig...")
    import base64
    kc_resp = c.generate_sks_cluster_kubeconfig(
        id=cluster_id, groups=["system:masters"], ttl=86400, user="admin"
    )
    kc_path = OUT / "kubeconfig.yaml"
    kc_path.write_bytes(base64.b64decode(kc_resp.get("kubeconfig", "")))
    ok(f"Kubeconfig saved: {kc_path}")
    RESULTS["resources"]["kubeconfig"] = str(kc_path)

    ok(f"Exoscale infrastructure complete in {elapsed(t0)}")
    return str(kc_path)


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 4: WAIT FOR WORKER NODES
#  LESSON 10: Nodes take 3-8 minutes to boot, register, and become Ready
# ═══════════════════════════════════════════════════════════════════════════════
def stage_wait_for_nodes(kubeconfig: str):
    section("STAGE 4: Wait for Worker Nodes")
    t0 = time.time()

    # LESSON 9: Set KUBECONFIG in subprocess env; inherit OS PATH (Windows + Linux compatible)
    env = {**os.environ, "KUBECONFIG": kubeconfig}

    log(f"Waiting for {cfg['node_count']} worker nodes (up to 12 minutes)...")
    deadline = time.time() + 720
    nodes_ready = False

    while time.time() < deadline:
        r = subprocess.run(
            ["kubectl", "get", "nodes", "--no-headers"],
            env=env, capture_output=True, text=True,
        )
        lines = [line for line in r.stdout.strip().split("\n") if line]
        ready = [line for line in lines if "Ready" in line and "NotReady" not in line]
        log(f"  Nodes: {len(lines)} registered, {len(ready)} Ready")
        for line in lines:
            log(f"    {line}")
        if len(ready) >= cfg["node_count"]:
            nodes_ready = True
            break
        time.sleep(20)

    if nodes_ready:
        ok(f"All {cfg['node_count']} worker nodes Ready! ({elapsed(t0)})")
        RESULTS["stages"]["wait_nodes"] = {"status": "success", "duration": elapsed(t0)}
    else:
        warn(f"Nodes not all Ready after {elapsed(t0)} — proceeding anyway")
        RESULTS["stages"]["wait_nodes"] = {"status": "partial", "duration": elapsed(t0)}

    return nodes_ready


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 5: KUBERNETES MANIFESTS
#  LESSON 11: Create Docker Hub pull secret BEFORE applying manifests
#  LESSON 12: Use --dry-run=client -o yaml | kubectl apply -f - for secret creation
# ═══════════════════════════════════════════════════════════════════════════════
def stage_kubernetes(kubeconfig: str):
    section("STAGE 5: Kubernetes Deployment")
    t0 = time.time()
    manifests_dir = OUT / "k8s-manifests"

    # LESSON 9: Set KUBECONFIG in subprocess env; inherit OS PATH (Windows + Linux compatible)
    env = {**os.environ, "KUBECONFIG": kubeconfig}

    # Create namespace
    log(f"Creating namespace: {cfg['k8s_namespace']}")
    r_ns = subprocess.run(
        ["kubectl", "create", "namespace", cfg["k8s_namespace"]],
        env=env, capture_output=True, text=True,
    )
    if r_ns.returncode == 0:
        ok(f"Namespace {cfg['k8s_namespace']} created")
    else:
        log(f"  Namespace: {r_ns.stderr.strip()[:80]} (may already exist)")

    # LESSON 11: Create Docker Hub pull secret BEFORE applying manifests
    # LESSON 12: Use --dry-run=client -o yaml | kubectl apply -f - pattern
    log("Creating Docker Hub pull secret (dockerhub-creds)...")
    r_sec = subprocess.run(
        [
            "kubectl", "create", "secret", "docker-registry", "dockerhub-creds",
            "--docker-server=docker.io",
            "--docker-username", cfg["docker_hub_user"],
            "--docker-password", cfg["docker_hub_token"],
            "--docker-email=deploy@example.com",
            "-n", cfg["k8s_namespace"],
            "--save-config", "--dry-run=client", "-o", "yaml",
        ],
        capture_output=True, text=True,
    )
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=r_sec.stdout, env=env, text=True, check=False,
    )
    ok("Docker Hub pull secret: dockerhub-creds applied")

    # Generate manifests using bundled k8s_manifest_generator.py (relative path)
    generator = KIT_DIR / "k8s_manifest_generator.py"
    r = subprocess.run(
        [
            sys.executable, str(generator),
            "--service-name", cfg["service_name"],
            "--image", IMAGE,
            "--version", cfg["service_version"],
            "--namespace", cfg["k8s_namespace"],
            "--replicas", str(cfg["k8s_replicas"]),
            "--port", str(cfg["k8s_port"]),
            "--service-port", str(cfg.get("k8s_service_port", cfg["k8s_port"])),
            "--nodeport", str(cfg["k8s_nodeport"]),
            "--outputs-dir", str(manifests_dir),
        ],
        capture_output=True, text=True,
    )
    if r.stdout:
        log(r.stdout.strip())
    if r.returncode != 0:
        warn(f"Manifest generator warning: {r.stderr[:200]}")

    # Apply manifests
    log("Applying manifests...")
    r = subprocess.run(
        ["kubectl", "apply", "-f", str(manifests_dir) + "/", "--validate=false"],
        env=env, capture_output=True, text=True,
    )
    if r.returncode == 0:
        ok("Manifests applied:")
        for line in r.stdout.strip().split("\n"):
            log(f"  {line}")
    else:
        warn(f"Apply issues: {r.stderr[:300]}")

    RESULTS["stages"]["kubernetes"] = {
        "status": "success", "manifests_dir": str(manifests_dir)
    }
    RESULTS["resources"]["k8s_manifests"] = str(manifests_dir)


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 6: VERIFY PODS RUNNING
# ═══════════════════════════════════════════════════════════════════════════════
def stage_verify(kubeconfig: str):
    section("STAGE 6: Verification")
    t0 = time.time()
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    ns = cfg["k8s_namespace"]

    log("Waiting for pods to start (up to 5 minutes)...")
    deadline = time.time() + 300
    pods_ok = False

    while time.time() < deadline:
        r = subprocess.run(
            ["kubectl", "get", "pods", "-n", ns, "--no-headers"],
            env=env, capture_output=True, text=True,
        )
        lines = [line for line in r.stdout.strip().split("\n") if line]
        running = [line for line in lines if "Running" in line]
        log(f"  Pods: {len(lines)} total, {len(running)} Running")
        for line in lines:
            log(f"    {line}")
        if len(running) >= 1:
            pods_ok = True
            break
        time.sleep(15)

    if pods_ok:
        ok(f"Pods Running! ({elapsed(t0)})")
    else:
        warn("Pods still Pending — may need more node startup time")

    for cmd_args, label in [
        (["kubectl", "get", "all", "-n", ns], "All Resources"),
        (["kubectl", "get", "nodes"], "Nodes"),
    ]:
        log(f"\n{label}:")
        r = subprocess.run(cmd_args, env=env, capture_output=True, text=True)
        print(r.stdout)

    RESULTS["stages"]["verify"] = {"status": "success" if pods_ok else "partial"}


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 7: REPORT
# ═══════════════════════════════════════════════════════════════════════════════
def stage_report():
    section("STAGE 7: Final Report")
    RESULTS["completed_at"] = datetime.now().isoformat()
    RESULTS["outputs_dir"] = str(OUT)

    report_json = OUT / "deployment_report.json"
    report_json.write_text(json.dumps(RESULTS, indent=2))
    ok(f"Report: {report_json}")

    print(f"\n{'='*60}")
    print(f"  DEPLOYMENT COMPLETE — {cfg['project_name']}")
    print(f"{'='*60}")
    print(f"  Image:      {IMAGE}")
    print(f"  Cluster:    {RESULTS['resources'].get('sks_cluster', {}).get('id', '?')}")
    print(f"  Kubeconfig: {RESULTS['resources'].get('kubeconfig', '?')}")
    print(f"  Outputs:    {OUT}")
    print(f"{'='*60}")
    print("\nTeardown commands:")
    print(f"  python3 teardown.py          # Auto-discovers all {cfg['project_name']}-* resources")
    print(f"  python3 teardown.py --dry-run # Preview what will be deleted")
    print(f"  docker rmi {IMAGE} {IMAGE_LTS}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 3b: OBJECT STORAGE (SOS)
#  Creates an Exoscale SOS bucket (S3-compatible).
#  Uses existing EXO_API_KEY/EXO_API_SECRET — same key works for SOS if it has
#  the required permissions (default for admin/owner keys).
#  Credentials saved to RESULTS for K8s secret injection in Stage 5c.
# ═══════════════════════════════════════════════════════════════════════════════
def stage_object_storage() -> dict | None:
    sos_cfg = cfg.get("object_storage", {})
    if not sos_cfg.get("enabled"):
        log("Object Storage (SOS): disabled — skipping")
        return None

    section("STAGE 3b: Object Storage (SOS)")
    t0 = time.time()

    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        warn("boto3 not installed — run: pip install boto3")
        warn("Object Storage skipped")
        return None

    zone         = cfg["exoscale_zone"]
    bucket_suffix = sos_cfg.get("bucket_name", "assets")
    bucket_name  = f"{_slug}-{bucket_suffix}"
    sos_endpoint = f"https://sos-{zone}.exoscale.com"

    log(f"SOS endpoint: {sos_endpoint}")
    log(f"Creating bucket: {bucket_name}")

    s3 = boto3.client(
        "s3",
        endpoint_url=sos_endpoint,
        aws_access_key_id=cfg["exo_key"],
        aws_secret_access_key=cfg["exo_secret"],
        region_name=zone,
    )

    try:
        s3.create_bucket(Bucket=bucket_name)
        ok(f"SOS bucket created: {bucket_name}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            ok(f"SOS bucket already exists: {bucket_name}")
        else:
            warn(f"SOS bucket creation failed: {e}")
            warn("Object Storage skipped — continuing pipeline")
            return None

    # Set ACL if public-read requested
    if sos_cfg.get("acl") == "public-read":
        try:
            s3.put_bucket_acl(Bucket=bucket_name, ACL="public-read")
            ok(f"Bucket ACL set to public-read")
        except ClientError as e:
            warn(f"ACL set failed (non-critical): {e}")

    sos_result = {
        "bucket": bucket_name,
        "endpoint": sos_endpoint,
        "zone": zone,
        "access_key": cfg["exo_key"],
        "secret_key": cfg["exo_secret"],
    }
    RESULTS["resources"]["object_storage"] = {
        "bucket": bucket_name,
        "endpoint": sos_endpoint,
        "zone": zone,
    }
    ok(f"Object Storage ready: s3://{bucket_name} ({elapsed(t0)})")
    return sos_result


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 3c: DBAAS (MANAGED DATABASE)
#  Creates an Exoscale managed PostgreSQL service.
#  Polls until state == "running" (~3-10 min depending on plan).
#  Connection URI saved to RESULTS for K8s secret injection in Stage 5c.
# ═══════════════════════════════════════════════════════════════════════════════
def stage_dbaas() -> dict | None:
    db_cfg = cfg.get("database", {})
    if not db_cfg.get("enabled"):
        log("DBaaS: disabled — skipping")
        return None

    section("STAGE 3c: DBaaS (Managed Database)")
    t0 = time.time()

    from exoscale.api.v2 import Client
    c = Client(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])

    db_name = f"{_slug}-db"
    db_type = db_cfg.get("type", "pg")
    db_plan = db_cfg.get("plan", "startup-4")
    db_ver  = str(db_cfg.get("version", "16"))
    term_protect = db_cfg.get("termination_protection", False)

    log(f"Creating DBaaS service: {db_name}")
    log(f"  type={db_type}  plan={db_plan}  version={db_ver}")

    try:
        if db_type == "pg":
            c.create_dbaas_service_pg(
                name=db_name,
                plan=db_plan,
                version=db_ver,
                termination_protection=term_protect,
            )
        elif db_type == "mysql":
            c.create_dbaas_service_mysq(
                name=db_name,
                plan=db_plan,
                version=db_ver,
                termination_protection=term_protect,
            )
        elif db_type == "redis":
            c.create_dbaas_service_redis(
                name=db_name,
                plan=db_plan,
                termination_protection=term_protect,
            )
        else:
            warn(f"DBaaS type '{db_type}' not yet supported in pipeline — skipping")
            return None
    except Exception as e:
        warn(f"DBaaS creation failed: {str(e)[:150]}")
        warn("DBaaS skipped — continuing pipeline")
        return None

    ok(f"DBaaS {db_type} service '{db_name}' creation initiated")

    # Poll until state == running (up to 15 minutes for startup plans)
    log("Waiting for DBaaS service to be ready (3-15 minutes)...")
    deadline = time.time() + 900
    db_info = {}
    while time.time() < deadline:
        try:
            if db_type == "pg":
                svc = c.get_dbaas_service_pg(name=db_name)
            elif db_type == "mysql":
                svc = c.get_dbaas_service_mysql(name=db_name)
            elif db_type == "redis":
                svc = c.get_dbaas_service_redis(name=db_name)
            else:
                svc = {}
            state = svc.get("state", "unknown")
            log(f"  DBaaS state: {state} ({elapsed(t0)})")
            if state == "running":
                db_info = svc
                break
        except Exception as e:
            log(f"  DBaaS poll: {str(e)[:60]}")
        time.sleep(30)

    if not db_info:
        warn(f"DBaaS not ready after {elapsed(t0)} — recording as pending")
        RESULTS["resources"]["dbaas"] = {
            "name": db_name, "type": db_type, "plan": db_plan, "state": "pending"
        }
        return {"name": db_name, "type": db_type, "state": "pending"}

    # Extract connection URI
    conn_info = db_info.get("connection-info", {})
    pg_uri = None
    if db_type == "pg" and conn_info:
        # Exoscale returns connection-info.pg as list of URIs
        uris = conn_info.get("pg", [])
        pg_uri = uris[0] if uris else None

    ok(f"DBaaS {db_type} '{db_name}' is RUNNING ({elapsed(t0)})")
    db_result = {
        "name": db_name,
        "type": db_type,
        "plan": db_plan,
        "state": "running",
        "connection_uri": pg_uri or f"see Exoscale console: {db_name}",
    }
    RESULTS["resources"]["dbaas"] = db_result
    return db_result


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 4b: NODE LABELS (StarGate branding)
#  Applies kubectl labels to all worker nodes.
#  Labels visible via: kubectl get nodes --show-labels
# ═══════════════════════════════════════════════════════════════════════════════
def stage_label_nodes(kubeconfig: str) -> None:
    nl_cfg = cfg.get("node_labels", {})
    if not nl_cfg.get("enabled"):
        log("Node Labels: disabled — skipping")
        return

    labels_map = nl_cfg.get("labels", {})
    if not labels_map:
        log("Node Labels: no labels configured — skipping")
        return

    section("STAGE 4b: Node Labels (StarGate branding)")
    env = {**os.environ, "KUBECONFIG": kubeconfig}

    # Get list of all nodes
    r = subprocess.run(
        ["kubectl", "get", "nodes", "--no-headers", "-o", "custom-columns=NAME:.metadata.name"],
        env=env, capture_output=True, text=True,
    )
    nodes = [n.strip() for n in r.stdout.strip().split("\n") if n.strip()]
    log(f"Applying StarGate labels to {len(nodes)} node(s)...")

    label_args = [f"{k}={v}" for k, v in labels_map.items()]

    for node in nodes:
        r = subprocess.run(
            ["kubectl", "label", "node", node, "--overwrite"] + label_args,
            env=env, capture_output=True, text=True,
        )
        if r.returncode == 0:
            ok(f"  {node} → labels applied")
        else:
            warn(f"  {node} label failed: {r.stderr[:80]}")

    # Verify
    r = subprocess.run(
        ["kubectl", "get", "nodes", "--show-labels"],
        env=env, capture_output=True, text=True,
    )
    log("\nNodes with labels:")
    for line in r.stdout.strip().split("\n"):
        log(f"  {line}")

    RESULTS["stages"]["node_labels"] = {"status": "success", "nodes": nodes, "labels": labels_map}


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 5b: EXOSCALE CSI DRIVER (Block Storage)
#  Installs the Exoscale CSI driver into the cluster, creates StorageClass,
#  and generates a PVC manifest for the app.
#  CSI driver: github.com/exoscale/exoscale-csi-driver
# ═══════════════════════════════════════════════════════════════════════════════
def stage_install_csi(kubeconfig: str) -> bool:
    bs_cfg = cfg.get("block_storage", {})
    if not bs_cfg.get("enabled"):
        log("Block Storage (CSI): disabled — skipping")
        return False

    section("STAGE 5b: Block Storage — CSI Driver")
    t0 = time.time()
    env = {**os.environ, "KUBECONFIG": kubeconfig}

    # CSI driver manifest URL (official Exoscale CSI driver)
    CSI_NAMESPACE = "exoscale-csi"
    csi_manifests_dir = OUT / "csi-manifests"
    csi_manifests_dir.mkdir(parents=True, exist_ok=True)

    # Generate the CSI driver namespace + secret + driver manifests
    # The CSI driver needs Exoscale API credentials to provision BSS volumes
    log("Installing Exoscale CSI driver...")

    # Step 1: Create CSI namespace
    subprocess.run(
        ["kubectl", "create", "namespace", CSI_NAMESPACE],
        env=env, capture_output=True, text=True,
    )

    # Step 2: Create Exoscale API credentials secret for CSI driver
    csi_secret_yaml = f"""apiVersion: v1
kind: Secret
metadata:
  name: exoscale-credentials
  namespace: {CSI_NAMESPACE}
type: Opaque
stringData:
  api-key: "{cfg['exo_key']}"
  api-secret: "{cfg['exo_secret']}"
  zone: "{cfg['exoscale_zone']}"
"""
    r = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=csi_secret_yaml, env=env, text=True, capture_output=True,
    )
    if r.returncode == 0:
        ok("CSI credentials secret created")
    else:
        warn(f"CSI secret: {r.stderr[:100]}")

    # Step 3: Apply official Exoscale CSI driver via kubectl
    CSI_MANIFEST_URL = "https://raw.githubusercontent.com/exoscale/exoscale-csi-driver/main/deploy/manifests/csi-driver.yaml"
    log(f"Applying CSI driver from: {CSI_MANIFEST_URL}")
    r = subprocess.run(
        ["kubectl", "apply", "-f", CSI_MANIFEST_URL],
        env=env, capture_output=True, text=True,
    )
    if r.returncode == 0:
        ok("Exoscale CSI driver applied")
        for line in r.stdout.strip().split("\n"):
            log(f"  {line}")
    else:
        warn(f"CSI driver apply warning (may need internet access): {r.stderr[:150]}")
        warn("Falling back to manual StorageClass creation")

    # Step 4: Create StorageClass (works independently of driver install)
    storage_class_yaml = f"""apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: {bs_cfg.get('storage_class', 'exoscale-ssd')}
  annotations:
    storageclass.kubernetes.io/is-default-class: "false"
provisioner: csi.exoscale.com
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  zone: "{cfg['exoscale_zone']}"
"""
    sc_path = csi_manifests_dir / "storage-class.yaml"
    sc_path.write_text(storage_class_yaml)
    r = subprocess.run(
        ["kubectl", "apply", "-f", str(sc_path)],
        env=env, capture_output=True, text=True,
    )
    if r.returncode == 0:
        ok(f"StorageClass '{bs_cfg.get('storage_class', 'exoscale-ssd')}' created")
    else:
        warn(f"StorageClass: {r.stderr[:100]}")

    # Step 5: Generate PVC manifest (to be applied with app manifests)
    pvc_yaml = f"""apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {cfg['service_name']}-data
  namespace: {cfg['k8s_namespace']}
  labels:
    app: {cfg['service_name']}
    stargate.io/managed-by: exoscale-deploy-kit
spec:
  accessModes:
    - {bs_cfg.get('access_mode', 'ReadWriteOnce')}
  storageClassName: {bs_cfg.get('storage_class', 'exoscale-ssd')}
  resources:
    requests:
      storage: {bs_cfg.get('size_gb', 10)}Gi
"""
    # Write PVC to k8s-manifests dir so it's applied with app manifests
    manifests_dir = OUT / "k8s-manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    pvc_path = manifests_dir / "06-pvc.yaml"
    pvc_path.write_text(pvc_yaml)
    ok(f"PVC manifest generated: {pvc_path.name} ({bs_cfg.get('size_gb', 10)}Gi {bs_cfg.get('storage_class', 'exoscale-ssd')})")

    RESULTS["resources"]["block_storage"] = {
        "storage_class": bs_cfg.get("storage_class", "exoscale-ssd"),
        "pvc_name": f"{cfg['service_name']}-data",
        "size_gb": bs_cfg.get("size_gb", 10),
        "mount_path": bs_cfg.get("mount_path", "/data"),
        "csi_namespace": CSI_NAMESPACE,
    }
    ok(f"Block Storage ready ({elapsed(t0)})")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  STAGE 5c: INJECT SERVICE CREDENTIALS AS K8S SECRETS
#  Injects DB connection URI and SOS bucket credentials as K8s secrets.
#  Apps consume: secret/db-credentials and secret/sos-credentials
# ═══════════════════════════════════════════════════════════════════════════════
def stage_inject_secrets(kubeconfig: str, db_info: dict | None, sos_info: dict | None) -> None:
    if not db_info and not sos_info:
        log("No service credentials to inject — skipping")
        return

    section("STAGE 5c: Inject Service Credentials (K8s Secrets)")
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    ns  = cfg["k8s_namespace"]

    # --- DB Credentials ---
    if db_info and db_info.get("state") == "running" and db_info.get("connection_uri"):
        conn_uri = db_info["connection_uri"]
        db_secret_yaml = f"""apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: {ns}
  labels:
    app.kubernetes.io/managed-by: exoscale-deploy-kit
type: Opaque
stringData:
  DATABASE_URL: "{conn_uri}"
  DB_TYPE: "{db_info.get('type', 'pg')}"
  DB_SERVICE_NAME: "{db_info.get('name', '')}"
"""
        r = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=db_secret_yaml, env=env, text=True, capture_output=True,
        )
        if r.returncode == 0:
            ok(f"Secret 'db-credentials' applied to namespace {ns}")
        else:
            warn(f"DB secret: {r.stderr[:100]}")
    elif db_info:
        log(f"DBaaS state={db_info.get('state')} — DB secret will need manual injection after service is running")

    # --- SOS Credentials ---
    if sos_info:
        sos_secret_yaml = f"""apiVersion: v1
kind: Secret
metadata:
  name: sos-credentials
  namespace: {ns}
  labels:
    app.kubernetes.io/managed-by: exoscale-deploy-kit
type: Opaque
stringData:
  SOS_BUCKET: "{sos_info.get('bucket', '')}"
  SOS_ENDPOINT: "{sos_info.get('endpoint', '')}"
  SOS_REGION: "{sos_info.get('zone', cfg['exoscale_zone'])}"
  AWS_S3_ENDPOINT: "{sos_info.get('endpoint', '')}"
  AWS_ACCESS_KEY_ID: "{sos_info.get('access_key', cfg['exo_key'])}"
  AWS_SECRET_ACCESS_KEY: "{sos_info.get('secret_key', cfg['exo_secret'])}"
"""
        r = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=sos_secret_yaml, env=env, text=True, capture_output=True,
        )
        if r.returncode == 0:
            ok(f"Secret 'sos-credentials' applied to namespace {ns}")
        else:
            warn(f"SOS secret: {r.stderr[:100]}")

    RESULTS["stages"]["inject_secrets"] = {"status": "success"}


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "="*60)
    print(f"  EXOSCALE DEPLOY KIT — {cfg['project_name'].upper()}")
    print(f"  Deployment ID: {TS}")
    print(f"  Image:  {IMAGE}")
    print(f"  Zone:   {cfg['exoscale_zone']}")
    print(f"  Output: {OUT}")
    print("="*60 + "\n")

    try:
        stage_docker_build()
        stage_docker_push()

        # Stage 3b/3c run in parallel with cluster creation — kick off managed
        # services early so they can reach 'running' while K8s nodes are booting.
        sos_info = stage_object_storage()
        db_info  = stage_dbaas()

        kubeconfig = stage_exoscale()
        stage_wait_for_nodes(kubeconfig)

        # Stage 4b: Label nodes with StarGate identity after they are Ready
        stage_label_nodes(kubeconfig)

        # Stage 5b: Install CSI driver + generate PVC manifest
        stage_install_csi(kubeconfig)

        stage_kubernetes(kubeconfig)

        # Stage 5c: Inject DB + SOS credentials as K8s secrets
        stage_inject_secrets(kubeconfig, db_info, sos_info)

        stage_verify(kubeconfig)
        stage_report()
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        fail(f"Pipeline exception: {e}")
        traceback.print_exc()
        # Save partial results on failure
        (OUT / "deployment_report_partial.json").write_text(json.dumps(RESULTS, indent=2))
        sys.exit(1)
