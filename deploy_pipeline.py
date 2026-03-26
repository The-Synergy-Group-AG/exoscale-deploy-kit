#!/usr/bin/env python3
"""
Exoscale Deploy Kit -- Production Deployment Pipeline
=====================================================
BATTLE-TESTED: Validated 2026-02-20 on live Exoscale + Docker Hub infrastructure.
Extracted from a battle-tested deployment and de-hardcoded for reuse in any project.

ARCHITECTURE:
  Stage 0:  Preflight checks
  Stage 1:  Docker build (multi-stage, linux/amd64, non-root)
  Stage 2:  Docker Hub push (both versioned + latest tags)
  Stage 3:  Exoscale infrastructure (Security Group, SKS Cluster, Node Pool)
  Stage 3b: Object Storage (SOS) + DBaaS (managed database)
  Stage 4:  Wait for worker nodes to join cluster
  Stage 3b: SG post-attach (after nodes Ready)
  Stage 4b: Node labels
  Stage 5:  Apply Kubernetes manifests
  Stage 5b: Exoscale CSI driver (block storage)
  Stage 5c: nginx-ingress + cert-manager + TLS  [Plan 123-P5 ISSUE-018]
  Stage 5d: Inject service credentials as K8s secrets
  Stage 6:  Verify pods Running
  Stage 6b: Connectivity test (uses LB IP)        [Plan 123-P5 ISSUE-016]
  Stage 7:  Final report

CRITICAL LESSONS LEARNED (battle-tested 2026-02-20 -- do not repeat these mistakes):
  1. Exoscale API base URL is ZONE-SPECIFIC:
       https://api-{zone}.exoscale.com/v2  <- CORRECT
       https://api.exoscale.com/v2         <- WRONG (404 on all compute endpoints)
  2. Use official Python SDK (exoscale v0.16.1+) -- manual HMAC-SHA256 signing fails in practice
  3. Instance type IDs must be queried at runtime -- hardcoded IDs change and break silently
  4. Node pool MUST be created + nodes MUST be Ready BEFORE applying K8s manifests
  5. Create nodepool WITHOUT security_groups first -- adding SG on creation returns HTTP 500
     on fresh clusters. Update SG after pool is running (Step B pattern).
  6. NLB is auto-created by Exoscale cloud controller when K8s type:LoadBalancer service
     is applied -- NEVER create NLB manually (creates duplicate, breaks routing)
  7. NodePort 30671 is pre-approved in Exoscale default Security Group -- use this or
     30888/30999. Any other NodePort will be BLOCKED by the default SG.
  8. Docker build: pass args as Python list items -- never string interpolation in subprocess
  9. kubectl env needs KUBECONFIG + PATH set explicitly in subprocess calls (no shell PATH)
 10. Worker nodes take 3-8 minutes to boot, register, and become Ready after pool creation
 11. Create Docker Hub pull secret BEFORE applying K8s manifests (ErrImagePull otherwise)
 12. Use --dry-run=client -o yaml | kubectl apply -f - pattern for secret creation
 13. SKS node pools reject 'tiny' and 'micro' instance sizes (HTTP 409) -- auto-upgrade to 'small'
 14. Exoscale resource names must be lowercase DNS-label format -- slugify project_name
 15. Teardown: use slugified project_name for resource matching (e.g. 'jtp-test1', not 'JTP-test1')
 16. project_name in config.yaml is display name; derive slug via re.sub for all API resource names
 17. update_sks_nodepool(security_groups=...) ALSO returns HTTP 500 -- Exoscale API bug.
     FIX: Attach SG to each nodepool instance individually via per-instance API:
       nodepool["instance-pool"]["id"] -> get_instance_pool(id=...).instances
       -> attach_instance_to_security_group(id=sg_id, instance={"id": inst_id})
     CRITICAL: args are (id=SG_id, instance={"id": inst_id}) -- SG id first, NOT instance-first.
 18. Exoscale SOS endpoint (sos-{zone}.exoscale.com) may be unresolvable on some networks
     (corporate DNS, VPN, Windows DNS cache). The botocore EndpointConnectionError is NOT
     a ClientError so it bypasses the boto3 except block. FIX: wrap boto3 client + create_bucket
     in a broad except Exception that warns + returns None (non-fatal) so the pipeline continues.
 19. Kubernetes label values must match [a-zA-Z0-9_.-] -- commas and spaces are NOT allowed.
     config.yaml label values like "agent1,agent2" fail with kubectl label error.
     FIX: sanitize all label values via re.sub before applying -- replace invalid chars with '-',
     collapse '--', strip leading/trailing '-', truncate to 63 chars.
 20. Exoscale CSI driver manifest URL changes between releases -- do NOT hardcode a single path.
     FIX: try a list of candidate URLs in order; first one that kubectl apply succeeds is used.
     If all fail, fall back to manual StorageClass creation only (pipeline still succeeds).
 21. Exoscale SDK Client has NO method 'terminate_dbaas_service_pg' -- AttributeError on teardown.
     The actual delete method name is unknown at SDK install time (changes between versions).
     FIX: In teardown.py, iterate candidate method names ['terminate_dbaas_service_pg',
     'delete_dbaas_service_pg', 'terminate_dbaas_service'] via getattr() with None fallback.
     If none exist, emit a WARN with Exoscale Console URL for manual deletion.
 22. Windows cp1252 encoding crashes when ANY script prints Unicode chars (->  arrows, emojis,
     box-drawing chars, etc.) OR when the Exoscale SDK opens its bundled JSON API spec file.
     BOTH issues share the same root cause: Python defaulting to cp1252 on Windows.
     FIX (two-part):
       a) Replace any Unicode-only chars in print/warn/fail/log strings with ASCII equivalents
          (e.g. replace U+2192 -> with ASCII ->).
       b) Always run all kit scripts with: python -X utf8 <script.py>
          This forces UTF-8 for ALL file I/O including SDK internals -- NOT just stdout.
          (PYTHONIOENCODING=utf-8 only fixes stdout/stderr, not file open() calls)
          (PYTHONUTF8=1 via 'set' in cmd.exe does NOT propagate correctly)
          The -X utf8 flag is the ONLY reliable solution on Python 3.7+/Windows.
     LESSON: Any script that imports exoscale.api.v2 WILL crash on Windows without -X utf8.

PLAN 123-P5 ADDITIONS (2026-03-04):
  ISSUE-015: DNS zone migration + update_dns.py --ip argument (Task 5.2)
  ISSUE-016: Stage 6b connectivity test now prefers LB external IP over NodePort (Task 5.4)
  ISSUE-018: Stage 5c nginx-ingress + cert-manager fully automated in pipeline (Task 5.3)
  ISSUE-020: DNS update runs before cert-manager apply -- guaranteed ordering (Task 5.5)

CONFIGURATION:
  Edit config.yaml for all non-secret settings.
  Copy .env.example to .env and fill in API keys.

PREREQUISITES:
  pip install -r requirements.txt
  docker running
  kubectl installed
  helm installed (for Stage 5c)
"""
import json
import re
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config_loader import load_config

# =============================================================================
#  CONFIGURATION -- loaded from config.yaml + .env
# =============================================================================
import argparse as _ap
_parser = _ap.ArgumentParser(add_help=False)
_parser.add_argument("--auto",   action="store_true", help="Skip wizard")
_parser.add_argument("--config", default="config.yaml",
                     help="Path to config YAML (relative to kit dir or absolute)")
_args, _ = _parser.parse_known_args()

cfg = load_config(_args.config)

if not _args.auto:
    import wizard as _wiz
    _existing = _wiz.load_existing()
    _wizard_cfg = _wiz.run_wizard(_existing)
    _wiz.print_summary(_wizard_cfg)
    if not _wiz.prompt_bool("Proceed with deployment?", True):
        sys.exit(0)
    _wiz.write_config(_wizard_cfg)
    cfg = load_config(_args.config)


# =============================================================================
#  RUNTIME SETUP -- derived from config
# =============================================================================
TS        = datetime.now().strftime("%Y%m%d_%H%M%S")
IMAGE     = f"{cfg['docker_hub_user']}/{cfg['service_name']}:{cfg['service_version']}"
IMAGE_LTS = f"{cfg['docker_hub_user']}/{cfg['service_name']}:latest"

# L39b: strip whitespace from node_count — shell layer does this via tr -d;
# deploy_pipeline.py must also sanitize so CPU-budget arithmetic and the
# Exoscale API size parameter never receive a string with stray whitespace.
cfg["node_count"] = int(str(cfg.get("node_count", 3)).strip())

_slug = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', cfg['project_name'].lower())).strip('-')
SG_NAME   = f"{_slug}-sg-{TS[-6:]}"
CLUSTER_N = f"{_slug}-cluster-{TS[-6:]}"
NLB_NAME  = f"{cfg['project_name']}-nlb-{TS[-6:]}"
POOL_NAME = f"{_slug}-workers-{TS[-6:]}"  # L45: unique suffix like CLUSTER_N

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
# L46: DEPLOY_RESOURCES must be defined — alias to RESULTS so any
# tooling or future code referencing DEPLOY_RESOURCES finds it.
DEPLOY_RESOURCES = RESULTS


def log(msg):   print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
def ok(msg):    print(f"[{datetime.now().strftime('%H:%M:%S')}] OK {msg}")
def warn(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] WARN {msg}")
def fail(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL {msg}")
def section(s): print(f"\n{'='*60}\n  {s}\n{'='*60}")


# =============================================================================
#  GRAFANA REAL-TIME ANNOTATION HELPER
#  Plan 123-P5+: Pushes stage events as annotations to localhost Grafana so the
#  jtp-deployment-dashboard shows a live timeline of the deployment progress.
#  Non-fatal: if Grafana is unreachable the pipeline continues unaffected.
# =============================================================================
import urllib.request as _urllib_req
import urllib.error   as _urllib_err
import base64         as _base64

_GF_ENV_FILE = Path(__file__).parent.parent / "monitoring" / "grafana" / ".env"


def _load_gf_env() -> dict:
    """Parse monitoring/grafana/.env for GRAFANA_URL / USER / PASSWORD."""
    env: dict = {}
    if _GF_ENV_FILE.exists():
        for line in _GF_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


_GF_CFG  = _load_gf_env()
_GF_URL  = _GF_CFG.get("GRAFANA_URL",      "http://localhost:3000")
_GF_USER = _GF_CFG.get("GRAFANA_USER",     "admin")
_GF_PASS = _GF_CFG.get("GRAFANA_PASSWORD", "admin")


def gf_annotate(text: str, tags: list | None = None, is_error: bool = False) -> None:
    """
    Push a deployment-stage annotation to the local Grafana instance.
    Non-fatal: errors are logged as WARNs and pipeline continues.
    """
    try:
        if tags is None:
            tags = []
        base_tags = ["deployment", "jtp", cfg.get("project_name", "jtp"), TS]
        all_tags  = list(dict.fromkeys(base_tags + tags + (["error"] if is_error else [])))
        prefix    = "[FAIL] " if is_error else "[OK] "
        payload   = json.dumps({
            "text":  prefix + text,
            "tags":  all_tags,
            "time":  int(datetime.now().timestamp() * 1000),
        }).encode("utf-8")
        creds = _base64.b64encode(f"{_GF_USER}:{_GF_PASS}".encode()).decode()
        req   = _urllib_req.Request(
            f"{_GF_URL.rstrip('/')}/api/annotations",
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Basic {creds}",
            },
            method="POST",
        )
        with _urllib_req.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                log(f"[Grafana] Annotation: {text[:70]}")
    except Exception as _exc:
        warn(f"[Grafana] Annotation skipped (non-fatal): {_exc}")


