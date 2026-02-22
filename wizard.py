#!/usr/bin/env python3
"""
Exoscale Deploy Kit — Interactive Configuration Wizard
=======================================================
Guides you through all deployment parameters and writes config.yaml.

Usage:
  python3 wizard.py                     # Run wizard, optionally deploy
  python3 deploy_pipeline.py            # Wizard auto-runs before deploy
  python3 deploy_pipeline.py --auto     # Skip wizard, use existing config.yaml
"""
import re
import sys, os, subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("pyyaml not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

# ── ANSI colours ──────────────────────────────────────────────
BOLD="[1m"; DIM="[2m"; CYAN="[36m"
GREEN="[32m"; YELLOW="[33m"; RED="[31m"; RESET="[0m"

def bold(s):   return f"{BOLD}{s}{RESET}"
def dim(s):    return f"{DIM}{s}{RESET}"
def cyan(s):   return f"{CYAN}{s}{RESET}"
def green(s):  return f"{GREEN}{s}{RESET}"
def yellow(s): return f"{YELLOW}{s}{RESET}"
def red(s):    return f"{RED}{s}{RESET}"

# ── Option tables ──────────────────────────────────────────────
ZONES = [
    ("ch-gva-2", "Geneva, Switzerland    (recommended default)"),
    ("ch-dk-2",  "Zurich, Switzerland"),
    ("de-fra-1", "Frankfurt, Germany"),
    ("at-vie-1", "Vienna, Austria"),
    ("bg-sof-1", "Sofia, Bulgaria"),
]
INSTANCE_FAMILIES = [
    ("standard", "Balanced CPU/RAM — web apps, APIs, microservices (recommended)"),
    ("memory",   "High RAM — databases, in-memory caches, Elasticsearch"),
    ("cpu",      "High CPU — compute jobs, rendering, ML inference"),
    ("storage",  "High disk throughput — log processing, data pipelines"),
    ("gpu",      "GPU instances — ML training, AI workloads"),
]
INSTANCE_SIZES = [
    ("tiny",        " 1 vCPU,   512 MB RAM  — dev/test only — NOT for SKS node pools (API restriction)"),
    ("small",       " 2 vCPU,   2 GB  RAM   — lightweight apps"),
    ("medium",      " 4 vCPU,   4 GB  RAM   — recommended for most services"),
    ("large",       " 4 vCPU,   8 GB  RAM   — production workloads"),
    ("extra-large", " 8 vCPU,  16 GB  RAM   — high-traffic services"),
    ("huge",        "12 vCPU,  32 GB  RAM   — heavy / data-intensive workloads"),
]
SKS_LEVELS = [
    ("starter", "Basic K8s control plane — lower cost, suitable for dev/staging"),
    ("pro",     "Production-grade — SLA-backed, recommended for production"),
]
SKS_CNIS = [
    ("calico", "Calico — most widely used, full NetworkPolicy support (recommended)"),
    ("cilium", "Cilium — eBPF-based, advanced observability + security policies"),
]
DB_TYPES = [
    ("postgres", "PostgreSQL — best general-purpose relational database"),
    ("mysql",    "MySQL / MariaDB — popular for web applications"),
    ("redis",    "Redis — in-memory cache, session store, message queue"),
]
DB_DEPLOY_MODES = [
    ("managed",     "Exoscale DBaaS — fully managed, auto-backups (recommended)"),
    ("self-hosted", "K8s StatefulSet — full control, manual ops, lower cloud cost"),
]
INGRESS_PROVIDERS = [
    ("nginx",   "nginx-ingress — battle-tested, most widely deployed"),
    ("traefik", "Traefik — built-in Let's Encrypt, automatic TLS renewal"),
]
ENVIRONMENTS = [
    ("dev",        "Development  — minimal resources, 1 replica, no HPA or PDB"),
    ("staging",    "Staging      — moderate resources, 2 replicas, HPA enabled"),
    ("production", "Production   — full resources, 3+ replicas, HPA + PDB enabled"),
]

# ── UI helpers ────────────────────────────────────────────────
def hdr(title: str):
    print(f"\n{CYAN}{'='*62}{RESET}")
    print(f"{CYAN}  {BOLD}{title}{RESET}")
    print(f"{CYAN}{'='*62}{RESET}")

def sec(num: int, total: int, title: str):
    print(f"\n{BOLD}{CYAN}[{num}/{total}] {title}{RESET}")
    print(f"{DIM}{'-'*50}{RESET}")

def prompt(q: str, default: str = "", required: bool = False) -> str:
    sfx = f" [{dim(default)}]" if default else ""
    while True:
        v = input(f"  {q}{sfx}: ").strip()
        if not v:
            if default: return default
            if required: print(f"  {red('Required.')}"); continue
        return v or default

def prompt_int(q: str, default: int, lo: int = 1, hi: int = 9999) -> int:
    while True:
        raw = prompt(q, str(default))
        try:
            v = int(raw)
            if lo <= v <= hi: return v
            print(f"  {red(f'Must be {lo}-{hi}.')}")
        except ValueError:
            print(f"  {red('Enter a whole number.')}")

def prompt_bool(q: str, default: bool = True) -> bool:
    sfx = "Y/n" if default else "y/N"
    raw = input(f"  {q} [{dim(sfx)}]: ").strip().lower()
    if not raw: return default
    return raw in ("y", "yes", "1", "true")

def choose(opts: list, def_idx: int = 0) -> tuple:
    for i, (v, d) in enumerate(opts, 1):
        marker = green("->") if i == def_idx + 1 else "  "
        print(f"    {marker} {bold(str(i))}. {bold(v):<16} {dim(d)}")
    while True:
        raw = input(f"  Choice [{dim(str(def_idx + 1))}]: ").strip()
        if not raw: return def_idx, opts[def_idx][0]
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(opts): return idx, opts[idx][0]
        except ValueError:
            pass
        print(f"  {red(f'Enter 1-{len(opts)}.')}")

def load_existing() -> dict:
    p = Path(__file__).parent / "config.yaml"
    if p.exists():
        try:
            with open(p) as f: return yaml.safe_load(f) or {}
        except Exception: pass
    return {}

def estimate_cost(cfg: dict) -> str:
    node_costs = {
        ("standard","tiny"): 3,   ("standard","small"): 10,
        ("standard","medium"): 30, ("standard","large"): 55,
        ("standard","extra-large"): 105, ("standard","huge"): 200,
        ("memory","small"): 15,   ("memory","medium"): 45,
        ("memory","large"): 80,   ("memory","extra-large"): 155,
        ("cpu","small"): 12,      ("cpu","medium"): 35,
        ("cpu","large"): 65,
    }
    k = (cfg.get("node_type_family","standard"), cfg.get("node_type_size","medium"))
    base = node_costs.get(k, 30) * cfg.get("node_count", 2)
    extra = 0; parts = []
    lb = cfg.get("load_balancer", {})
    if isinstance(lb, dict) and lb.get("enabled"):
        extra += 8; parts.append("NLB ~8")
    db = cfg.get("database", {})
    if isinstance(db, dict) and db.get("enabled") and db.get("deployment") == "managed":
        extra += 25; parts.append("DBaaS ~25+")
    xtra = " + " + ", ".join(parts) if parts else ""
    return f"~EUR {base}/mo nodes{xtra} = ~EUR {base + extra}/mo total"


# ════════════════════════════════════════════════════════════════
#  WIZARD — 9-step interactive configuration
# ════════════════════════════════════════════════════════════════
def run_wizard(existing: dict | None = None) -> dict:
    """Run interactive wizard. Returns complete config dict."""
    if existing is None:
        existing = load_existing()

    hdr("EXOSCALE DEPLOY KIT — CONFIGURATION WIZARD")
    print(f"  {dim('Guides you through all deployment parameters.')}")
    print(f"  {dim('Press Enter to accept the default shown in [brackets].')}")
    print(f"  {dim('Ctrl+C at any time to abort without saving.')}")

    cfg: dict[str, Any] = {}
    TOTAL = 9

    # ── [1/9] Project Identity ────────────────────────────────
    sec(1, TOTAL, "PROJECT IDENTITY")
    cfg["project_name"]    = prompt("Project name (prefix for all cloud resources)",
                                     existing.get("project_name", "my-project"), required=True)
    # LESSON 14/16: warn if project_name has uppercase — resource names are slugified
    _pn_slug = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', cfg["project_name"].lower())).strip('-')
    if cfg["project_name"] != _pn_slug:
        print(f'\n  ⚠️  Note: project_name will be auto-slugified to \"{_pn_slug}\" for resource names')
        print(f'      Consider setting project_name: {_pn_slug} to avoid surprises')
    cfg["service_name"]    = prompt("Service / Docker image name",
                                     existing.get("service_name", "my-service"), required=True)
    cfg["service_version"] = prompt("Service version",
                                     existing.get("service_version", "1.0.0"), required=True)
    cfg["docker_hub_user"] = prompt("Docker Hub username",
                                     existing.get("docker_hub_user", ""), required=True)

    # ── [2/9] Environment Profile ─────────────────────────────
    sec(2, TOTAL, "ENVIRONMENT PROFILE")
    print(f"  {dim('Sets sensible defaults for replicas, resources, and HA.')}")
    existing_env = existing.get("environment", "production")
    env_def_idx = next((i for i,(v,_) in enumerate(ENVIRONMENTS) if v == existing_env), 2)
    _, cfg["environment"] = choose(ENVIRONMENTS, env_def_idx)

    # ── [3/9] Exoscale Zone & SKS ─────────────────────────────
    sec(3, TOTAL, "EXOSCALE ZONE & CLUSTER")
    existing_zone = existing.get("exoscale_zone", "ch-gva-2")
    zone_def_idx = next((i for i,(v,_) in enumerate(ZONES) if v == existing_zone), 0)
    _, cfg["exoscale_zone"] = choose(ZONES, zone_def_idx)

    print(f"\n  {bold('SKS cluster level:')}")
    existing_level = existing.get("sks_level", "pro")
    lvl_def_idx = next((i for i,(v,_) in enumerate(SKS_LEVELS) if v == existing_level), 1)
    _, cfg["sks_level"] = choose(SKS_LEVELS, lvl_def_idx)

    print(f"\n  {bold('Container Network Interface (CNI):')}")
    existing_cni = existing.get("sks_cni", "calico")
    cni_def_idx = next((i for i,(v,_) in enumerate(SKS_CNIS) if v == existing_cni), 0)
    _, cfg["sks_cni"] = choose(SKS_CNIS, cni_def_idx)
    cfg["sks_addons"] = ["exoscale-cloud-controller", "metrics-server"]

    # ── [4/9] Compute — Node Pool ─────────────────────────────
    sec(4, TOTAL, "COMPUTE — WORKER NODES")
    print(f"  {bold('Instance family:')}")
    existing_family = existing.get("node_type_family", "standard")
    fam_def_idx = next((i for i,(v,_) in enumerate(INSTANCE_FAMILIES) if v == existing_family), 0)
    _, cfg["node_type_family"] = choose(INSTANCE_FAMILIES, fam_def_idx)

    print(f"\n  {bold('Instance size:')}")
    existing_size = existing.get("node_type_size", "medium")
    size_def_idx = next((i for i,(v,_) in enumerate(INSTANCE_SIZES) if v == existing_size), 2)
    _, cfg["node_type_size"] = choose(INSTANCE_SIZES, size_def_idx)

    env_node_defaults = {"dev": 1, "staging": 2, "production": 3}
    default_nodes = existing.get("node_count", env_node_defaults.get(cfg["environment"], 2))
    cfg["node_count"] = prompt_int(
        "Number of worker nodes (min 2 for HA)",
        default_nodes, lo=1, hi=50
    )
    if cfg["node_count"] < 2 and cfg["environment"] == "production":
        print(f"  {yellow('WARNING: production should have at least 2 nodes for high availability.')}")

    cfg["node_disk_gb"] = prompt_int(
        "Disk size per node (GB)", existing.get("node_disk_gb", 50), lo=20, hi=2000
    )

    # ── [5/9] Kubernetes ──────────────────────────────────────
    sec(5, TOTAL, "KUBERNETES CONFIGURATION")
    default_ns = existing.get("k8s_namespace", f"{cfg['project_name']}-{cfg['environment']}")
    cfg["k8s_namespace"] = prompt("Kubernetes namespace", default_ns, required=True)

    env_replica_defaults = {"dev": 1, "staging": 2, "production": 3}
    default_replicas = existing.get("k8s_replicas", env_replica_defaults.get(cfg["environment"], 2))
    cfg["k8s_replicas"] = prompt_int("Pod replicas", default_replicas, lo=1, hi=100)
    cfg["k8s_port"] = prompt_int(
        "Container port (inside the container)", existing.get("k8s_port", 5000), lo=1, hi=65535
    )
    cfg["k8s_service_port"] = cfg["k8s_port"]
    print(f"  {dim('Pre-approved NodePorts (Exoscale default SG): 30671, 30888, 30999')}")
    cfg["k8s_nodeport"] = prompt_int(
        "NodePort", existing.get("k8s_nodeport", 30671), lo=30000, hi=32767
    )

    # ── [6/9] Load Balancer ───────────────────────────────────
    sec(6, TOTAL, "LOAD BALANCER")
    print(f"  {dim('Exoscale NLB auto-provisions via K8s type:LoadBalancer service.')}")
    print(f"  {dim('Adds ~EUR 8-10/mo. Recommended for staging and production.')}")
    existing_lb = existing.get("load_balancer", {})
    if isinstance(existing_lb, bool): existing_lb = {"enabled": existing_lb}
    lb_def = existing_lb.get("enabled", cfg["environment"] != "dev")
    lb_enabled = prompt_bool("Enable Exoscale NLB?", lb_def)
    cfg["load_balancer"] = {"enabled": lb_enabled, "type": "nlb"}
    if lb_enabled:
        print(f"  {green('NLB will be auto-provisioned by the Exoscale cloud controller.')}")
    else:
        print(f"  {yellow('NodePort access only — no external load balancer.')}")

    # ── [7/9] Ingress / Web Server ────────────────────────────
    sec(7, TOTAL, "INGRESS / WEB SERVER")
    print(f"  {dim('Ingress routes HTTP/HTTPS, enables custom domains, TLS, path routing.')}")
    existing_ingress = existing.get("ingress", {})
    ingress_enabled = prompt_bool("Enable Ingress controller?", existing_ingress.get("enabled", False))
    cfg["ingress"] = {"enabled": ingress_enabled}
    if ingress_enabled:
        print(f"\n  {bold('Provider:')}")
        existing_prov = existing_ingress.get("provider", "nginx")
        prov_def_idx = next((i for i,(v,_) in enumerate(INGRESS_PROVIDERS) if v == existing_prov), 0)
        _, cfg["ingress"]["provider"] = choose(INGRESS_PROVIDERS, prov_def_idx)
        cfg["ingress"]["tls"] = prompt_bool("Enable TLS/HTTPS?", existing_ingress.get("tls", False))
        if cfg["ingress"]["tls"]:
            cfg["ingress"]["domain"]     = prompt("Domain (e.g. myapp.example.com)",
                                                    existing_ingress.get("domain", ""), required=True)
            cfg["ingress"]["cert_email"] = prompt("Let's Encrypt email for TLS cert notifications",
                                                    existing_ingress.get("cert_email", ""), required=True)
        else:
            cfg["ingress"]["domain"] = existing_ingress.get("domain", "")
            cfg["ingress"]["cert_email"] = ""
    else:
        print(f"  {yellow('No Ingress. Services exposed via NodePort/LoadBalancer only.')}")

    # ── [8/9] Database ────────────────────────────────────────
    sec(8, TOTAL, "DATABASE")
    existing_db = existing.get("database", {})
    db_enabled = prompt_bool("Include a database?", existing_db.get("enabled", False))
    cfg["database"] = {"enabled": db_enabled}
    if db_enabled:
        print(f"\n  {bold('Database type:')}")
        existing_dbtype = existing_db.get("type", "postgres")
        dbtype_def_idx = next((i for i,(v,_) in enumerate(DB_TYPES) if v == existing_dbtype), 0)
        _, cfg["database"]["type"] = choose(DB_TYPES, dbtype_def_idx)

        print(f"\n  {bold('Deployment mode:')}")
        existing_mode = existing_db.get("deployment", "managed")
        mode_def_idx = next((i for i,(v,_) in enumerate(DB_DEPLOY_MODES) if v == existing_mode), 0)
        _, cfg["database"]["deployment"] = choose(DB_DEPLOY_MODES, mode_def_idx)

        db_versions = {"postgres": "16", "mysql": "8.0", "redis": "7.2"}
        default_ver = existing_db.get("version", db_versions.get(cfg["database"]["type"], "latest"))
        cfg["database"]["version"] = prompt("Version", default_ver)

        if cfg["database"]["deployment"] == "self-hosted":
            cfg["database"]["storage_gb"] = prompt_int(
                "Storage per DB instance (GB)", existing_db.get("storage_gb", 20), lo=10, hi=2000
            )
            cfg["database"]["replicas"] = prompt_int(
                "DB replicas (1=single, 3=HA)", existing_db.get("replicas", 1), lo=1, hi=10
            )
        else:
            cfg["database"]["storage_gb"] = existing_db.get("storage_gb", 20)
            cfg["database"]["replicas"] = 1
            print(f"  {yellow('NOTE: Exoscale DBaaS provisioning is manual — go to Console -> DBaaS after deploy.')}")
    else:
        print(f"  {yellow('No database included.')}")

    # ── [9/9] Autoscaling & Resources ────────────────────────
    sec(9, TOTAL, "AUTOSCALING & RESOURCE LIMITS")
    existing_as = existing.get("autoscaling", {})
    as_enabled = prompt_bool("Enable HPA (Horizontal Pod Autoscaler)?",
                              existing_as.get("enabled", cfg["environment"] != "dev"))

    env_resources = {
        "dev":        {"cpu_req":"50m",  "mem_req":"64Mi",  "cpu_lim":"200m",  "mem_lim":"256Mi"},
        "staging":    {"cpu_req":"100m", "mem_req":"128Mi", "cpu_lim":"500m",  "mem_lim":"512Mi"},
        "production": {"cpu_req":"200m", "mem_req":"256Mi", "cpu_lim":"1000m", "mem_lim":"1Gi"},
    }
    rd = env_resources.get(cfg["environment"], env_resources["staging"])
    existing_res = existing.get("resources", {})
    existing_req = existing_res.get("requests", {})
    existing_lim = existing_res.get("limits", {})

    cfg["autoscaling"] = {
        "enabled": as_enabled,
        "min_replicas": existing_as.get("min_replicas", cfg["k8s_replicas"]),
        "max_replicas": existing_as.get("max_replicas", 10),
        "cpu_target_percent": existing_as.get("cpu_target_percent", 70),
        "memory_target_percent": existing_as.get("memory_target_percent", 80),
    }
    if as_enabled:
        cfg["autoscaling"]["min_replicas"] = prompt_int(
            "Min replicas (HPA lower bound)", cfg["autoscaling"]["min_replicas"], lo=1, hi=100)
        cfg["autoscaling"]["max_replicas"] = prompt_int(
            "Max replicas (HPA upper bound)", cfg["autoscaling"]["max_replicas"],
            lo=cfg["autoscaling"]["min_replicas"], hi=500)
        cfg["autoscaling"]["cpu_target_percent"] = prompt_int(
            "CPU % target to trigger scale-out", cfg["autoscaling"]["cpu_target_percent"], lo=10, hi=100)
        cfg["autoscaling"]["memory_target_percent"] = prompt_int(
            "Memory % target to trigger scale-out", cfg["autoscaling"]["memory_target_percent"], lo=10, hi=100)

    print(f"\n  {bold('Container resource requests / limits:')}")
    print(f"  {dim('Requests = guaranteed. Limits = hard cap.')}")
    cfg["resources"] = {
        "requests": {
            "cpu":    prompt("CPU request (e.g. 100m)", existing_req.get("cpu", rd["cpu_req"])),
            "memory": prompt("Memory request (e.g. 128Mi)", existing_req.get("memory", rd["mem_req"])),
        },
        "limits": {
            "cpu":    prompt("CPU limit (e.g. 500m)", existing_lim.get("cpu", rd["cpu_lim"])),
            "memory": prompt("Memory limit (e.g. 512Mi)", existing_lim.get("memory", rd["mem_lim"])),
        },
    }

    # Derived flags
    cfg["monitoring"] = {"metrics_server": True}
    cfg["pod_disruption_budget"] = {
        "enabled": cfg["environment"] == "production",
        "min_available": 1,
    }

    return cfg


# ════════════════════════════════════════════════════════════════
#  SUMMARY + WRITE + MAIN
# ════════════════════════════════════════════════════════════════
def print_summary(cfg: dict):
    """Print a comprehensive deployment summary before proceeding."""
    hdr("DEPLOYMENT SUMMARY — PLEASE REVIEW CAREFULLY")
    W = 36
    def row(k, v): print(f"  {bold(k.ljust(W))} {v}")

    print()
    row("Project:",      f"{cfg['project_name']} / {cfg['service_name']}:{cfg['service_version']}")
    row("Docker Hub:",   cfg['docker_hub_user'])
    row("Environment:",  cfg['environment'].upper())
    row("Zone:",         cfg['exoscale_zone'])
    print()
    row("SKS Level:",    cfg['sks_level'])
    row("CNI:",          cfg['sks_cni'])
    row("Worker nodes:", (f"{cfg['node_count']} x {cfg['node_type_family']}."
                          f"{cfg['node_type_size']} ({cfg['node_disk_gb']}GB disk each)"))
    print()
    row("Namespace:",    cfg['k8s_namespace'])
    row("Replicas:",     str(cfg['k8s_replicas']))
    row("Container port:", str(cfg['k8s_port']))
    row("NodePort:",     str(cfg['k8s_nodeport']))
    print()

    lb = cfg.get("load_balancer", {})
    lb_str = green("YES — Exoscale NLB") if lb.get("enabled") else yellow("No (NodePort only)")
    row("Load Balancer:", lb_str)

    ingress = cfg.get("ingress", {})
    if ingress.get("enabled"):
        tls_info = f" + TLS ({ingress.get('domain','?')})" if ingress.get("tls") else " (no TLS)"
        row("Ingress:", green(f"YES — {ingress.get('provider','nginx')}{tls_info}"))
    else:
        row("Ingress:", yellow("Disabled"))

    db = cfg.get("database", {})
    if db.get("enabled"):
        row("Database:", green(f"YES — {db.get('type','?')} v{db.get('version','?')} ({db.get('deployment','?')})"))
    else:
        row("Database:", yellow("None"))

    asc = cfg.get("autoscaling", {})
    if asc.get("enabled"):
        row("HPA:", green((f"YES — {asc['min_replicas']}->{asc['max_replicas']} replicas "
                           f"(CPU {asc['cpu_target_percent']}% / Mem {asc['memory_target_percent']}%)")))
    else:
        row("HPA:", yellow("Disabled (fixed replicas)"))

    pdb = cfg.get("pod_disruption_budget", {})
    if pdb.get("enabled"):
        row("PodDisruptionBudget:", green(f"YES — min_available={pdb['min_available']}"))

    res = cfg.get("resources", {})
    req = res.get("requests", {})
    lim = res.get("limits", {})
    row("Resources:", (f"req {req.get('cpu','?')}/{req.get('memory','?')}  "
                       f"lim {lim.get('cpu','?')}/{lim.get('memory','?')}"))
    print()
    print(f"  {bold('Estimated cost:')} {yellow(estimate_cost(cfg))}")
    print()
    print(f"  {yellow(bold('WARNING: This will CREATE real Exoscale cloud resources and INCUR COSTS.'))}")
    _disp_slug = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', cfg['project_name'].lower())).strip('-')
    print(f"  {dim('All resources will be prefixed with:')} {bold(_disp_slug)}-*  (slugified)")


def write_config(cfg: dict, path: "Path | None" = None) -> Path:
    """Write configuration dict to config.yaml with header comments."""
    if path is None:
        path = Path(__file__).parent / "config.yaml"
    sep = "=" * 61
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    hlines = [
        f"# {sep}",
        "# Exoscale Deploy Kit - Configuration",
        f"# Generated by wizard.py on {ts}",
        f"# {sep}",
        "# Edit values below OR re-run: python3 wizard.py",
        "# Credentials go in .env (NEVER commit .env to git)",
        "# Deploy:   python3 deploy_pipeline.py --auto",
        "# Teardown: python3 teardown.py --force",
        f"# {sep}",
        "",
    ]
    with open(path, "w") as f:
        f.write(chr(10).join(hlines))

        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return path


def main():
    """Entry point for standalone wizard run."""
    try:
        existing = load_existing()
        cfg = run_wizard(existing)
        print_summary(cfg)
        print()
        proceed = prompt_bool("Save this configuration to config.yaml?", True)
        if not proceed:
            print(f"\n  {yellow('Configuration NOT saved. No changes made.')}")
            sys.exit(0)

        path = write_config(cfg)
        print(f"\n  {green('Configuration saved to:')} {bold(str(path))}")
        print()
        deploy_now = prompt_bool("Deploy now? (python3 deploy_pipeline.py --auto)", False)
        if deploy_now:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "deploy_pipeline.py"), "--auto"],
                cwd=str(Path(__file__).parent)
            )
            sys.exit(result.returncode)
        else:
            print(f"\n  {dim('When ready:')} {bold('python3 deploy_pipeline.py --auto')}")
            print(f"  {dim('Re-run wizard:')} {bold('python3 wizard.py')}")

    except KeyboardInterrupt:
        print(f"\n\n  {yellow('Wizard aborted. No changes made.')}")
        sys.exit(0)


if __name__ == "__main__":
    main()
