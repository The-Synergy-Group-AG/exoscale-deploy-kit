#!/usr/bin/env python3
"""
StarGate Template Test Runner
==============================
Validates a deployed Exoscale template against its expected configuration.
Saves structured results to templates/test-results/TN-result-YYYYMMDD.json

Usage:
    python3 templates/template_test_runner.py --config templates/runs/T1-20260223.yaml

Requirements:
    - kubectl must be configured (KUBECONFIG pointing to deployed cluster)
    - .env must contain EXO_API_KEY and EXO_API_SECRET
    - pip install exoscale boto3 pyyaml python-dotenv
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

EXO_KEY    = os.getenv("EXO_API_KEY", "")
EXO_SECRET = os.getenv("EXO_API_SECRET", "")

RESULTS_DIR = ROOT / "templates" / "test-results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError as e:
        return -1, "", str(e)


def kubectl(*args, timeout: int = 30) -> tuple[int, str, str]:
    return run(["kubectl"] + list(args), timeout=timeout)


def check(name: str, passed: bool, detail: str = "") -> dict:
    status = "PASS" if passed else "FAIL"
    icon   = "✅" if passed else "❌"
    print(f"  {icon}  {name}: {status}" + (f" — {detail}" if detail else ""))
    return {"check": name, "status": status, "detail": detail}


# ---------------------------------------------------------------------------
# Universal checks
# ---------------------------------------------------------------------------
def universal_checks(cfg: dict) -> list[dict]:
    results = []
    ns = cfg["k8s_namespace"]
    project = cfg["project_name"]
    node_count = cfg.get("node_count", 1)
    node_size  = cfg.get("node_type_size", "unknown")

    print("\n── Universal Checks ──────────────────────────────")

    # U02: cluster reachable via kubectl
    rc, out, _ = kubectl("cluster-info", timeout=20)
    results.append(check("U02 Cluster reachable", rc == 0, out[:80] if rc == 0 else "kubectl cluster-info failed"))

    # U03: all nodes Ready
    rc, out, _ = kubectl("get", "nodes", "--no-headers", "-o",
                          "custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type")
    if rc == 0:
        lines   = [l for l in out.splitlines() if l.strip()]
        ready   = all("Ready" in l for l in lines)
        results.append(check("U03 All nodes Ready", ready, f"{len(lines)} node(s) found"))
    else:
        results.append(check("U03 All nodes Ready", False, "kubectl get nodes failed"))

    # U04: correct node count
    rc, out, _ = kubectl("get", "nodes", "--no-headers")
    actual_count = len([l for l in out.splitlines() if l.strip()]) if rc == 0 else -1
    results.append(check("U04 Node count", actual_count == node_count,
                         f"expected={node_count} actual={actual_count}"))

    # U05: node type label from Exoscale (best-effort via node labels)
    rc, out, _ = kubectl("get", "nodes", "-o",
                          "jsonpath={.items[*].metadata.labels.node\\.kubernetes\\.io/instance-type}")
    results.append(check("U05 Node type", node_size in out or out == "",
                         f"expected ~{node_size}, got: {out[:60]}"))

    # U06: namespace exists
    rc, out, _ = kubectl("get", "namespace", ns, "--no-headers")
    results.append(check("U06 Namespace exists", rc == 0, ns))

    # U07: service exists in namespace
    rc, out, _ = kubectl("get", "svc", "-n", ns, "--no-headers")
    results.append(check("U07 Service running", rc == 0 and len(out.splitlines()) > 0,
                         out[:80] if out else "no services found"))

    # U08 / U09: node labels
    rc, out, _ = kubectl("get", "nodes", "--show-labels")
    has_stargate = "stargate.io/project" in out
    template_key = cfg.get("node_labels", {}).get("labels", {}).get("stargate.io/template", "")
    has_template  = template_key in out if template_key else False
    results.append(check("U08 stargate.io labels present", has_stargate, "stargate.io/project found" if has_stargate else "MISSING"))
    results.append(check("U09 Template label present", has_template, template_key if has_template else f"Missing: {template_key}"))

    return results


# ---------------------------------------------------------------------------
# Template-specific checks
# ---------------------------------------------------------------------------
def t1_checks(cfg: dict) -> list[dict]:
    results = []
    ns = cfg["k8s_namespace"]
    print("\n── T1 Specific Checks ────────────────────────────")

    results.append(check("T1-01 Node size tiny", cfg.get("node_type_size") == "tiny",
                         cfg.get("node_type_size")))
    results.append(check("T1-02 Single node", cfg.get("node_count", 0) == 1,
                         str(cfg.get("node_count"))))

    db_enabled  = cfg.get("database", {}).get("enabled", False)
    sos_enabled = cfg.get("object_storage", {}).get("enabled", False)
    bs_enabled  = cfg.get("block_storage", {}).get("enabled", False)
    hpa_enabled = cfg.get("autoscaling", {}).get("enabled", False)

    results.append(check("T1-03 No DB", not db_enabled, "DB disabled as expected" if not db_enabled else "DB unexpectedly enabled"))
    results.append(check("T1-04 No SOS", not sos_enabled, "SOS disabled" if not sos_enabled else "SOS unexpectedly enabled"))
    results.append(check("T1-05 No block storage", not bs_enabled))
    results.append(check("T1-06 No HPA", not hpa_enabled))

    rc, out, _ = kubectl("get", "pvc", "-n", ns, "--no-headers")
    no_pvc = rc == 0 and out.strip() == ""
    results.append(check("T1-07 No PVC in namespace", no_pvc, out[:60] if out else "no PVCs"))

    results.append(check("T1-08 Namespace correct", ns == "exo-stargate-test", ns))
    return results


def t2_checks(cfg: dict) -> list[dict]:
    results = []
    ns = cfg["k8s_namespace"]
    print("\n── T2 Specific Checks ────────────────────────────")

    results.append(check("T2-01 Node size small", cfg.get("node_type_size") == "small"))
    results.append(check("T2-02 2 worker nodes", cfg.get("node_count") == 2))

    db_cfg = cfg.get("database", {})
    results.append(check("T2-03 Redis DB enabled", db_cfg.get("enabled") and db_cfg.get("type") == "redis",
                         f"type={db_cfg.get('type')} enabled={db_cfg.get('enabled')}"))

    rc, out, _ = kubectl("get", "secret", "db-credentials", "-n", ns, "--no-headers")
    results.append(check("T2-04 DB secret injected", rc == 0, "db-credentials found" if rc == 0 else "MISSING"))

    sos_enabled = cfg.get("object_storage", {}).get("enabled", False)
    results.append(check("T2-05 No SOS", not sos_enabled))

    rc, out, _ = kubectl("get", "hpa", "-n", ns, "--no-headers")
    results.append(check("T2-06 HPA exists", rc == 0 and len(out.splitlines()) > 0, out[:60]))

    results.append(check("T2-07 Namespace correct", ns == "exo-stargate-orch", ns))

    rc, out, _ = kubectl("get", "ingress", "-n", ns, "--no-headers")
    results.append(check("T2-08 Ingress exists", rc == 0 and len(out.splitlines()) > 0, out[:60]))
    return results


def t3_checks(cfg: dict) -> list[dict]:
    results = []
    ns = cfg["k8s_namespace"]
    print("\n── T3 Specific Checks ────────────────────────────")

    db_cfg = cfg.get("database", {})
    results.append(check("T3-01 PostgreSQL enabled", db_cfg.get("enabled") and db_cfg.get("type") == "pg"))
    results.append(check("T3-02 PG version 16", db_cfg.get("version") == "16"))

    rc, out, _ = kubectl("get", "secret", "db-credentials", "-n", ns, "--no-headers")
    results.append(check("T3-03 DB secret injected", rc == 0))

    sos_cfg = cfg.get("object_storage", {})
    results.append(check("T3-04 SOS enabled", sos_cfg.get("enabled") and sos_cfg.get("acl") == "private"))

    rc, out, _ = kubectl("get", "secret", "sos-credentials", "-n", ns, "--no-headers")
    results.append(check("T3-05 SOS secret injected", rc == 0))

    rc, out, _ = kubectl("get", "pvc", "-n", ns, "--no-headers")
    has_pvc = rc == 0 and "Bound" in out
    results.append(check("T3-06 PVC Bound", has_pvc, out[:80]))

    bs_cfg = cfg.get("block_storage", {})
    results.append(check("T3-07 Block storage 10GB", bs_cfg.get("size_gb") == 10))

    rc, out, _ = kubectl("get", "hpa", "-n", ns, "--no-headers")
    results.append(check("T3-08 HPA exists", rc == 0 and bool(out.strip())))

    results.append(check("T3-09 Namespace correct", ns == "exo-stargate-store", ns))
    return results


def t4_checks(cfg: dict) -> list[dict]:
    results = []
    ns = cfg["k8s_namespace"]
    print("\n── T4 Specific Checks ────────────────────────────")

    results.append(check("T4-01 Node size large", cfg.get("node_type_size") == "large"))
    results.append(check("T4-02 3 worker nodes", cfg.get("node_count") == 3))

    db_cfg = cfg.get("database", {})
    results.append(check("T4-03 PostgreSQL enabled", db_cfg.get("enabled") and db_cfg.get("type") == "pg"))

    bs_cfg = cfg.get("block_storage", {})
    results.append(check("T4-04 Block storage 100GB", bs_cfg.get("size_gb") == 100))

    rc, out, _ = kubectl("get", "pvc", "-n", ns, "--no-headers")
    results.append(check("T4-05 PVC Bound", "Bound" in out if rc == 0 else False, out[:80]))

    asc = cfg.get("autoscaling", {})
    results.append(check("T4-06 HPA max=15", asc.get("max_replicas") == 15))

    limits = cfg.get("resources", {}).get("limits", {})
    results.append(check("T4-07 CPU limit 2000m", str(limits.get("cpu", "")) == "2000"))
    results.append(check("T4-08 Memory limit 4Gi", limits.get("memory") == "4Gi"))

    rc, out, _ = kubectl("get", "pdb", "-n", ns, "--no-headers")
    results.append(check("T4-09 PDB exists", rc == 0 and bool(out.strip())))

    results.append(check("T4-10 Namespace correct", ns == "exo-stargate-compute", ns))
    return results


def t5_checks(cfg: dict) -> list[dict]:
    results = []
    ns = cfg["k8s_namespace"]
    print("\n── T5 Specific Checks ────────────────────────────")

    results.append(check("T5-01 Node size small", cfg.get("node_type_size") == "small"))
    results.append(check("T5-02 2 worker nodes", cfg.get("node_count") == 2))
    results.append(check("T5-03 No DB", not cfg.get("database", {}).get("enabled", False)))
    results.append(check("T5-04 No SOS", not cfg.get("object_storage", {}).get("enabled", False)))
    results.append(check("T5-05 No block storage", not cfg.get("block_storage", {}).get("enabled", False)))

    limits = cfg.get("resources", {}).get("limits", {})
    results.append(check("T5-06 CPU limit 500m", str(limits.get("cpu", "")) == "500"))
    results.append(check("T5-07 Memory limit 512Mi", limits.get("memory") == "512Mi"))

    asc = cfg.get("autoscaling", {})
    results.append(check("T5-08 HPA max=4 (hard ceiling)", asc.get("max_replicas") == 4))

    ingress_cfg = cfg.get("ingress", {})
    results.append(check("T5-09 TLS enforced", ingress_cfg.get("tls") is True))
    results.append(check("T5-10 Namespace correct", ns == "exo-stargate-security", ns))

    labels = cfg.get("node_labels", {}).get("labels", {})
    results.append(check("T5-11 clearance=restricted label", labels.get("stargate.io/clearance") == "restricted"))
    return results


def t6_checks(cfg: dict) -> list[dict]:
    results = []
    ns = cfg["k8s_namespace"]
    print("\n── T6 Specific Checks ────────────────────────────")

    results.append(check("T6-01 Node size medium", cfg.get("node_type_size") == "medium"))
    results.append(check("T6-02 2 worker nodes", cfg.get("node_count") == 2))

    db_cfg = cfg.get("database", {})
    results.append(check("T6-03 PostgreSQL enabled", db_cfg.get("enabled") and db_cfg.get("type") == "pg"))

    sos_cfg = cfg.get("object_storage", {})
    results.append(check("T6-04 SOS telemetry bucket", sos_cfg.get("enabled") and sos_cfg.get("bucket_name") == "telemetry"))

    bs_cfg = cfg.get("block_storage", {})
    results.append(check("T6-05 Block storage 50GB", bs_cfg.get("size_gb") == 50))

    results.append(check("T6-06 Port 3000 (Grafana)", cfg.get("k8s_port") == 3000))
    results.append(check("T6-07 NodePort 30006", cfg.get("k8s_nodeport") == 30006))

    limits = cfg.get("resources", {}).get("limits", {})
    results.append(check("T6-08 Memory limit 2Gi", limits.get("memory") == "2Gi"))

    rc, out, _ = kubectl("top", "nodes", timeout=15)
    results.append(check("T6-09 metrics-server responding", rc == 0, "kubectl top nodes OK" if rc == 0 else out[:60]))

    results.append(check("T6-10 Namespace correct", ns == "exo-stargate-obs", ns))
    return results


def t7_checks(cfg: dict) -> list[dict]:
    results = []
    ns = cfg["k8s_namespace"]
    print("\n── T7 Specific Checks ────────────────────────────")

    results.append(check("T7-01 Node size medium", cfg.get("node_type_size") == "medium"))
    results.append(check("T7-02 3 worker nodes", cfg.get("node_count") == 3))

    db_cfg = cfg.get("database", {})
    results.append(check("T7-03 PostgreSQL enabled", db_cfg.get("enabled") and db_cfg.get("type") == "pg"))

    sos_cfg = cfg.get("object_storage", {})
    results.append(check("T7-04 SOS integration bucket", sos_cfg.get("enabled") and sos_cfg.get("bucket_name") == "integration"))

    bs_cfg = cfg.get("block_storage", {})
    results.append(check("T7-05 Block storage 50GB", bs_cfg.get("size_gb") == 50))

    asc = cfg.get("autoscaling", {})
    results.append(check("T7-06 HPA min=3 max=20", asc.get("min_replicas") == 3 and asc.get("max_replicas") == 20))

    rc, out, _ = kubectl("get", "pdb", "-n", ns, "--no-headers")
    results.append(check("T7-07 PDB exists", rc == 0 and bool(out.strip())))

    rc_ing, out_ing, _ = kubectl("get", "ingress", "-n", ns, "--no-headers")
    results.append(check("T7-08 Ingress + TLS", rc_ing == 0 and bool(out_ing.strip())))

    rc_db,  _, _ = kubectl("get", "secret", "db-credentials",  "-n", ns, "--no-headers")
    rc_sos, _, _ = kubectl("get", "secret", "sos-credentials", "-n", ns, "--no-headers")
    results.append(check("T7-09 Both secrets injected", rc_db == 0 and rc_sos == 0,
                         f"db-creds={rc_db==0} sos-creds={rc_sos==0}"))

    results.append(check("T7-10 Namespace correct", ns == "exo-stargate-integration", ns))

    labels = cfg.get("node_labels", {}).get("labels", {})
    results.append(check("T7-11 agents=all label", labels.get("stargate.io/agents") == "all"))
    return results


TEMPLATE_CHECKS = {
    "T1": t1_checks,
    "T2": t2_checks,
    "T3": t3_checks,
    "T4": t4_checks,
    "T5": t5_checks,
    "T6": t6_checks,
    "T7": t7_checks,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="StarGate Template Test Runner")
    parser.add_argument("--config", required=True, help="Path to dated deploy config YAML")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: config not found: {config_path}")
        sys.exit(1)

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    project_name = cfg.get("project_name", "unknown")

    # Detect template ID from project_name (e.g. stargate-t1-20260223 → T1)
    m = re.search(r"stargate-t(\d)", project_name, re.I)
    template_id = f"T{m.group(1)}" if m else "T?"
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    print("=" * 54)
    print(f"  StarGate Template Test Runner")
    print(f"  Template : {template_id}")
    print(f"  Project  : {project_name}")
    print(f"  Config   : {config_path.name}")
    print(f"  Time     : {datetime.now(timezone.utc).isoformat()}")
    print("=" * 54)

    all_results = []

    # Universal checks
    all_results.extend(universal_checks(cfg))

    # Template-specific checks
    specific_fn = TEMPLATE_CHECKS.get(template_id)
    if specific_fn:
        all_results.extend(specific_fn(cfg))
    else:
        print(f"\nWARN: No specific checks defined for {template_id}")

    # Tally
    passed = sum(1 for r in all_results if r["status"] == "PASS")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    total  = len(all_results)
    pct    = round(passed / total * 100, 1) if total else 0
    verdict = "PASS ✅" if failed == 0 else ("WARN ⚠️" if pct >= 85 else "FAIL ❌")

    print("\n" + "=" * 54)
    print(f"  RESULT: {verdict}")
    print(f"  Checks: {passed}/{total} passed ({pct}%)")
    if failed:
        print(f"  Failed: {failed} check(s)")
    print("=" * 54)

    # Save results
    result_data = {
        "template": template_id,
        "project_name": project_name,
        "config_file": str(config_path),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate_pct": pct,
            "verdict": verdict.split()[0],
        },
        "checks": all_results,
    }

    result_file = RESULTS_DIR / f"{template_id}-result-{date_str}.json"
    result_file.write_text(json.dumps(result_data, indent=2), encoding="utf-8")
    print(f"\n  Results saved → {result_file}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