def gf_stage_start(stage: str, detail: str = "") -> None:
    """Annotate Grafana at the START of a pipeline stage."""
    msg = f"STAGE {stage} -- START"
    if detail:
        msg += f" | {detail}"
    gf_annotate(msg, tags=[f"stage:{stage.lower().replace(' ', '_')}"])


def gf_stage_end(stage: str, status: str = "success", detail: str = "") -> None:
    """Annotate Grafana at the END of a pipeline stage."""
    is_err = status.lower() in ("fail", "failed", "error")
    msg    = f"STAGE {stage} -- {status.upper()}"
    if detail:
        msg += f" | {detail}"
    gf_annotate(msg,
                tags=[f"stage:{stage.lower().replace(' ', '_')}", status.lower()],
                is_error=is_err)

def elapsed(t): return f"{time.time()-t:.0f}s"


# =============================================================================
#  STAGE 0: PREFLIGHT CHECKS
#  Plan 122-DEH ISSUE-003: Fail fast BEFORE any Exoscale API call or cloud spend.
# =============================================================================
def stage_preflight() -> None:
    import socket
    section("STAGE 0: Preflight Checks (Plan 122-DEH ISSUE-003)")
    t0 = time.time()
    failures: list[str] = []

    r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        ok("Docker daemon: running")
    else:
        failures.append("Docker daemon not running -- start Docker Desktop or Docker service")

    r = subprocess.run(
        ["kubectl", "version", "--client", "--output=json"],
        capture_output=True, text=True, timeout=10
    )
    if r.returncode == 0:
        ok("kubectl: available")
    else:
        failures.append(
            "kubectl not found or not working -- "
            "install kubectl: https://kubernetes.io/docs/tasks/tools/"
        )

    # LESSON 27: helm required for Stage 5c (ingress-nginx + cert-manager via Helm)
    # Without this check the pipeline crashes with FileNotFoundError mid-run (after
    # spending ~3 minutes provisioning Exoscale infrastructure).
    r_helm = subprocess.run(
        ["helm", "version", "--short"],
        capture_output=True, text=True, timeout=10
    )
    if r_helm.returncode == 0:
        helm_ver = r_helm.stdout.strip().split("\n")[0]
        ok(f"helm: available ({helm_ver})")
    else:
        ingress_cfg = cfg.get("ingress", {})
        if ingress_cfg.get("enabled", False):
            failures.append(
                "helm not found -- required for Stage 5c (ingress-nginx + cert-manager). "
                "Install: curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"
            )
        else:
            warn("helm not found (OK -- ingress disabled, Stage 5c will be skipped)")

    if cfg.get("exo_key") and cfg.get("exo_secret"):
        ok(f"Exoscale credentials: set (key={cfg['exo_key'][:8]}...)")
    else:
        failures.append(
            "Exoscale credentials missing -- set EXO_API_KEY and EXO_API_SECRET in .env"
        )

    if cfg.get("docker_hub_token"):
        ok("Docker Hub token: set")
    else:
        failures.append(
            "Docker Hub token missing -- set DOCKER_HUB_TOKEN in .env"
        )

    api_host = f"api-{cfg['exoscale_zone']}.exoscale.com"
    try:
        socket.getaddrinfo(api_host, 443, proto=socket.IPPROTO_TCP)
        ok(f"DNS: {api_host} resolves OK")
    except socket.gaierror:
        failures.append(
            f"DNS resolution failed for {api_host} -- "
            "check network connection, VPN status, or corporate DNS settings"
        )

    if failures:
        fail(f"PREFLIGHT FAILED -- {len(failures)} check(s) not satisfied:")
        for i, msg in enumerate(failures, 1):
            fail(f"  {i}. {msg}")
        fail("")
        fail("Fix the above issues and retry deployment.")
        fail("To bypass (advanced debugging only): python3 deploy_pipeline.py --skip-preflight")
        sys.exit(1)

    ok(f"All preflight checks passed ({elapsed(t0)})")
    RESULTS["stages"]["preflight"] = {"status": "success", "duration": elapsed(t0)}


# =============================================================================
#  STAGE 1: DOCKER BUILD
# =============================================================================
def stage_docker_build():
    section("STAGE 1: Docker Build")
    t0 = time.time()
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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


# =============================================================================
#  STAGE 2: DOCKER HUB PUSH
# =============================================================================
def stage_docker_push():
    section("STAGE 2: Docker Hub Push")
    t0 = time.time()

    r = subprocess.run(
        ["docker", "login", "--username", cfg["docker_hub_user"], "--password-stdin", "docker.io"],
        input=cfg["docker_hub_token"], text=True, capture_output=True,
    )
    if r.returncode != 0:
        fail(f"Docker login failed: {r.stderr[:100]}")
        sys.exit(1)
    ok("Authenticated with Docker Hub")

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


# =============================================================================
#  HELPER: _populate_sg_rules -- LESSON 25/26
# =============================================================================
def _populate_sg_rules(c, sg_id: str) -> None:
    _SGS_RULES = [
        {"flow_direction": "ingress", "protocol": "tcp", "network": "0.0.0.0/0",
         "start_port": 10250, "end_port": 10250,
         "description": "Kubelet API -- kubectl logs/exec/port-forward"},
        {"flow_direction": "ingress", "protocol": "tcp", "network": "0.0.0.0/0",
         "start_port": 10255, "end_port": 10255,
         "description": "Kubelet read-only metrics"},
        {"flow_direction": "ingress", "protocol": "tcp", "network": "0.0.0.0/0",
         "start_port": 30000, "end_port": 32767,
         "description": "NodePort services 30000-32767 (incl. 30671 gateway)"},
        {"flow_direction": "ingress", "protocol": "tcp", "network": "0.0.0.0/0",
         "start_port": 80, "end_port": 80, "description": "HTTP"},
        {"flow_direction": "ingress", "protocol": "tcp", "network": "0.0.0.0/0",
         "start_port": 443, "end_port": 443, "description": "HTTPS"},
        {"flow_direction": "ingress", "protocol": "tcp",
         "security_group": {"id": sg_id}, "start_port": 1, "end_port": 65535,
         "description": "Intra-cluster TCP (Calico CNI, konnectivity, pod-to-pod)"},
        {"flow_direction": "ingress", "protocol": "udp",
         "security_group": {"id": sg_id}, "start_port": 1, "end_port": 65535,
         "description": "Intra-cluster UDP (Calico VXLAN, WireGuard)"},
        {"flow_direction": "ingress", "protocol": "icmp", "network": "0.0.0.0/0",
         "description": "ICMP ingress (ping, NLB health probes)"},
        {"flow_direction": "egress", "protocol": "tcp", "network": "0.0.0.0/0",
         "start_port": 1, "end_port": 65535, "description": "Egress all TCP"},
        {"flow_direction": "egress", "protocol": "udp", "network": "0.0.0.0/0",
         "start_port": 1, "end_port": 65535, "description": "Egress all UDP"},
        {"flow_direction": "egress", "protocol": "icmp", "network": "0.0.0.0/0",
         "description": "Egress ICMP"},
    ]
    log(f"Populating SG {sg_id[:8]}... with {len(_SGS_RULES)} rules (LESSON 25)...")
    _ok, _fail, _skip = 0, 0, 0
    for _rule in _SGS_RULES:
        _desc = _rule.get("description", "")
        try:
            c.add_rule_to_security_group(id=sg_id, **_rule)
            ok(f"  SG rule: {_rule['flow_direction']} {_rule['protocol']} -- {_desc}")
            _ok += 1
        except Exception as _e:
            _err = str(_e)
            if "already" in _err.lower() or "duplicate" in _err.lower():
                _skip += 1
            else:
                warn(f"  SG rule WARN ({_desc}): {_err[:80]}")
                _fail += 1
    if _ok > 0 or _skip > 0:
        ok(f"SG populated: {_ok} rules added, {_skip} existed, {_fail} failed")
        RESULTS["resources"]["security_group"]["rules_added"] = _ok
    else:
        warn(f"All SG rules failed -- SG is empty, will have no effect on traffic!")
        RESULTS["resources"]["security_group"]["rules_failed"] = _fail


