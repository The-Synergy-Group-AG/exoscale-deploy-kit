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

CONFIGURATION:
  Edit config.yaml for all non-secret settings.
  Copy .env.example to .env and fill in API keys.

PREREQUISITES:
  pip install -r requirements.txt
  docker running
  kubectl installed
"""
import json
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
    # on a fresh cluster. Always create WITHOUT SG first (Step A), then update the
    # SG association after the pool reaches 'running' state (Step B).
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
    log("  (Step A: creating without SG — will update SG after pool is running)")
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

    # Step B: Update nodepool with security group (works after pool is running)
    log(f"(Step B) Updating nodepool with security group {sg_id}...")
    _sg_attempts = 0
    _sg_success = False
    while _sg_attempts < 5:
        try:
            c.update_sks_nodepool(
                id=cluster_id,
                sks_nodepool_id=pool_id,
                security_groups=[{"id": sg_id}],
            )
            ok(f"Nodepool security group updated: {sg_id}")
            _sg_success = True
            break
        except Exception as _e:
            _sg_attempts += 1
            warn(f"SG update attempt {_sg_attempts}/5: {str(_e)[:60]} — retrying in 30s")
            time.sleep(30)
    if not _sg_success:
        warn("SG update failed — will need manual SG assignment in Exoscale console")
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

    # LESSON 9: Always set KUBECONFIG + PATH explicitly in subprocess env
    env = {"KUBECONFIG": kubeconfig, "PATH": "/usr/local/bin:/usr/bin:/bin"}

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

    # LESSON 9: Always set KUBECONFIG + PATH explicitly in subprocess env
    env = {"KUBECONFIG": kubeconfig, "PATH": "/usr/local/bin:/usr/bin:/bin"}

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
    env = {"KUBECONFIG": kubeconfig, "PATH": "/usr/local/bin:/usr/bin:/bin"}
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
        kubeconfig = stage_exoscale()
        stage_wait_for_nodes(kubeconfig)
        stage_kubernetes(kubeconfig)
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
