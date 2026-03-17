#!/usr/bin/env python3
"""
service_health_check.py — Plan 125 Post-Deployment Service Health Sweep
=======================================================================
Checks the /health endpoint of every service pod in the namespace using
kubectl port-forward (one at a time) OR by reading ClusterIP + exec.

Fast mode: uses kubectl exec to curl /health inside each pod (no port-forward needed).
Output:  HEALTHY / UNHEALTHY / TIMEOUT / ERROR per service, JSON report.

Usage:
    python3 service_health_check.py \\
        --kubeconfig outputs/20260305_125732/kubeconfig.yaml \\
        --namespace exo-jtp-prod

    python3 service_health_check.py \\
        --kubeconfig outputs/20260305_125732/kubeconfig.yaml \\
        --namespace exo-jtp-prod \\
        --output-json results/health_20260305.json \\
        --workers 20

Plan: 125-True-Microservices-Deployment
Phase: 2 — Post-Deployment Verification
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Status codes ─────────────────────────────────────────────────────────────
STATUS_HEALTHY   = "HEALTHY"
STATUS_UNHEALTHY = "UNHEALTHY"   # HTTP non-200
STATUS_TIMEOUT   = "TIMEOUT"     # curl timeout
STATUS_ERROR     = "ERROR"       # pod not running / exec failed
STATUS_SKIP      = "SKIP"        # pod not in Running state

# ── Result record ─────────────────────────────────────────────────────────────
class CheckResult:
    def __init__(self, service: str, pod: str, status: str,
                 http_code: Optional[int], latency_ms: Optional[float],
                 detail: str = ""):
        self.service    = service
        self.pod        = pod
        self.status     = status
        self.http_code  = http_code
        self.latency_ms = latency_ms
        self.detail     = detail

    def to_dict(self) -> dict:
        return {
            "service":    self.service,
            "pod":        self.pod,
            "status":     self.status,
            "http_code":  self.http_code,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms else None,
            "detail":     self.detail,
        }


def get_running_pods(kubeconfig: str, namespace: str) -> list[dict]:
    """Return list of {name, phase, service_name} for all pods in namespace."""
    cmd = [
        "kubectl", "get", "pods",
        "-n", namespace,
        "--kubeconfig", kubeconfig,
        "-o", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"kubectl get pods failed: {result.stderr.strip()}")

    items = json.loads(result.stdout).get("items", [])
    pods = []
    for item in items:
        name  = item["metadata"]["name"]
        phase = item.get("status", {}).get("phase", "Unknown")
        # SERVICE_NAME env var identifies the microservice
        envs = item.get("spec", {}).get("containers", [{}])[0].get("env", [])
        svc_name = next(
            (e["value"] for e in envs if e.get("name") == "SERVICE_NAME"),
            name  # fallback: use pod name
        )
        # Skip gateway and system pods
        if any(skip in name for skip in ["docker-jtp", "nginx", "cert-manager",
                                          "cm-acme", "coredns", "calico",
                                          # L72: AI backends use native ports, not 8000
                                          "gpt4-orchestrator", "claude-integration",
                                          "embeddings-engine", "vector-store",
                                          "job-matcher", "cv-processor",
                                          "career-navigator", "skill-bridge",
                                          "memory-system", "learning-system",
                                          "pattern-recognition", "decision-making"]):
            continue
        pods.append({"name": name, "phase": phase, "service_name": svc_name})
    return pods


def check_pod_health(kubeconfig: str, namespace: str,
                     pod: dict, timeout: int = 5) -> CheckResult:
    """Check /health endpoint of a single pod via kubectl exec + curl."""
    pod_name = pod["name"]
    svc_name = pod["service_name"]

    if pod["phase"] != "Running":
        return CheckResult(svc_name, pod_name, STATUS_SKIP, None, None,
                           f"pod phase={pod['phase']}")

    # Use kubectl exec to curl /health inside the pod
    cmd = [
        "kubectl", "exec",
        "-n", namespace,
        "--kubeconfig", kubeconfig,
        pod_name,
        "--",
        "curl", "-sf",
        "--max-time", str(timeout),
        "-o", "/dev/null",
        "-w", "%{http_code}:%{time_total}",
        "http://localhost:8000/health",
    ]

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout + 5  # outer timeout slightly longer
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        if result.returncode != 0:
            # Check if it's a timeout vs exec failure
            stderr = result.stderr.strip()
            if "timed out" in stderr.lower() or "timeout" in stderr.lower():
                return CheckResult(svc_name, pod_name, STATUS_TIMEOUT, None, elapsed_ms,
                                   f"curl timeout after {timeout}s")
            return CheckResult(svc_name, pod_name, STATUS_ERROR, None, elapsed_ms,
                               f"exec failed: {stderr[:80]}")

        # Parse curl output: "200:0.123456"
        output = result.stdout.strip()
        if ":" in output:
            parts = output.split(":", 1)
            http_code = int(parts[0]) if parts[0].isdigit() else None
            latency_ms = float(parts[1]) * 1000 if len(parts) > 1 else elapsed_ms
        else:
            http_code = int(output) if output.isdigit() else None
            latency_ms = elapsed_ms

        if http_code == 200:
            return CheckResult(svc_name, pod_name, STATUS_HEALTHY, http_code, latency_ms)
        else:
            return CheckResult(svc_name, pod_name, STATUS_UNHEALTHY, http_code, latency_ms,
                               f"HTTP {http_code}")

    except subprocess.TimeoutExpired:
        elapsed_ms = (time.monotonic() - t0) * 1000
        return CheckResult(svc_name, pod_name, STATUS_TIMEOUT, None, elapsed_ms,
                           f"kubectl exec timeout after {timeout + 5}s")
    except Exception as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        return CheckResult(svc_name, pod_name, STATUS_ERROR, None, elapsed_ms,
                           f"exception: {exc}")


def run_health_sweep(kubeconfig: str, namespace: str, workers: int = 10,
                     timeout: int = 5) -> list[CheckResult]:
    """Run health checks on all service pods in parallel."""
    print(f"\n[health-check] Fetching pods from namespace: {namespace}")
    pods = get_running_pods(kubeconfig, namespace)
    print(f"[health-check] Found {len(pods)} service pods (excl. gateway/system)")

    results: list[CheckResult] = []
    total = len(pods)
    done  = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(check_pod_health, kubeconfig, namespace, pod, timeout): pod
            for pod in pods
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done += 1
            icon = "✅" if result.status == STATUS_HEALTHY else (
                   "⏭️" if result.status == STATUS_SKIP else "❌")
            lat = f"{result.latency_ms:.0f}ms" if result.latency_ms else "-"
            print(f"  [{done:>3}/{total}] {icon} {result.service:<55} {result.status:<10} {lat}")

    return results


def print_summary(results: list[CheckResult]) -> None:
    """Print summary table and statistics."""
    counts = {STATUS_HEALTHY: 0, STATUS_UNHEALTHY: 0, STATUS_TIMEOUT: 0,
              STATUS_ERROR: 0, STATUS_SKIP: 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    total      = len(results)
    healthy    = counts[STATUS_HEALTHY]
    not_healthy = total - healthy - counts[STATUS_SKIP]

    print("\n" + "=" * 65)
    print(f"  SERVICE HEALTH SWEEP RESULTS")
    print("=" * 65)
    print(f"  Total checked:  {total}")
    print(f"  ✅ HEALTHY:     {healthy}")
    print(f"  ❌ UNHEALTHY:   {counts[STATUS_UNHEALTHY]}")
    print(f"  ⏱️  TIMEOUT:     {counts[STATUS_TIMEOUT]}")
    print(f"  🚫 ERROR:       {counts[STATUS_ERROR]}")
    print(f"  ⏭️  SKIP:        {counts[STATUS_SKIP]}")
    print(f"  Health rate:    {healthy}/{total - counts[STATUS_SKIP]} "
          f"({100*healthy/max(1, total-counts[STATUS_SKIP]):.1f}%)")
    print("=" * 65)

    if not_healthy > 0:
        print(f"\n  FAILED SERVICES ({not_healthy}):")
        for r in sorted(results, key=lambda x: x.status):
            if r.status not in (STATUS_HEALTHY, STATUS_SKIP):
                print(f"    ❌ {r.service:<55} {r.status}  {r.detail}")

    # Latency stats for healthy services
    latencies = [r.latency_ms for r in results
                 if r.status == STATUS_HEALTHY and r.latency_ms]
    if latencies:
        avg = sum(latencies) / len(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]
        print(f"\n  LATENCY (healthy services):")
        print(f"    avg={avg:.0f}ms  p95={p95:.0f}ms  p99={p99:.0f}ms")


def main() -> int:
    parser = argparse.ArgumentParser(description="JTP Service Health Check Sweep")
    parser.add_argument("--kubeconfig", required=True, help="Path to kubeconfig.yaml")
    parser.add_argument("--namespace", default="exo-jtp-prod")
    parser.add_argument("--workers", type=int, default=10,
                        help="Parallel workers (default: 10)")
    parser.add_argument("--timeout", type=int, default=5,
                        help="Curl timeout per probe (default: 5s)")
    parser.add_argument("--output-json", help="Save results to JSON file")
    parser.add_argument("--fail-threshold", type=float, default=0.80,
                        help="Minimum healthy fraction (default: 0.80)")
    args = parser.parse_args()

    ts = datetime.now().isoformat()
    print(f"[health-check] JTP Service Health Sweep — {ts}")
    print(f"[health-check] kubeconfig: {args.kubeconfig}")
    print(f"[health-check] namespace:  {args.namespace}")
    print(f"[health-check] workers:    {args.workers}")

    try:
        results = run_health_sweep(
            args.kubeconfig, args.namespace,
            workers=args.workers, timeout=args.timeout
        )
    except Exception as exc:
        print(f"[health-check] FATAL: {exc}", file=sys.stderr)
        return 1

    print_summary(results)

    # Save JSON report
    if args.output_json:
        report = {
            "timestamp": ts,
            "kubeconfig": args.kubeconfig,
            "namespace": args.namespace,
            "results": [r.to_dict() for r in results],
            "summary": {
                STATUS_HEALTHY:   sum(1 for r in results if r.status == STATUS_HEALTHY),
                STATUS_UNHEALTHY: sum(1 for r in results if r.status == STATUS_UNHEALTHY),
                STATUS_TIMEOUT:   sum(1 for r in results if r.status == STATUS_TIMEOUT),
                STATUS_ERROR:     sum(1 for r in results if r.status == STATUS_ERROR),
                STATUS_SKIP:      sum(1 for r in results if r.status == STATUS_SKIP),
                "total":          len(results),
            }
        }
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2))
        print(f"\n[health-check] Report saved: {out_path}")

    # Exit code: fail if below threshold
    running = [r for r in results if r.status != STATUS_SKIP]
    healthy = sum(1 for r in running if r.status == STATUS_HEALTHY)
    rate    = healthy / max(1, len(running))

    if rate < args.fail_threshold:
        print(f"\n[health-check] FAIL: {rate:.1%} healthy < {args.fail_threshold:.0%} threshold")
        return 1

    print(f"\n[health-check] PASS: {rate:.1%} healthy ≥ {args.fail_threshold:.0%} threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