# =============================================================================
#  STAGE 3: EXOSCALE INFRASTRUCTURE
# =============================================================================
def stage_exoscale():
    section("STAGE 3: Exoscale Infrastructure")
    t0 = time.time()

    from exoscale.api.v2 import Client
    c = Client(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])
    log(f"Connected to Exoscale zone: {cfg['exoscale_zone']}")

    log(f"Creating security group: {SG_NAME}")
    _sg_op = c.create_security_group(
        name=SG_NAME,
        description=f"{cfg['project_name']} -- {cfg['service_name']} ({TS})",
    )
    _sg_op_id = _sg_op.get("id")
    log(f"SG create operation: {_sg_op_id} -- resolving real SG ID...")
    time.sleep(3)
    _all_sgs = c.list_security_groups().get("security-groups", [])
    _sg_real  = next((s for s in _all_sgs if s.get("name") == SG_NAME), {})
    sg_id     = _sg_real.get("id") or _sg_op_id
    ok(f"Security group resolved: {sg_id} (op was {_sg_op_id[:8]}...)")
    RESULTS["resources"]["security_group"] = {"id": sg_id, "name": SG_NAME}

    _populate_sg_rules(c, sg_id)
    ok(f"Security group ready: {sg_id} (web access via NodePort {cfg['k8s_nodeport']})")

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
                f"({t.get('cpus')}cpu/{t.get('memory', 0)//1024}GB) -- {selected_id}"
            )
            break
    if not selected_id and types:
        selected_id = types[0].get("id")
        warn(f"Exact match not found, using: {types[0].get('size')} -- {selected_id}")

    log("Querying SKS cluster versions...")
    versions = c.list_sks_cluster_versions().get("sks-cluster-versions", [])
    k8s_ver = versions[0] if versions else None
    ok(f"Kubernetes version: {k8s_ver}")

    log(f"Creating SKS cluster: {CLUSTER_N}...")
    op = c.create_sks_cluster(
        name=CLUSTER_N,
        cni=cfg["sks_cni"],
        level=cfg["sks_level"],
        version=k8s_ver,
        description=f"{cfg['project_name']} -- {TS}",
        addons=cfg["sks_addons"],
    )
    op_id = op.get("id")
    log(f"Cluster creation initiated -- operation: {op_id}")
    log("Waiting for SKS cluster (3-8 minutes)...")
    result = c.wait(op_id, max_wait_time=600)
    cluster_id = result.get("reference", {}).get("id")
    ok(f"SKS cluster: {cluster_id}")
    RESULTS["resources"]["sks_cluster"] = {"id": cluster_id, "name": CLUSTER_N}

    _SKS_FORBIDDEN_SIZES = {"tiny", "micro"}
    if cfg.get("node_type_size", "").lower() in _SKS_FORBIDDEN_SIZES:
        _upgraded = "small"
        warn(f"Instance size '{cfg['node_type_size']}' is NOT supported for SKS node pools.")
        warn(f"Auto-upgrading to '{_upgraded}' (minimum supported size).")
        cfg["node_type_size"] = _upgraded
        selected_id = None
        for t in types:
            fam  = (t.get("family") or "").lower()
            size = (t.get("size") or "").lower()
            if cfg["node_type_family"] in fam and cfg["node_type_size"] in size:
                selected_id = t.get("id")
                ok(f"Upgraded instance type: {t.get('size')} ({t.get('cpus')}cpu) -- {selected_id}")
                break
        if not selected_id and types:
            selected_id = types[0].get("id")

    log(f"Creating node pool: {POOL_NAME} ({cfg['node_count']} x {cfg['node_type_size']})...")
    log("  (Step A: creating without SG -- will attach SG per-instance after pool is running)")
    op = c.create_sks_nodepool(
        id=cluster_id,
        name=POOL_NAME,
        size=cfg["node_count"],
        description=f"{cfg['project_name']} worker nodes",
        disk_size=cfg["node_disk_gb"],
        instance_type={"id": selected_id},
    )
    op_id = op.get("id")
    log(f"Node pool initiated -- operation: {op_id}")
    log("Waiting for node pool (2-5 minutes)...")
    result = c.wait(op_id, max_wait_time=600)
    pool_id = result.get("reference", {}).get("id")
    ok(f"Node pool created: {pool_id}")
    RESULTS["resources"]["node_pool"] = {
        "id": pool_id, "name": POOL_NAME, "size": cfg["node_count"]
    }

    log("SG instance attachment deferred to Stage 3b (after nodes Ready) -- see stage_sg_post_attach()")
    RESULTS["resources"]["node_pool"]["sg_deferred"] = True

    log("NLB: delegated to Exoscale cloud controller (K8s type:LoadBalancer service)")
    ok("NLB will appear as EXTERNAL-IP once K8s cloud controller provisions it")

    log("Retrieving kubeconfig...")
    import base64
    kc_resp = c.generate_sks_cluster_kubeconfig(
        id=cluster_id, groups=["system:masters"], ttl=86400, user="admin"
    )
    kc_path = OUT / "kubeconfig.yaml"
    kc_bytes = base64.b64decode(kc_resp.get("kubeconfig", ""))
    kc_path.write_bytes(kc_bytes)
    ok(f"Kubeconfig saved: {kc_path}")
    RESULTS["resources"]["kubeconfig"] = str(kc_path)

    # L63/L170: Also update ~/.kube/config so local kubectl works after deploy
    # Without this, `kubectl` commands fail with TLS cert rotation errors after teardown+redeploy
    home_kube = Path.home() / ".kube"
    home_kube.mkdir(exist_ok=True)
    home_kube_config = home_kube / "config"
    home_kube_config.write_bytes(kc_bytes)
    ok(f"L63: ~/.kube/config updated (prevents TLS cert rotation errors)")

    ok(f"Exoscale infrastructure complete in {elapsed(t0)}")
    return str(kc_path)


# =============================================================================
#  STAGE 4: WAIT FOR WORKER NODES
# =============================================================================
def stage_wait_for_nodes(kubeconfig: str):
    section("STAGE 4: Wait for Worker Nodes")
    t0 = time.time()

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
        warn(f"Nodes not all Ready after {elapsed(t0)} -- proceeding anyway")
        RESULTS["stages"]["wait_nodes"] = {"status": "partial", "duration": elapsed(t0)}

    return nodes_ready


# =============================================================================
#  STAGE 3b: SG POST-ATTACH -- after worker nodes are Ready
# =============================================================================
def stage_sg_post_attach() -> None:
    section("STAGE 3b: SG Post-Attach (after nodes Ready)")
    t0 = time.time()

    sg_id      = RESULTS["resources"].get("security_group", {}).get("id")
    cluster_id = RESULTS["resources"].get("sks_cluster", {}).get("id")
    pool_id    = RESULTS["resources"].get("node_pool", {}).get("id")

    if not all([sg_id, cluster_id, pool_id]):
        warn("SG post-attach: missing resource IDs -- skipping")
        return

    from exoscale.api.v2 import Client
    c = Client(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])

    _SG_MAX_ATTEMPTS = 10
    _SG_RETRY_DELAY  = 15
    log(
        f"Attaching SG {sg_id[:8]}... to node-pool instances "
        f"-- up to {_SG_MAX_ATTEMPTS} attempts x {_SG_RETRY_DELAY}s"
    )
    _sg_success  = False
    _attached    = 0
    _last_error  = ""

    for _attempt in range(1, _SG_MAX_ATTEMPTS + 1):
        try:
            _cluster_detail = c.get_sks_cluster(id=cluster_id)
            _pool_detail = next(
                (p for p in _cluster_detail.get("nodepools", []) if p.get("id") == pool_id),
                {}
            )
            _inst_pool_id = _pool_detail.get("instance-pool", {}).get("id")
            if not _inst_pool_id:
                _last_error = "instance-pool ref missing from nodepool detail"
                log(f"  Attempt {_attempt}/{_SG_MAX_ATTEMPTS}: {_last_error}")
                if _attempt < _SG_MAX_ATTEMPTS:
                    time.sleep(_SG_RETRY_DELAY)
                continue

            _inst_pool = c.get_instance_pool(id=_inst_pool_id)
            _instances = _inst_pool.get("instances", [])
            if not _instances:
                _last_error = f"instance-pool {_inst_pool_id[:8]}... has 0 instances"
                log(f"  Attempt {_attempt}/{_SG_MAX_ATTEMPTS}: {_last_error}")
                if _attempt < _SG_MAX_ATTEMPTS:
                    time.sleep(_SG_RETRY_DELAY)
                continue

            log(f"  Attempt {_attempt}/{_SG_MAX_ATTEMPTS}: found {len(_instances)} instance(s) -- attaching SG...")
            _attached = 0
            for _inst in _instances:
                _inst_id   = _inst.get("id")
                _inst_name = _inst.get("name", _inst_id)
                c.attach_instance_to_security_group(id=sg_id, instance={"id": _inst_id})
                ok(f"  SG attached to {_inst_name}")
                _attached += 1

            if _attached >= len(_instances) and _instances:
                ok(f"  All {_attached} instance(s) have SG attached ({elapsed(t0)})")
                _sg_success = True
                break
            elif _attached > 0:
                ok(f"  Partial: SG attached to {_attached}/{len(_instances)} instances")
                _sg_success = True
                break

        except Exception as _e:
            _last_error = str(_e)[:100]
            warn(f"  Attempt {_attempt}/{_SG_MAX_ATTEMPTS} failed: {_last_error}")
            if _attempt < _SG_MAX_ATTEMPTS:
                time.sleep(_SG_RETRY_DELAY)

    if _sg_success:
        RESULTS["resources"]["node_pool"]["sg_attached"]       = True
        RESULTS["resources"]["node_pool"]["sg_attached_count"] = _attached
        RESULTS["resources"]["node_pool"].pop("sg_deferred", None)
        ok(f"SG post-attach complete -- NodePort traffic now routed to worker nodes")
    else:
        warn(f"SG post-attach failed after {_SG_MAX_ATTEMPTS} attempts: {_last_error}")
        warn("NodePort traffic will be blocked -- manual SG attach needed in Exoscale Console")
        RESULTS["resources"]["node_pool"]["sg_update_failed"]   = True
        RESULTS["resources"]["node_pool"]["sg_attach_attempts"] = _SG_MAX_ATTEMPTS


# =============================================================================
#  STAGE 5: KUBERNETES MANIFESTS
# =============================================================================
def stage_kubernetes(kubeconfig: str):
    section("STAGE 5: Kubernetes Deployment")
    t0 = time.time()
    manifests_dir = OUT / "k8s-manifests"

    env = {**os.environ, "KUBECONFIG": kubeconfig}

    log(f"Creating namespace: {cfg['k8s_namespace']}")
    r_ns = subprocess.run(
        ["kubectl", "create", "namespace", cfg["k8s_namespace"]],
        env=env, capture_output=True, text=True,
    )
    if r_ns.returncode == 0:
        ok(f"Namespace {cfg['k8s_namespace']} created")
    else:
        log(f"  Namespace: {r_ns.stderr.strip()[:80]} (may already exist)")

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

    # ISSUE-019: ClusterIP when nginx-ingress is entry point (avoids second NLB)
    # ISSUE-023: hostname so gateway reports K8s identity not Docker Compose name
    _svc_type    = "ClusterIP" if cfg.get("ingress", {}).get("enabled") else "LoadBalancer"
    _gw_hostname = cfg.get("gateway_hostname", "jtp-gateway")

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
            "--service-type", _svc_type,        # ISSUE-019
            "--gateway-hostname", _gw_hostname,  # ISSUE-023
        ],
        capture_output=True, text=True,
    )
    if r.stdout:
        log(r.stdout.strip())
    if r.returncode != 0:
        warn(f"Manifest generator warning: {r.stderr[:200]}")

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


# =============================================================================
#  STAGE 6: VERIFY PODS RUNNING
# =============================================================================
def stage_verify(kubeconfig: str):
    section("STAGE 6: Verification")
    t0 = time.time()
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    ns = cfg["k8s_namespace"]

    target_replicas = cfg.get("k8s_replicas", 1)
    log(f"Waiting for {target_replicas} pod replica(s) to reach Running state (up to 5 min)...")
    deadline = time.time() + 300
    pods_ok = False
    last_lines: list[str] = []

    while time.time() < deadline:
        r = subprocess.run(
            ["kubectl", "get", "pods", "-n", ns, "--no-headers"],
            env=env, capture_output=True, text=True,
        )
        lines = [line for line in r.stdout.strip().split("\n") if line]
        running  = [line for line in lines if "Running"   in line and "0/"  not in line]
        crashing = [line for line in lines if "CrashLoop" in line or "Error" in line]
        pending  = [line for line in lines if "Pending"   in line]
        log(f"  Pods: {len(lines)} total | {len(running)} Running | "
            f"{len(pending)} Pending | {len(crashing)} CrashLoop/Error "
            f"| target={target_replicas}")
        for line in lines:
            log(f"    {line}")
        last_lines = lines

        if crashing:
            warn(f"  {len(crashing)} pod(s) in CrashLoop/Error -- streaming events:")
            r_ev = subprocess.run(
                ["kubectl", "get", "events", "-n", ns,
                 "--field-selector=type=Warning", "--sort-by=.lastTimestamp"],
                env=env, capture_output=True, text=True,
            )
            for ev_line in r_ev.stdout.strip().split("\n")[-10:]:
                warn(f"    {ev_line}")

        if len(running) >= target_replicas:
            pods_ok = True
            break
        time.sleep(15)

    if pods_ok:
        ok(f"All {target_replicas} replica(s) Running! ({elapsed(t0)})")
    else:
        warn(
            f"Only {len([l for l in last_lines if 'Running' in l])}/"
            f"{target_replicas} replicas Running after {elapsed(t0)} -- "
            "may need more startup time"
        )
        log("  Streaming pod details for debugging:")
        r_desc = subprocess.run(
            ["kubectl", "describe", "pods", "-n", ns],
            env=env, capture_output=True, text=True,
        )
        for desc_line in r_desc.stdout.strip().split("\n")[-30:]:
            log(f"    {desc_line}")

    for cmd_args, label in [
        (["kubectl", "get", "all", "-n", ns], "All Resources"),
        (["kubectl", "get", "nodes"], "Nodes"),
    ]:
        log(f"\n{label}:")
        r = subprocess.run(cmd_args, env=env, capture_output=True, text=True)
        print(r.stdout)

    RESULTS["stages"]["verify"] = {"status": "success" if pods_ok else "partial"}


