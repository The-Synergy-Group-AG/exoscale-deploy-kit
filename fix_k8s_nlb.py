#!/usr/bin/env python3
"""
Fix K8s CCM NLB port mismatch (ISSUE-021 — Plan 123 Phase 5)
=============================================================
Exoscale K8s Cloud Controller Manager creates the nginx-ingress NLB with wrong
NodePort targets. Both port-80 and port-443 listeners target the FIRST NodePort
assigned (e.g. 30615) instead of the actual nginx-ingress NodePorts.

Result: cert-manager HTTP-01 challenges ALWAYS FAIL because Let's Encrypt cannot
reach the ACME token URL (port 80 routes to the wrong NodePort → connection refused).

This script:
  1. Discovers the nginx-ingress Service NodePorts dynamically from kubectl
  2. Finds the K8s-created NLB by its external IP (does NOT use hardcoded NLB name)
  3. Updates each NLB service (port 80, port 443) with the correct NodePort

Usage:
  # Auto-discover (uses KUBECONFIG env or most recent kubeconfig in outputs/)
  python3 fix_k8s_nlb.py

  # Explicit kubeconfig
  python3 fix_k8s_nlb.py --kubeconfig outputs/20260304_085857/kubeconfig.yaml

  # Dry run — show what would be changed
  python3 fix_k8s_nlb.py --dry-run

Note: deploy_pipeline.py Stage 5c-1b runs this logic automatically. Use this
script as a manual fallback if Stage 5c-1b fails or for debugging.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Load .env credentials ─────────────────────────────────────────────────────
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _raw in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _raw.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


def log(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
def ok(msg):   print(f"[{datetime.now().strftime('%H:%M:%S')}] OK  {msg}")
def warn(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] WARN {msg}")
def fail(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL {msg}", file=sys.stderr)


def get_latest_kubeconfig() -> str | None:
    """Find the most recent kubeconfig from deployment outputs."""
    outputs_dir = Path(__file__).parent / "outputs"
    if not outputs_dir.exists():
        return None
    dirs = sorted([d for d in outputs_dir.iterdir() if d.is_dir()], reverse=True)
    for d in dirs:
        kc = d / "kubeconfig.yaml"
        if kc.exists():
            return str(kc)
    return None


def get_nginx_nodeports(kubeconfig: str) -> tuple[int | None, int | None]:
    """Return (http_nodeport, https_nodeport) for ingress-nginx-controller service."""
    env = {**os.environ, "KUBECONFIG": kubeconfig}

    http_np = subprocess.run(
        ["kubectl", "--insecure-skip-tls-verify",
         "-n", "ingress-nginx", "get", "svc", "ingress-nginx-controller",
         "-o", "jsonpath={.spec.ports[?(@.port==80)].nodePort}"],
        env=env, capture_output=True, text=True,
    ).stdout.strip()

    https_np = subprocess.run(
        ["kubectl", "--insecure-skip-tls-verify",
         "-n", "ingress-nginx", "get", "svc", "ingress-nginx-controller",
         "-o", "jsonpath={.spec.ports[?(@.port==443)].nodePort}"],
        env=env, capture_output=True, text=True,
    ).stdout.strip()

    http_val  = int(http_np)  if http_np  else None
    https_val = int(https_np) if https_np else None
    return http_val, https_val


def get_ingress_lb_ip(kubeconfig: str) -> str | None:
    """Return the external IP of the ingress-nginx-controller LoadBalancer service."""
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    ip = subprocess.run(
        ["kubectl", "--insecure-skip-tls-verify",
         "-n", "ingress-nginx", "get", "svc", "ingress-nginx-controller",
         "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}"],
        env=env, capture_output=True, text=True,
    ).stdout.strip()
    return ip if ip and ip != "<pending>" else None


def main():
    parser = argparse.ArgumentParser(
        description="Fix K8s CCM NLB port mismatch for nginx-ingress (ISSUE-021)"
    )
    parser.add_argument(
        "--kubeconfig", default=None,
        help="Path to kubeconfig (default: auto-discover from outputs/)"
    )
    parser.add_argument(
        "--zone", default=None,
        help="Exoscale zone (default: from .env EXO_ZONE or ch-dk-2)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be changed without modifying anything"
    )
    args = parser.parse_args()

    zone = args.zone or os.environ.get("EXO_ZONE", "ch-dk-2")
    api_key    = os.environ.get("EXO_API_KEY")
    api_secret = os.environ.get("EXO_API_SECRET")

    if not api_key or not api_secret:
        fail("EXO_API_KEY and EXO_API_SECRET must be set in .env or environment")
        sys.exit(1)

    # ── Kubeconfig ─────────────────────────────────────────────────────────────
    kubeconfig = args.kubeconfig or get_latest_kubeconfig()
    if not kubeconfig:
        fail("No kubeconfig found. Use --kubeconfig or deploy first.")
        sys.exit(1)
    log(f"Using kubeconfig: {kubeconfig}")

    # ── Get actual nginx-ingress NodePorts ─────────────────────────────────────
    log("Querying nginx-ingress NodePorts from K8s...")
    http_np, https_np = get_nginx_nodeports(kubeconfig)

    if not http_np or not https_np:
        fail("Cannot get nginx-ingress NodePorts — is nginx-ingress deployed?")
        fail("  Check: kubectl -n ingress-nginx get svc ingress-nginx-controller")
        sys.exit(1)

    ok(f"nginx-ingress NodePorts: HTTP={http_np}, HTTPS={https_np}")

    # ── Get nginx-ingress LB external IP ──────────────────────────────────────
    log("Querying nginx-ingress external IP...")
    ingress_lb_ip = get_ingress_lb_ip(kubeconfig)

    if not ingress_lb_ip:
        fail("Cannot get nginx-ingress LB external IP — is it still pending?")
        fail("  Check: kubectl -n ingress-nginx get svc ingress-nginx-controller")
        sys.exit(1)

    ok(f"nginx-ingress LB IP: {ingress_lb_ip}")

    # ── Find K8s NLB by IP via Exoscale API ───────────────────────────────────
    log("Connecting to Exoscale API...")
    try:
        from exoscale.api.v2 import Client
        c = Client(api_key, api_secret, zone=zone)
    except ImportError:
        fail("exoscale package not installed: pip install exoscale")
        sys.exit(1)

    log(f"Listing NLBs in zone {zone}...")
    all_nlbs = c.list_load_balancers().get("load-balancers", [])
    k8s_nlb  = next((n for n in all_nlbs if n.get("ip") == ingress_lb_ip), None)

    if not k8s_nlb:
        fail(f"No NLB found with IP {ingress_lb_ip}")
        log(f"Available NLBs: {[(n.get('name'), n.get('ip')) for n in all_nlbs]}")
        sys.exit(1)

    nlb_id   = k8s_nlb["id"]
    nlb_name = k8s_nlb.get("name", nlb_id[:8])
    ok(f"Found K8s NLB: {nlb_name} ({nlb_id[:8]}...) IP={ingress_lb_ip}")

    # ── Inspect current NLB service port assignments ──────────────────────────
    detail   = c.get_load_balancer(id=nlb_id)
    services = detail.get("services", [])

    if not services:
        warn("NLB has no services yet — nothing to fix")
        sys.exit(0)

    log(f"NLB services: {[(s.get('port'), s.get('target-port'), s.get('healthcheck', {}).get('port')) for s in services]}")

    port_map = {80: http_np, 443: https_np}
    fixes_needed = []
    fixes_ok     = []

    for svc in services:
        port    = svc.get("port")
        svc_id  = svc.get("id")
        cur_hc  = svc.get("healthcheck", {}).get("port")
        target  = port_map.get(port)

        if target is None:
            continue

        if cur_hc == target:
            ok(f"port {port}: already -> {target} (no change needed)")
            fixes_ok.append(port)
        else:
            log(f"port {port}: WRONG target {cur_hc} -> needs {target}")
            fixes_needed.append((port, svc_id, cur_hc, target))

    if not fixes_needed:
        ok("All NLB port assignments are correct — no fix needed")
        sys.exit(0)

    if args.dry_run:
        log("\n=== DRY RUN — would apply these fixes ===")
        for port, svc_id, cur_hc, target in fixes_needed:
            log(f"  NLB port {port}: target-port {cur_hc} -> {target}")
        log("Re-run without --dry-run to apply")
        sys.exit(0)

    # ── Apply fixes ────────────────────────────────────────────────────────────
    log("\n=== Applying NLB port fixes ===")
    errors = []
    for port, svc_id, cur_hc, target in fixes_needed:
        log(f"Fixing port {port}: {cur_hc} -> {target}...")
        try:
            c.update_load_balancer_service(
                id=nlb_id, service_id=svc_id,
                protocol="tcp",
                target_port=target,
                healthcheck={
                    "port": target, "mode": "tcp",
                    "interval": 10, "timeout": 5, "retries": 1
                },
            )
            ok(f"port {port}: fixed -> {target}")
        except Exception as e:
            fail(f"port {port} fix failed: {e}")
            errors.append((port, str(e)))

    # ── Verify ─────────────────────────────────────────────────────────────────
    log("\n=== Verifying ===")
    detail2   = c.get_load_balancer(id=nlb_id)
    services2 = detail2.get("services", [])
    all_ok = True
    for svc in services2:
        port   = svc.get("port")
        cur_hc = svc.get("healthcheck", {}).get("port")
        target = port_map.get(port)
        if target is None:
            continue
        if cur_hc == target:
            ok(f"port {port}: -> {target} VERIFIED")
        else:
            fail(f"port {port}: STILL WRONG ({cur_hc} != {target})")
            all_ok = False

    if errors:
        fail(f"{len(errors)} fix(es) failed: {errors}")
        sys.exit(1)
    elif all_ok:
        ok(f"\nAll NLB port assignments fixed: port 80->{http_np}, port 443->{https_np}")
        ok("cert-manager HTTP-01 challenges should now succeed")
        ok("Monitor: kubectl -n <namespace> get certificate")
    else:
        fail("Some ports still incorrect after fix attempt")
        sys.exit(1)


if __name__ == "__main__":
    main()