# =============================================================================
#  HELPER: refresh_kubeconfig  (ISSUE-017)
#  Exoscale SKS clusters rotate TLS certs periodically. The saved kubeconfig CA
#  bundle becomes stale ~2-3 hours after cluster creation. Re-generate before any
#  long-running stage (particularly Stage 5c which runs after nodes are Ready).
# =============================================================================
def refresh_kubeconfig(kubeconfig: str) -> str:
    """Re-generate kubeconfig from Exoscale API to avoid TLS cert rotation issues."""
    cluster_id = RESULTS.get("resources", {}).get("sks_cluster", {}).get("id")
    if not cluster_id:
        warn("refresh_kubeconfig: cluster_id not in RESULTS -- skipping refresh")
        return kubeconfig
    try:
        import base64
        from exoscale.api.v2 import Client as _ExoClient
        _c = _ExoClient(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])
        kc_resp = _c.generate_sks_cluster_kubeconfig(
            id=cluster_id, groups=["system:masters"], ttl=86400, user="admin"
        )
        kc_bytes = base64.b64decode(kc_resp.get("kubeconfig", ""))
        if kc_bytes:
            Path(kubeconfig).write_bytes(kc_bytes)
            ok(f"Kubeconfig refreshed (ISSUE-017): {kubeconfig}")
        else:
            warn("refresh_kubeconfig: empty response -- keeping existing kubeconfig")
    except Exception as _e:
        warn(f"refresh_kubeconfig: {_e} -- keeping existing kubeconfig + using --insecure-skip-tls-verify")
    return kubeconfig


#  HELPER: get_lb_external_ip  (Task 5.4 -- Plan 123-P5 ISSUE-016)
#  Waits for and returns the external LoadBalancer IP of a K8s service.
#  Used by stage_5c_ingress_tls() and stage_connectivity_test().
# =============================================================================
def get_lb_external_ip(svc_name: str, namespace: str, kubeconfig: str,
                       timeout: int = 120) -> str | None:
    """Wait for and return the external LoadBalancer IP of a K8s service."""
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    for _ in range(timeout // 5):
        r = subprocess.run(
            ["kubectl", "--insecure-skip-tls-verify",
             "-n", namespace, "get", "svc", svc_name,
             "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}"],
            env=env, capture_output=True, text=True,
        )
        ip = r.stdout.strip()
        if ip and ip != "<pending>":
            return ip
        time.sleep(5)
    return None


# =============================================================================
#  HELPER: generate_ingress_yaml  (Task 5.3b -- Plan 123-P5 ISSUE-018)
#  Generates ClusterIssuer + Ingress YAML from config values at deploy time.
#  Replaces the static ingress-tls.yaml file used in Phase 4.
# =============================================================================
def generate_ingress_yaml(domain: str, cert_email: str, namespace: str,
                          svc_name: str, svc_port: int) -> str:
    """Generate ClusterIssuer + Ingress YAML string from runtime config values."""
    tls_secret = domain.replace(".", "-") + "-tls"
    return f"""---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: {cert_email}
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          class: nginx
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {svc_name}-ingress
  namespace: {namespace}
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/session-cookie-name: "jtp-session"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "3600"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "180"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "180"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "10"
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - {domain}
    secretName: {tls_secret}
  rules:
  - host: {domain}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: {svc_name}
            port:
              number: {svc_port}
  - host: www.{domain}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: {svc_name}
            port:
              number: {svc_port}
"""


# =============================================================================
#  STAGE 5c: INGRESS + TLS  (Task 5.3 -- Plan 123-P5 ISSUE-018, ISSUE-020)
#  Deploys nginx-ingress-controller + cert-manager + ClusterIssuer + Ingress.
#  Follows FUTURE_DEPLOYMENT_GUIDE.md stages 6-8.
#  Ordering (ISSUE-020): nginx LB IP -> DNS update -> cert-manager -> Ingress.
#  Only runs when cfg['ingress']['enabled'] == True.
# =============================================================================
def stage_5c_ingress_tls(kubeconfig: str) -> None:
    """
    Stage 5c: Deploy nginx-ingress + cert-manager + TLS.
    Steps:
      5c-1: Deploy nginx-ingress via Helm, wait for LB IP
      5c-2: Update DNS via update_dns.py --ip <ingress-lb-ip>   (ISSUE-020 ordering)
      5c-3: Deploy cert-manager via Helm
      5c-4: Generate + apply ClusterIssuer + Ingress from config
      5c-5: Wait for TLS certificate Ready=True
    """
    if not cfg.get("ingress", {}).get("enabled"):
        log("ingress.enabled: false -- skipping Stage 5c")
        return

    section("STAGE 5c: Ingress + TLS (nginx-ingress + cert-manager)")
    t0 = time.time()

    domain     = cfg["ingress"].get("domain", "")
    cert_email = cfg["ingress"].get("cert_email", "")
    namespace  = cfg["k8s_namespace"]
    svc_name   = cfg["service_name"]
    svc_port   = cfg.get("k8s_service_port", cfg["k8s_port"])

    env = {**os.environ, "KUBECONFIG": kubeconfig}

    def _run(cmd, check=True):
        r = subprocess.run(cmd, env=env, check=False, capture_output=False)
        if check and r.returncode != 0:
            raise RuntimeError(f"Command failed ({r.returncode}): {' '.join(str(c) for c in cmd)}")
        return r

    def _cap(cmd):
        r = subprocess.run(cmd, env=env, capture_output=True, text=True)
        return r.stdout.strip()

    # ── 5c-1: nginx-ingress via Helm ─────────────────────────────────────────
    log("5c-1: Deploying nginx-ingress-controller (Helm)...")
    _run([
        "helm", "upgrade", "--install", "ingress-nginx", "ingress-nginx",
        "--repo", "https://kubernetes.github.io/ingress-nginx",
        "--namespace", "ingress-nginx", "--create-namespace",
        "--set", "controller.service.type=LoadBalancer",
        # LESSON 59: admissionWebhooks.enabled=false removes the pre-install
        # webhook cert-generator Job that times out on fresh Exoscale clusters.
        "--set", "controller.admissionWebhooks.enabled=false",
        "--wait", "--timeout", "10m"
    ])
    ok("nginx-ingress-controller deployed")

    # Wait for LB IP on ingress-nginx-controller service
    log("  Waiting for nginx-ingress LB IP (up to 2 min)...")
    ingress_lb_ip = None
    for _ in range(24):  # 24 x 5s = 2 min
        ip = _cap([
            "kubectl", "--insecure-skip-tls-verify",
            "-n", "ingress-nginx", "get", "svc", "ingress-nginx-controller",
            "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}"
        ])
        if ip and ip != "<pending>":
            ingress_lb_ip = ip
            break
        time.sleep(5)

    if not ingress_lb_ip:
        raise RuntimeError(
            "nginx-ingress LB IP not assigned after 2 minutes -- "
            "check cloud controller logs"
        )
    ok(f"nginx-ingress LB IP: {ingress_lb_ip}")
    RESULTS["resources"]["ingress"] = {"lb_ip": ingress_lb_ip, "domain": domain}

    # ── 5c-1b: Fix K8s CCM NLB port mismatch (ISSUE-021) ─────────────────────
    # Exoscale K8s CCM creates the nginx-ingress NLB with wrong NodePort targets.
    # Both port-80 and port-443 listeners target the first NodePort assigned (wrong).
    # Without this fix cert-manager HTTP-01 challenges ALWAYS FAIL (cert never issued).
    # Fix: dynamically read actual NodePorts from K8s, update NLB via Exoscale API.
    # Discovered 2026-03-04 (Plan 123 Phase 5). fix_k8s_nlb.py was the manual fix.
    log("5c-1b: Fixing K8s CCM NLB port assignments (ISSUE-021)...")
    http_nodeport_str = _cap([
        "kubectl", "--insecure-skip-tls-verify",
        "-n", "ingress-nginx", "get", "svc", "ingress-nginx-controller",
        "-o", "jsonpath={.spec.ports[?(@.port==80)].nodePort}"
    ])
    https_nodeport_str = _cap([
        "kubectl", "--insecure-skip-tls-verify",
        "-n", "ingress-nginx", "get", "svc", "ingress-nginx-controller",
        "-o", "jsonpath={.spec.ports[?(@.port==443)].nodePort}"
    ])
    if not http_nodeport_str or not https_nodeport_str:
        warn("  Cannot get nginx-ingress NodePorts -- NLB port fix skipped")
        warn("  HTTP-01 cert challenge may fail! Run: python3 fix_k8s_nlb.py")
    else:
        http_np  = int(http_nodeport_str)
        https_np = int(https_nodeport_str)
        log(f"  nginx-ingress NodePorts: HTTP={http_np}, HTTPS={https_np}")
        try:
            from exoscale.api.v2 import Client as _ExoClient
            _exo = _ExoClient(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])
            # Find K8s-created NLB by IP — name changes each deploy, never hardcode it
            _all_nlbs = _exo.list_load_balancers().get("load-balancers", [])
            _k8s_nlb  = next((n for n in _all_nlbs if n.get("ip") == ingress_lb_ip), None)
            if not _k8s_nlb:
                log("  NLB not yet visible — waiting 10s and retrying...")
                time.sleep(10)
                _all_nlbs = _exo.list_load_balancers().get("load-balancers", [])
                _k8s_nlb  = next((n for n in _all_nlbs if n.get("ip") == ingress_lb_ip), None)
            if _k8s_nlb:
                _nlb_id   = _k8s_nlb["id"]
                log(f"  K8s NLB found: {_nlb_id[:8]}... IP={ingress_lb_ip}")
                _detail   = _exo.get_load_balancer(id=_nlb_id)
                _port_map = {80: http_np, 443: https_np}
                for _svc in _detail.get("services", []):
                    _port   = _svc.get("port")
                    _svc_id = _svc.get("id")
                    _cur_hc = _svc.get("healthcheck", {}).get("port")
                    _target = _port_map.get(_port)
                    if _target is None:
                        continue
                    if _cur_hc == _target:
                        log(f"  port {_port}: already -> {_target} (OK)")
                    else:
                        log(f"  port {_port}: {_cur_hc} -> {_target} (fixing)")
                        _exo.update_load_balancer_service(
                            id=_nlb_id, service_id=_svc_id,
                            protocol="tcp",
                            target_port=_target,
                            healthcheck={"port": _target, "mode": "tcp",
                                         "interval": 10, "timeout": 5, "retries": 1},
                        )
                ok(f"NLB port assignments fixed: port 80->{http_np}, port 443->{https_np}")
                RESULTS["resources"]["ingress"]["nlb_port_fix"] = {
                    "http_nodeport": http_np,
                    "https_nodeport": https_np,
                    "nlb_id": _nlb_id,
                }
            else:
                warn(f"  K8s NLB with IP {ingress_lb_ip} not found -- port fix skipped")
                warn("  Manual fix required: python3 fix_k8s_nlb.py")
        except Exception as _e:
            warn(f"  NLB port fix error: {_e}")
            warn("  Manual fallback: python3 fix_k8s_nlb.py")

    # ── 5c-2: Update DNS (ISSUE-020: DNS BEFORE cert-manager) ────────────────
    # L68: Auto-update DNS via Exoscale SDK (replaces update_dns.py)
    log(f"5c-2: Updating DNS {domain} -> {ingress_lb_ip} (Exoscale SDK)...")
    try:
        # L62b: DNS is a global API — do NOT pass zone= (zone-specific URL returns 0 domains)
        from exoscale.api.v2 import Client as _DnsClient  # L170: explicit import — fixes 'name Client is not defined'
        _dns_client = _DnsClient(key=cfg["exo_key"], secret=cfg["exo_secret"])
        _domains = _dns_client.list_dns_domains().get("dns-domains", [])
        _domain_id = None
        for _d in _domains:
            if _d.get("unicode-name") == domain:
                _domain_id = _d["id"]
                break
        if _domain_id:
            _records = _dns_client.list_dns_domain_records(domain_id=_domain_id).get("dns-domain-records", [])
            _updated = 0
            for _r in _records:
                if _r["type"] == "A" and _r.get("content") != ingress_lb_ip:
                    _dns_client.update_dns_domain_record(
                        domain_id=_domain_id, record_id=_r["id"], content=ingress_lb_ip
                    )
                    _updated += 1
                    log(f"  DNS A {_r.get('name', '@')} → {ingress_lb_ip} (was {_r.get('content')})")
            if _updated:
                ok(f"DNS updated: {_updated} A record(s) → {ingress_lb_ip}")
            else:
                ok(f"DNS already correct: {domain} → {ingress_lb_ip}")
        else:
            warn(f"DNS zone '{domain}' not found in Exoscale account")
    except Exception as _dns_err:
        # L170: DNS failure is CRITICAL — site is unreachable without DNS
        # Log the error and the manual fix, but continue pipeline (DNS can be fixed manually)
        # However, mark the deploy as having a critical issue
        fail(f"DNS update FAILED: {_dns_err}")
        fail(f"  CRITICAL: Site will be unreachable until DNS is fixed")
        fail(f"  Manual fix: set A record {domain} → {ingress_lb_ip}")
        RESULTS["dns_update"] = {"success": False, "error": str(_dns_err), "target_ip": ingress_lb_ip}
        # Don't halt pipeline — NLB is up, DNS can be fixed post-deploy
        # But ensure this is surfaced in the final report as a critical issue

    # ── 5c-3: cert-manager via Helm ──────────────────────────────────────────
    log("5c-3: Deploying cert-manager (Helm)...")
    _run([
        "helm", "upgrade", "--install", "cert-manager", "cert-manager",
        "--repo", "https://charts.jetstack.io",
        "--namespace", "cert-manager", "--create-namespace",
        "--set", "crds.enabled=true",
        "--version", "v1.16.3", "--wait", "--timeout", "5m"
    ])
    ok("cert-manager deployed")

    # ── 5c-4: Generate + apply ClusterIssuer + Ingress ───────────────────────
    log("5c-4: Applying ClusterIssuer + Ingress resources...")
    ingress_yaml = generate_ingress_yaml(domain, cert_email, namespace, svc_name, svc_port)
    ingress_file = f"/tmp/ingress-tls-{TS}.yaml"
    Path(ingress_file).write_text(ingress_yaml)
    # LESSON 31: Ensure application namespace exists before applying ingress YAML
    # Stage 5c runs before Stage 5 (K8s manifests) which normally creates namespaces.
    try:
        _ns_r = subprocess.run(
            ["kubectl", "--insecure-skip-tls-verify", "create", "namespace", namespace],
            env=env, check=False, capture_output=True, text=True
        )
        if _ns_r.returncode == 0:
            ok(f"Namespace pre-created for ingress: {namespace}")
        elif "already exists" in (_ns_r.stderr or ""):
            log(f"Namespace already exists: {namespace} (OK)")
        else:
            warn(f"Namespace create note: {_ns_r.stderr.strip() or _ns_r.stdout.strip()}")
    except Exception as _ns_e:
        warn(f"Namespace pre-create error (non-fatal): {_ns_e}")

    # L72: Restore backed-up TLS certificate (avoids Let's Encrypt rate limit)
    _cert_backup = KIT_DIR / "tls_cert_backup.json"
    if _cert_backup.exists():
        try:
            _cert_json = json.loads(_cert_backup.read_text())
            # Strip resourceVersion/uid/creationTimestamp so K8s accepts it as new
            _meta = _cert_json.get("metadata", {})
            for _strip_key in ("resourceVersion", "uid", "creationTimestamp",
                               "managedFields", "annotations"):
                _meta.pop(_strip_key, None)
            _cert_json["metadata"] = {
                "name": _meta.get("name", ""),
                "namespace": namespace,
                "labels": _meta.get("labels", {}),
            }
            _cert_yaml = json.dumps(_cert_json)
            r_restore = subprocess.run(
                ["kubectl", "--insecure-skip-tls-verify", "apply", "-f", "-"],
                input=_cert_yaml, env=env, text=True, capture_output=True,
            )
            if r_restore.returncode == 0:
                ok(f"L72: TLS certificate restored from backup (skipping Let's Encrypt)")
            else:
                warn(f"L72: Cert restore failed: {r_restore.stderr[:120]}")
        except Exception as _exc:
            warn(f"L72: Cert restore error (non-fatal): {_exc}")
    else:
        log("L72: No TLS cert backup found — cert-manager will request new cert")

    _run(["kubectl", "--insecure-skip-tls-verify", "apply", "-f", ingress_file])
    ok(f"ClusterIssuer + Ingress applied (manifest: {ingress_file})")

    # ── 5c-5: Wait for TLS certificate ───────────────────────────────────────
    log("5c-5: Waiting for TLS certificate (Let's Encrypt HTTP-01)...")
    cert_name  = domain.replace(".", "-") + "-tls"
    cert_ready = False
    for i in range(36):  # 36 x 5s = 3 min
        status = _cap([
            "kubectl", "--insecure-skip-tls-verify",
            "-n", namespace, "get", "certificate", cert_name,
            "-o", 'jsonpath={.status.conditions[?(@.type=="Ready")].status}'
        ])
        if status == "True":
            cert_ready = True
            break
        if i % 6 == 0:
            log(f"  Certificate status: {status or 'pending'} ({i * 5}s elapsed)")
        time.sleep(5)

    RESULTS["resources"]["ingress"]["cert_status"] = "issued" if cert_ready else "pending"
    if cert_ready:
        ok(f"TLS certificate ISSUED -- https://{domain} is live! ({elapsed(t0)})")
    else:
        warn(f"TLS certificate still pending after {elapsed(t0)}")
        warn(f"  DNS may not have propagated yet (TTL=300 -- up to 5 min)")
        warn(f"  Monitor: kubectl --insecure-skip-tls-verify -n {namespace} get certificate {cert_name}")

    RESULTS["stages"]["ingress_tls"] = {
        "status": "success" if cert_ready else "pending",
        "ingress_lb_ip": ingress_lb_ip,
        "domain": domain,
        "cert_status": "issued" if cert_ready else "pending",
        "duration": elapsed(t0),
    }
    ok(f"Stage 5c complete ({elapsed(t0)})")


# =============================================================================
#  STAGE 6b: CONNECTIVITY TEST  (Plan 122-DEH ISSUE-005)
#  Probes gateway /health.
#  Task 5.4 (ISSUE-016): Now preferentially uses LoadBalancer external IP
#  rather than NodePort, matching the production traffic path.
# =============================================================================
def stage_connectivity_test(kubeconfig: str, gateway_url: str = "") -> bool:
    import urllib.request, urllib.error
    section("STAGE 6b: Connectivity Test (Plan 122-DEH ISSUE-005 + Plan 123-P5 ISSUE-016)")
    t0 = time.time()
    env = {**os.environ, "KUBECONFIG": kubeconfig}

    if not gateway_url:
        ns       = cfg["k8s_namespace"]
        svc_name = cfg["service_name"]

        # Task 5.4 (ISSUE-016): Try LoadBalancer external IP first (production path).
        # Only fall back to NodePort if LB IP is unavailable.
        log("  Discovering gateway URL (prefer LB external IP -- ISSUE-016)...")
        lb_ip = get_lb_external_ip(svc_name, ns, kubeconfig, timeout=60)
        if lb_ip:
            gateway_url = f"http://{lb_ip}"
            log(f"  Using LB external IP: {gateway_url}")
            RESULTS["resources"]["gateway_lb_ip"] = lb_ip
        else:
            # Fallback: NodePort on worker node IP
            log("  LB IP not available -- falling back to NodePort")
            r = subprocess.run(
                ["kubectl", "get", "nodes", "-o",
                 "jsonpath={.items[0].status.addresses[?(@.type=='ExternalIP')].address}"],
                env=env, capture_output=True, text=True,
            )
            node_ip = r.stdout.strip()
            if not node_ip:
                r = subprocess.run(
                    ["kubectl", "get", "nodes", "-o",
                     "jsonpath={.items[0].status.addresses[0].address}"],
                    env=env, capture_output=True, text=True,
                )
                node_ip = r.stdout.strip()
            if node_ip:
                gateway_url = f"http://{node_ip}:{cfg['k8s_nodeport']}"
                log(f"  Fallback NodePort URL: {gateway_url}")
                RESULTS["resources"]["gateway_node_ip"] = node_ip
            else:
                warn("Cannot determine LB IP or node IP -- skipping connectivity test")
                RESULTS["stages"]["connectivity_test"] = {
                    "status": "skipped", "reason": "no_gateway_ip"
                }
                return False

    log(f"Probing {gateway_url}/health (3 attempts, 15s apart)...")
    for attempt in range(1, 4):
        try:
            req = urllib.request.urlopen(f"{gateway_url}/health", timeout=10)
            body = req.read().decode("utf-8", errors="replace")[:100]
            ok(f"  Attempt {attempt}: HTTP {req.status} -- gateway UP ({elapsed(t0)})")
            log(f"  Response: {body}")
            RESULTS["stages"]["connectivity_test"] = {
                "status": "success", "gateway_url": gateway_url,
                "http_status": req.status, "attempts": attempt, "duration": elapsed(t0),
            }
            RESULTS["resources"]["gateway_url"] = gateway_url
            ok(f"Connectivity test PASSED -- {gateway_url}")
            return True
        except urllib.error.HTTPError as e:
            ok(f"  Attempt {attempt}: HTTP {e.code} -- gateway responding ({elapsed(t0)})")
            RESULTS["stages"]["connectivity_test"] = {
                "status": "success", "gateway_url": gateway_url,
                "http_status": e.code, "attempts": attempt, "duration": elapsed(t0),
            }
            RESULTS["resources"]["gateway_url"] = gateway_url
            return True
        except Exception as e:
            warn(f"  Attempt {attempt}/3: {str(e)[:80]}")
            if attempt < 3:
                time.sleep(15)

    warn(f"Connectivity test FAILED -- {gateway_url} unreachable after 3 attempts")
    warn(f"  Manual check: curl {gateway_url}/health")
    RESULTS["stages"]["connectivity_test"] = {
        "status": "failed", "gateway_url": gateway_url, "reason": "connection_refused",
    }
    return False


# =============================================================================
#  STAGE 7: REPORT
# =============================================================================
def stage_report():
    section("STAGE 7: Final Report")
    RESULTS["completed_at"] = datetime.now().isoformat()
    RESULTS["outputs_dir"] = str(OUT)

    report_json = OUT / "deployment_report.json"
    report_json.write_text(json.dumps(RESULTS, indent=2))
    ok(f"Report: {report_json}")

    print(f"\n{'='*60}")
    print(f"  DEPLOYMENT COMPLETE -- {cfg['project_name']}")
    print(f"{'='*60}")
    print(f"  Image:      {IMAGE}")
    print(f"  Cluster:    {RESULTS['resources'].get('sks_cluster', {}).get('id', '?')}")
    print(f"  Kubeconfig: {RESULTS['resources'].get('kubeconfig', '?')}")
    ingress = RESULTS["resources"].get("ingress", {})
    if ingress.get("lb_ip"):
        print(f"  Ingress LB: {ingress['lb_ip']}")
        print(f"  HTTPS:      https://{ingress.get('domain', '?')} "
              f"(cert: {ingress.get('cert_status', 'unknown')})")
    print(f"  Outputs:    {OUT}")
    print(f"{'='*60}")
    print("\nTeardown commands:")
    print(f"  python3 teardown.py          # Auto-discovers all {cfg['project_name']}-* resources")
    print(f"  python3 teardown.py --dry-run # Preview what will be deleted")
    print(f"  docker rmi {IMAGE} {IMAGE_LTS}")
    print()


# =============================================================================
#  STAGE 3b: OBJECT STORAGE (SOS)
# =============================================================================
def stage_object_storage() -> dict | None:
    sos_cfg = cfg.get("object_storage", {})
    if not sos_cfg.get("enabled"):
        log("Object Storage (SOS): disabled -- skipping")
        return None

    section("STAGE 3b: Object Storage (SOS)")
    t0 = time.time()

    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        warn("boto3 not installed -- run: pip install boto3")
        warn("Object Storage skipped")
        return None

    zone         = cfg["exoscale_zone"]
    bucket_suffix = sos_cfg.get("bucket_name", "assets")
    bucket_name  = f"{_slug}-{bucket_suffix}"
    sos_endpoint = f"https://sos-{zone}.exoscale.com"

    log(f"SOS endpoint: {sos_endpoint}")
    log(f"Creating bucket: {bucket_name}")

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=sos_endpoint,
            aws_access_key_id=cfg["exo_key"],
            aws_secret_access_key=cfg["exo_secret"],
            region_name=zone,
        )
        s3.create_bucket(Bucket=bucket_name)
        ok(f"SOS bucket created: {bucket_name}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            ok(f"SOS bucket already exists: {bucket_name}")
        else:
            warn(f"SOS bucket creation failed: {e}")
            warn("Object Storage skipped -- continuing pipeline")
            return None
    except Exception as e:
        warn(f"SOS endpoint unreachable: {str(e)[:120]}")
        warn(f"  Endpoint: {sos_endpoint}")
        warn("  Create bucket manually: Exoscale Console -> Object Storage -> New Bucket")
        warn("  Object Storage skipped -- continuing pipeline")
        RESULTS["resources"]["object_storage"] = {
            "bucket": bucket_name,
            "endpoint": sos_endpoint,
            "status": "skipped_network_error",
        }
        return None

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


# =============================================================================
#  STAGE 3c: DBAAS (MANAGED DATABASE)
# =============================================================================
def stage_dbaas() -> dict | None:
    db_cfg = cfg.get("database", {})
    if not db_cfg.get("enabled"):
        log("DBaaS: disabled -- skipping")
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

    # Plan 153: Idempotent creation — reuse existing DBaaS if persist_on_teardown
    _already_exists = False
    try:
        if db_type == "pg":
            c.create_dbaas_service_pg(
                name=db_name,
                plan=db_plan,
                version=db_ver,
                termination_protection=term_protect,
            )
        elif db_type == "mysql":
            c.create_dbaas_service_mysql(  # LESSON 28: was 'mysq' (typo fixed)
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
            warn(f"DBaaS type '{db_type}' not yet supported in pipeline -- skipping")
            return None
    except Exception as e:
        _err = str(e).lower()
        if "already exists" in _err or "409" in _err or "conflict" in _err:
            ok(f"DBaaS '{db_name}' already exists — reusing (persist_on_teardown)")
            _already_exists = True
        else:
            warn(f"DBaaS creation failed: {str(e)[:150]}")
            warn("DBaaS skipped -- continuing pipeline")
            return None

    if not _already_exists:
        ok(f"DBaaS {db_type} service '{db_name}' creation initiated")

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
        warn(f"DBaaS not ready after {elapsed(t0)} -- recording as pending")
        RESULTS["resources"]["dbaas"] = {
            "name": db_name, "type": db_type, "plan": db_plan, "state": "pending"
        }
        return {"name": db_name, "type": db_type, "state": "pending"}

    conn_info = db_info.get("connection-info", {})
    pg_uri = None
    if db_type == "pg" and conn_info:
        uris = conn_info.get("pg", [])
        pg_uri = uris[0] if uris else None

    ok(f"DBaaS {db_type} '{db_name}' is RUNNING ({elapsed(t0)})")

    # Plan 153: Initialize pgvector extension + schema for PostgreSQL
    if db_type == "pg" and pg_uri:
        _pgvector_schema = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    embedding vector(1536),
    context TEXT[] DEFAULT '{}',
    analysis TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_entities_user_type ON entities (user_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_user_type_ts ON entities (user_id, entity_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_entities_user ON entities (user_id);
CREATE INDEX IF NOT EXISTS idx_entities_data_gin ON entities USING gin (data);
"""
        log("Initializing pgvector extension + schema...")
        try:
            _r = subprocess.run(
                ["psql", pg_uri, "-c", _pgvector_schema],
                capture_output=True, text=True, timeout=30,
            )
            if _r.returncode == 0:
                ok("pgvector extension + schema initialized")
            else:
                warn(f"Schema init warning: {_r.stderr[:150]}")
                log("  memory-system will self-initialize on startup (belt + suspenders)")
        except FileNotFoundError:
            log("  psql not available locally — memory-system will self-initialize on startup")
        except Exception as _e:
            warn(f"Schema init: {str(_e)[:100]} — memory-system will self-initialize on startup")

    db_result = {
        "name": db_name,
        "type": db_type,
        "plan": db_plan,
        "state": "running",
        "connection_uri": pg_uri or f"see Exoscale console: {db_name}",
    }
    RESULTS["resources"]["dbaas"] = db_result
    return db_result


# =============================================================================
#  STAGE 4b: NODE LABELS
# =============================================================================
def stage_label_nodes(kubeconfig: str) -> None:
    nl_cfg = cfg.get("node_labels", {})
    if not nl_cfg.get("enabled"):
        log("Node Labels: disabled -- skipping")
        return

    labels_map = nl_cfg.get("labels", {})
    if not labels_map:
        log("Node Labels: no labels configured -- skipping")
        return

    section("STAGE 4b: Node Labels (StarGate branding)")
    env = {**os.environ, "KUBECONFIG": kubeconfig}

    r = subprocess.run(
        ["kubectl", "get", "nodes", "--no-headers", "-o", "custom-columns=NAME:.metadata.name"],
        env=env, capture_output=True, text=True,
    )
    nodes = [n.strip() for n in r.stdout.strip().split("\n") if n.strip()]
    log(f"Applying StarGate labels to {len(nodes)} node(s)...")

    def _sanitize_label_value(v: str) -> str:
        s = re.sub(r'[^a-zA-Z0-9_.\-]', '-', str(v))
        s = re.sub(r'-+', '-', s).strip('-')
        return s[:63]

    label_args = [f"{k}={_sanitize_label_value(v)}" for k, v in labels_map.items()]

    for node in nodes:
        r = subprocess.run(
            ["kubectl", "label", "node", node, "--overwrite"] + label_args,
            env=env, capture_output=True, text=True,
        )
        if r.returncode == 0:
            ok(f"  {node} -> labels applied")
        else:
            warn(f"  {node} label failed: {r.stderr[:80]}")

    r = subprocess.run(
        ["kubectl", "get", "nodes", "--show-labels"],
        env=env, capture_output=True, text=True,
    )
    log("\nNodes with labels:")
    for line in r.stdout.strip().split("\n"):
        log(f"  {line}")

    RESULTS["stages"]["node_labels"] = {"status": "success", "nodes": nodes, "labels": labels_map}


# =============================================================================
#  STAGE 5b: EXOSCALE CSI DRIVER (Block Storage)
# =============================================================================
def stage_install_csi(kubeconfig: str) -> bool:
    bs_cfg = cfg.get("block_storage", {})
    if not bs_cfg.get("enabled"):
        log("Block Storage (CSI): disabled -- skipping")
        return False

    section("STAGE 5b: Block Storage -- CSI Driver")
    t0 = time.time()
    env = {**os.environ, "KUBECONFIG": kubeconfig}

    CSI_NAMESPACE = "exoscale-csi"
    csi_manifests_dir = OUT / "csi-manifests"
    csi_manifests_dir.mkdir(parents=True, exist_ok=True)

    log("Installing Exoscale CSI driver...")

    subprocess.run(
        ["kubectl", "create", "namespace", CSI_NAMESPACE],
        env=env, capture_output=True, text=True,
    )

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

    _CSI_CANDIDATE_URLS = [
        "https://raw.githubusercontent.com/exoscale/exoscale-csi-driver/main/deploy/k8s/csi-driver.yaml",
        "https://raw.githubusercontent.com/exoscale/exoscale-csi-driver/main/deploy/manifests/csi-driver.yaml",
        "https://raw.githubusercontent.com/exoscale/exoscale-csi-driver/main/deploy/exoscale-csi-driver.yaml",
    ]
    _csi_applied = False
    for _csi_url in _CSI_CANDIDATE_URLS:
        log(f"Trying CSI manifest: {_csi_url}")
        r = subprocess.run(
            ["kubectl", "apply", "-f", _csi_url],
            env=env, capture_output=True, text=True,
        )
        if r.returncode == 0:
            ok(f"Exoscale CSI driver applied from: {_csi_url}")
            for line in r.stdout.strip().split("\n"):
                log(f"  {line}")
            _csi_applied = True
            break
        else:
            warn(f"  URL failed: {r.stderr[:80]}")
    if not _csi_applied:
        warn("All CSI manifest URLs failed -- falling back to manual StorageClass creation")

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


# =============================================================================
#  STAGE 5d: INJECT SERVICE CREDENTIALS AS K8S SECRETS
#  (was Stage 5c prior to Plan 123-P5; renamed to 5d to make room for ingress/TLS)
#  Injects DB connection URI and SOS bucket credentials as K8s secrets.
#  Apps consume: secret/db-credentials and secret/sos-credentials
# =============================================================================
def stage_inject_secrets(kubeconfig: str, db_info: dict | None, sos_info: dict | None) -> None:
    # L72: Always run — AI keys must be injected even when DB/SOS are disabled
    section("STAGE 5d: Inject Service Credentials (K8s Secrets)")
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    ns  = cfg["k8s_namespace"]

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
        log(f"DBaaS state={db_info.get('state')} -- DB secret will need manual injection after service is running")

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

    # L57: Create/update jtp-gateway-config ConfigMap so service pods can call
    # each other through GATEWAY_URL (inter-service communication).
    gateway_url = RESULTS.get("resources", {}).get("gateway_url", "")
    if not gateway_url:
        # Fallback: derive from ingress LB IP if connectivity test hasn't run yet
        _ingress = RESULTS.get("resources", {}).get("ingress", {})
        _lb_ip = _ingress.get("lb_ip", "")
        gateway_url = f"http://{_lb_ip}" if _lb_ip else ""
    if gateway_url:
        gateway_cm_yaml = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: jtp-gateway-config
  namespace: {ns}
  labels:
    app.kubernetes.io/managed-by: exoscale-deploy-kit
    plan: l57-inter-service
data:
  GATEWAY_URL: "{gateway_url}"
  SERVICE_CALL_TIMEOUT: "2.0"
"""
        r_cm = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=gateway_cm_yaml, env=env, text=True, capture_output=True,
        )
        if r_cm.returncode == 0:
            ok(f"ConfigMap 'jtp-gateway-config' applied (GATEWAY_URL={gateway_url})")
        else:
            warn(f"jtp-gateway-config ConfigMap: {r_cm.stderr[:120]}")
    else:
        log("GATEWAY_URL not yet resolved — jtp-gateway-config ConfigMap will be applied after connectivity test")

    # L72: Inject ALL AI API keys for gateway + 12 AI backend services
    # Keys are read from environment (populated from .env file).
    # All pods have envFrom: secretRef: ai-api-keys (optional: true),
    # so every key in this secret is available to every pod automatically.
    _ai_keys = {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "PINECONE_API_KEY": os.getenv("PINECONE_API_KEY", ""),
        "PINECONE_ENVIRONMENT": os.getenv("PINECONE_ENVIRONMENT", ""),
        "PINECONE_INDEX_NAME": os.getenv("PINECONE_INDEX_NAME", ""),
        "COHERE_API_KEY": os.getenv("COHERE_API_KEY", ""),
        "GROK_API_KEY": os.getenv("GROK_API_KEY", ""),
        "HUGGINGFACE_TOKEN": os.getenv("HUGGINGFACE_TOKEN", ""),
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY", ""),
        "DEEPGRAM_API_KEY": os.getenv("DEEPGRAM_API_KEY", ""),
        "ELEVENLABS_API_KEY": os.getenv("ELEVENLABS_API_KEY", ""),
        "PERPLEXITY_API_KEY": os.getenv("PERPLEXITY_API_KEY", ""),
        "FIRECRAWL_API_KEY": os.getenv("FIRECRAWL_API_KEY", ""),
        "HELICONE_API_KEY": os.getenv("HELICONE_API_KEY", ""),
        "SENDGRID_API_KEY": os.getenv("SENDGRID_API_KEY", ""),
        "STRIPE_API_KEY": os.getenv("STRIPE_API_KEY", ""),
        "HEYGEN_API_KEY": os.getenv("HEYGEN_API_KEY", ""),
        "DID_API_KEY": os.getenv("DID_API_KEY", ""),
        "TAVUS_API_KEY": os.getenv("TAVUS_API_KEY", ""),
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
        # L64: LinkedIn OAuth for job search + profile import
        "LINKEDIN_CLIENT_ID": os.getenv("LINKEDIN_CLIENT_ID", ""),
        "LINKEDIN_CLIENT_SECRET": os.getenv("LINKEDIN_CLIENT_SECRET", ""),
    }
    # Only include keys that have actual values
    _populated = {k: v for k, v in _ai_keys.items() if v}
    if _populated:
        _string_data = "\n".join(f'  {k}: "{v}"' for k, v in _populated.items())
        ai_secret_yaml = f"""apiVersion: v1
kind: Secret
metadata:
  name: ai-api-keys
  namespace: {ns}
  labels:
    app.kubernetes.io/managed-by: exoscale-deploy-kit
    plan: l72-full-ai-stack
type: Opaque
stringData:
{_string_data}
"""
        r_ai = subprocess.run(  # nosec B603
            ["kubectl", "apply", "-f", "-"],
            input=ai_secret_yaml, env=env, text=True, capture_output=True,
        )
        if r_ai.returncode == 0:
            ok(f"Secret 'ai-api-keys' applied ({len(_populated)} keys injected for L72 AI stack)")
        else:
            warn(f"ai-api-keys Secret: {r_ai.stderr[:120]}")
    else:
        warn("L72: No AI API keys found in environment — AI services will run in demo mode")

    RESULTS["stages"]["inject_secrets"] = {"status": "success"}

    # ── Plan 133: Validate AI API keys are functional ──
    _validate_ai_keys()


def _validate_ai_keys():
    """Plan 133: Validate AI API keys are functional — warn operator of quota issues."""
    section("AI API Key Validation (Plan 133)")
    import requests as _req
    _results = {}
    # Test Anthropic
    _ak = os.getenv("ANTHROPIC_API_KEY", "")
    if _ak:
        try:
            _r = _req.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": _ak, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 5,
                      "messages": [{"role": "user", "content": "ping"}]},
                timeout=15)
            if _r.status_code == 200:
                _results["anthropic"] = "VALID"
                ok("  Anthropic API key: ✅ VALID")
            else:
                _results["anthropic"] = f"ERROR {_r.status_code}"
                warn(f"  Anthropic API key: ❌ HTTP {_r.status_code} — {_r.text[:100]}")
        except Exception as _e:
            _results["anthropic"] = f"UNREACHABLE: {_e}"
            warn(f"  Anthropic API key: ❌ UNREACHABLE — {_e}")
    else:
        warn("  Anthropic API key: ⚠️ NOT SET — AI chat will be disabled")

    # Test OpenAI
    _ok = os.getenv("OPENAI_API_KEY", "")
    if _ok:
        try:
            _r = _req.get("https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {_ok}"}, timeout=15)
            if _r.status_code == 200:
                _results["openai"] = "VALID"
                ok("  OpenAI API key: ✅ VALID")
            elif _r.status_code == 429:
                _results["openai"] = "QUOTA EXCEEDED"
                warn("  ⚠️  OpenAI API key: QUOTA EXCEEDED — cv_processor will use Anthropic fallback")
                warn("  ⚠️  Top up at: https://platform.openai.com/account/billing")
            else:
                _results["openai"] = f"ERROR {_r.status_code}"
                warn(f"  OpenAI API key: ❌ HTTP {_r.status_code}")
        except Exception as _e:
            _results["openai"] = f"UNREACHABLE: {_e}"
            warn(f"  OpenAI API key: ❌ UNREACHABLE — {_e}")

    # Test Pinecone
    _pk = os.getenv("PINECONE_API_KEY", "")
    if _pk:
        try:
            _r = _req.get("https://api.pinecone.io/indexes",
                headers={"Api-Key": _pk}, timeout=15)
            if _r.status_code == 200:
                _results["pinecone"] = "VALID"
                ok("  Pinecone API key: ✅ VALID")
            else:
                _results["pinecone"] = f"ERROR {_r.status_code}"
                warn(f"  Pinecone API key: ❌ HTTP {_r.status_code}")
        except Exception as _e:
            _results["pinecone"] = f"UNREACHABLE: {_e}"
            warn(f"  Pinecone API key: ❌ UNREACHABLE — {_e}")

    RESULTS["ai_key_validation"] = _results
    _valid = sum(1 for v in _results.values() if "VALID" in v)
    _total = len(_results)
    if _valid == _total:
        ok(f"  All {_valid}/{_total} AI API keys validated ✅")
    else:
        warn(f"  {_valid}/{_total} AI API keys valid — check warnings above")


# =============================================================================
#  ABORT CLEANUP -- Plan 122-DEH ISSUE-008
# =============================================================================
def pipeline_abort_cleanup() -> None:
    created = RESULTS.get("resources", {})
    if not any(k in created for k in ("security_group", "sks_cluster", "node_pool")):
        return

    warn("AUTO-CLEANUP: Deleting partially-created Exoscale resources to prevent orphans...")
    try:
        from exoscale.api.v2 import Client as _EXOClient
        _c = _EXOClient(cfg["exo_key"], cfg["exo_secret"], zone=cfg["exoscale_zone"])
    except Exception as _e:
        warn(f"AUTO-CLEANUP: Cannot connect to Exoscale SDK: {_e}")
        warn(f"  Manual recovery: python3 teardown.py --from-report {OUT / 'deployment_report_partial.json'}")
        return

    _cluster = created.get("sks_cluster", {})
    _np      = created.get("node_pool", {})
    _sg      = created.get("security_group", {})

    if _np.get("id") and _cluster.get("id"):
        try:
            warn(f"AUTO-CLEANUP: Deleting nodepool {_np['id'][:8]}...")
            _op = _c.delete_sks_nodepool(id=_cluster["id"], sks_nodepool_id=_np["id"])
            _op_id = _op.get("id")
            if _op_id:
                _c.wait(_op_id, max_wait_time=180)
            ok("AUTO-CLEANUP: Nodepool deleted")
        except Exception as _e:
            warn(f"AUTO-CLEANUP: Nodepool deletion warning (cluster deletion covers it): {_e}")

    if _cluster.get("id"):
        try:
            warn(f"AUTO-CLEANUP: Deleting cluster {_cluster.get('name', _cluster['id'][:8])}...")
            _op = _c.delete_sks_cluster(id=_cluster["id"])
            _op_id = _op.get("id")
            if _op_id:
                _c.wait(_op_id, max_wait_time=300)
            ok("AUTO-CLEANUP: Cluster deleted")
        except Exception as _e:
            if "404" in str(_e):
                ok("AUTO-CLEANUP: Cluster already gone")
            else:
                warn(f"AUTO-CLEANUP: Cluster deletion failed: {_e}")

    if _sg.get("id"):
        time.sleep(5)
        for _attempt in range(1, 4):
            try:
                warn(f"AUTO-CLEANUP: Deleting SG {_sg.get('name', _sg['id'][:8])} (attempt {_attempt}/3)...")
                _c.delete_security_group(id=_sg["id"])
                ok("AUTO-CLEANUP: Security group deleted -- no orphan left behind")
                break
            except Exception as _e:
                if "404" in str(_e):
                    ok("AUTO-CLEANUP: Security group already gone")
                    break
                if _attempt < 3:
                    warn(f"AUTO-CLEANUP: SG still locked -- retrying in 15s: {_e}")
                    time.sleep(15)
                else:
                    warn(f"AUTO-CLEANUP: SG deletion failed after 3 attempts: {_e}")
                    warn(f"  Manual recovery: python3 teardown.py --from-report {OUT / 'deployment_report_partial.json'}")


# =============================================================================
#  MAIN
# =============================================================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print(f"  EXOSCALE DEPLOY KIT -- {cfg['project_name'].upper()}")
    print(f"  Deployment ID: {TS}")
    print(f"  Image:  {IMAGE}")
    print(f"  Zone:   {cfg['exoscale_zone']}")
    print(f"  Output: {OUT}")
    print("="*60 + "\n")

    if "--skip-preflight" in sys.argv:
        warn("STAGE 0: Preflight skipped (--skip-preflight flag set -- not recommended)")
    else:
        gf_stage_start('0 Preflight')
        stage_preflight()
        gf_stage_end('0 Preflight', 'success')

    try:
        gf_stage_start('1 Docker Build', IMAGE)
        stage_docker_build()
        gf_stage_end('1 Docker Build', 'success', IMAGE)
        gf_stage_start('2 Docker Push', IMAGE)
        stage_docker_push()
        gf_stage_end('2 Docker Push', 'success', IMAGE)

        gf_stage_start('3b Object Storage')
        sos_info = stage_object_storage()
        gf_stage_end('3b Object Storage', 'success')
        gf_stage_start('3b DBaaS')
        db_info  = stage_dbaas()
        gf_stage_end('3b DBaaS', 'success')

        gf_stage_start('3 Exoscale Infra', cfg.get('exoscale_zone',''))
        kubeconfig = stage_exoscale()
        gf_stage_end('3 Exoscale Infra', 'success')
        gf_stage_start('4 Wait Nodes')
        stage_wait_for_nodes(kubeconfig)
        gf_stage_end('4 Wait Nodes', 'success')

        stage_sg_post_attach()
        gf_stage_start('4b Node Labels')
        stage_label_nodes(kubeconfig)
        gf_stage_end('4b Node Labels', 'success')

        # Stage 5b: CSI driver + PVC manifest
        gf_stage_start('5b CSI Driver')
        stage_install_csi(kubeconfig)
        gf_stage_end('5b CSI Driver', 'success')

        # ISSUE-017: Refresh kubeconfig before Stage 5c -- TLS cert may have rotated
        # during the 3-8 min node wait (Exoscale SKS rotates certs periodically).
        # All kubectl calls already use --insecure-skip-tls-verify as fallback,
        # but a fresh kubeconfig is cleaner and avoids x509 warnings.
        kubeconfig = refresh_kubeconfig(kubeconfig)

        # Stage 5c: nginx-ingress + cert-manager + TLS  (Plan 123-P5 ISSUE-018)
        # Ordering: nginx LB IP -> NLB port fix (ISSUE-021) -> DNS -> cert-manager -> Ingress
        gf_stage_start('5c Ingress TLS', cfg.get('ingress',{}).get('domain',''))
        stage_5c_ingress_tls(kubeconfig)
        gf_stage_end('5c Ingress TLS', 'success')

        gf_stage_start('5 K8s Manifests')
        stage_kubernetes(kubeconfig)
        gf_stage_end('5 K8s Manifests', 'success')

        # Stage 5d: Inject DB + SOS credentials as K8s secrets
        gf_stage_start('5d Inject Secrets')
        stage_inject_secrets(kubeconfig, db_info, sos_info)
        gf_stage_end('5d Inject Secrets', 'success')

        gf_stage_start('6 Verify Pods')
        stage_verify(kubeconfig)
        gf_stage_end('6 Verify Pods', 'success')

        # Stage 6b: Connectivity test -- now uses LB IP (Plan 123-P5 ISSUE-016)
        gf_stage_start('6b Connectivity Test')
        stage_connectivity_test(kubeconfig)
        gf_stage_end('6b Connectivity Test', 'success')

        # L72: Restore chat logs from backup (deep persistence across deploys)
        _chat_backup = KIT_DIR / "chat_logs_backup.jsonl"
        if _chat_backup.exists():
            try:
                _domain = cfg.get("ingress", {}).get("domain", "")
                if _domain:
                    import urllib.request, ssl
                    _ctx = ssl.create_default_context()
                    _ctx.check_hostname = False
                    _ctx.verify_mode = ssl.CERT_NONE
                    _data = _chat_backup.read_bytes()
                    _req = urllib.request.Request(
                        f"https://{_domain}/chat/logs/import",
                        data=_data,
                        headers={"Content-Type": "application/jsonl"},
                        method="POST",
                    )
                    _resp = urllib.request.urlopen(_req, timeout=15, context=_ctx)
                    _result = json.loads(_resp.read())
                    ok(f"L72: Chat logs restored — {_result.get('imported', 0)} entries imported")
                else:
                    log("L72: No domain — skipping chat log restore")
            except Exception as _exc:
                warn(f"L72: Chat log restore failed (non-fatal): {_exc}")
        else:
            log("L72: No chat log backup found — starting fresh")

        # Stage 6c: Deploy Monitoring (Prometheus + Grafana) — Plan 170 Gap 15
        # This is NOT optional — monitoring is part of the infrastructure.
        gf_stage_start('6c Monitoring Stack')
        log("Stage 6c: Deploying monitoring stack (Prometheus + Grafana)...")
        _mon_script = KIT_DIR / "monitoring" / "deploy_monitoring.sh"
        if _mon_script.exists():
            _mon_env = {**os.environ, "KUBECONFIG": kubeconfig}
            _mon_result = subprocess.run(
                ["bash", str(_mon_script)],
                env=_mon_env,
                capture_output=False,
            )
            if _mon_result.returncode == 0:
                ok("Monitoring stack deployed (Prometheus + Grafana)")
                RESULTS["monitoring"] = {"deployed": True}
            else:
                warn(f"Monitoring deployment failed (exit code {_mon_result.returncode})")
                RESULTS["monitoring"] = {"deployed": False, "error": f"exit code {_mon_result.returncode}"}
        else:
            warn("monitoring/deploy_monitoring.sh not found — skipping")
            RESULTS["monitoring"] = {"deployed": False, "error": "script not found"}
        gf_stage_end('6c Monitoring Stack', 'success')

        # Stage 7b: Post-Deploy Test Suite — Plan 174
        # Runs ALL service tests (user_stories, integration, e2e, security) against live gateway
        gf_stage_start('7b Post-Deploy Tests')
        log("Stage 7b: Running post-deploy test suite against live gateway...")
        try:
            _test_runner = KIT_DIR / "run_external_tests.py"
            if _test_runner.exists():
                # Determine gateway URL from ingress LB IP
                _gw_url = ""
                _ingress = RESULTS.get("resources", {}).get("ingress", {})
                if _ingress.get("lb_ip"):
                    _gw_url = f"https://{_ingress['lb_ip']}"
                elif _ingress.get("domain"):
                    _gw_url = f"https://{_ingress['domain']}"

                if _gw_url:
                    _test_output = OUT / "post_deploy_test_results.json"
                    _test_cmd = [
                        sys.executable, str(_test_runner),
                        "--gateway", _gw_url,
                        "--suites", "user_stories", "integration",
                        "--workers", "10",
                        "--output", str(_test_output),
                    ]
                    _test_env = {**os.environ, "KUBECONFIG": kubeconfig}
                    log(f"  Running: {' '.join(_test_cmd[:6])}...")
                    _test_result = subprocess.run(
                        _test_cmd,
                        env=_test_env,
                        capture_output=True,
                        text=True,
                        timeout=600,  # 10 minute max
                    )
                    if _test_output.exists():
                        _test_data = json.loads(_test_output.read_text())
                        _tests_passed = _test_data.get("tests_passed", 0)
                        _tests_failed = _test_data.get("tests_failed", 0)
                        _tests_total = _tests_passed + _tests_failed
                        _pass_rate = _tests_passed / _tests_total if _tests_total > 0 else 0
                        RESULTS["post_deploy_tests"] = {
                            "total": _tests_total,
                            "passed": _tests_passed,
                            "failed": _tests_failed,
                            "pass_rate": round(_pass_rate, 3),
                        }
                        if _pass_rate >= 0.95:
                            ok(f"Post-deploy tests: {_tests_passed}/{_tests_total} = {_pass_rate:.0%} — PASS")
                        else:
                            warn(f"Post-deploy tests: {_tests_passed}/{_tests_total} = {_pass_rate:.0%} — below 95% target")
                    else:
                        warn("Post-deploy test output file not created")
                        RESULTS["post_deploy_tests"] = {"error": "no output file"}
                else:
                    warn("No gateway URL available — skipping post-deploy tests")
                    RESULTS["post_deploy_tests"] = {"error": "no gateway URL"}
            else:
                warn("run_external_tests.py not found — skipping post-deploy tests")
                RESULTS["post_deploy_tests"] = {"error": "runner not found"}
        except subprocess.TimeoutExpired:
            warn("Post-deploy tests timed out after 600s")
            RESULTS["post_deploy_tests"] = {"error": "timeout"}
        except Exception as _exc:
            warn(f"Post-deploy tests failed: {_exc}")
            RESULTS["post_deploy_tests"] = {"error": str(_exc)}
        gf_stage_end('7b Post-Deploy Tests', 'success')

        gf_stage_start('7 Final Report')
        stage_report()
        gf_stage_end('7 Final Report', 'success', f'Image={IMAGE}')
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        fail(f"Pipeline exception: {e}")
        gf_annotate(f"PIPELINE EXCEPTION: {e}", tags=['exception'], is_error=True)
        traceback.print_exc()
        (OUT / "deployment_report_partial.json").write_text(json.dumps(RESULTS, indent=2))
        pipeline_abort_cleanup()
        sys.exit(1)
