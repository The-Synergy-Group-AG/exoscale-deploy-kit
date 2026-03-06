#!/usr/bin/env python3
"""
run_service_tests.py — Plan 125 Post-Deployment Full Test Suite Runner
=======================================================================
After all services are live and healthy, runs the complete per-service
test suite (unit, integration, e2e, performance, security, user_stories)
via kubectl exec inside each pod.

Flow:
  1. Get all running service pods (excl. gateway/system)
  2. Parallel health sweep — confirm /health returns 200 (quick gate)
  3. For each pod, run: kubectl exec pod -- python -m pytest tests/ -q --tb=short
  4. Collect PASS / FAIL / ERROR / SKIP per service + per suite type
  5. Generate JSON report + print summary table
  6. Exit 1 if healthy fraction < --fail-threshold (default 0.80)

Usage:
    python3 run_service_tests.py \\
        --kubeconfig outputs/20260305_125732/kubeconfig.yaml \\
        --namespace exo-jtp-prod

    python3 run_service_tests.py \\
        --kubeconfig outputs/20260305_125732/kubeconfig.yaml \\
        --namespace exo-jtp-prod \\
        --workers 20 \\
        --output-json outputs/test_results_20260305_125732.json \\
        --suites unit integration e2e

Plan: 125-True-Microservices-Deployment
Phase: 2 — Post-Deployment Verification
Step: 2.7b
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

# ── Test suite directories (in execution order) ───────────────────────────────
ALL_SUITES = ["unit", "integration", "e2e", "performance", "security", "user_stories"]

# ── Status codes ─────────────────────────────────────────────────────────────
STATUS_PASS    = "PASS"
STATUS_FAIL    = "FAIL"
STATUS_ERROR   = "ERROR"     # kubectl exec failed / pod not running
STATUS_SKIP    = "SKIP"      # pod not Running
STATUS_NOTESTS = "NO_TESTS"  # tests/ dir empty or pytest not found


# ── Pod discovery ─────────────────────────────────────────────────────────────
def get_running_service_pods(kubeconfig: str, namespace: str) -> list[dict]:
    """Return list of {name, phase, service_name} for all running service pods."""
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
    skip_patterns = ["docker-jtp", "nginx", "cert-manager", "cm-acme",
                     "coredns", "calico", "kube-state", "kube-proxy"]

    for item in items:
        name  = item["metadata"]["name"]
        phase = item.get("status", {}).get("phase", "Unknown")

        if any(skip in name for skip in skip_patterns):
            continue

        # Extract SERVICE_NAME env var to get canonical service name
        envs = item.get("spec", {}).get("containers", [{}])[0].get("env", [])
        svc_name = next(
            (e["value"] for e in envs if e.get("name") == "SERVICE_NAME"),
            name
        )
        pods.append({"name": name, "phase": phase, "service_name": svc_name})

    return pods


# ── Health check gate ─────────────────────────────────────────────────────────
def quick_health_check(kubeconfig: str, namespace: str, pod_name: str,
                       timeout: int = 5) -> bool:
    """Returns True if /health returns HTTP 200, False otherwise."""
    cmd = [
        "kubectl", "exec", "-n", namespace,
        "--kubeconfig", kubeconfig,
        pod_name, "--",
        "curl", "-sf", "--max-time", str(timeout),
        "-o", "/dev/null", "-w", "%{http_code}",
        "http://localhost:8000/health",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        return result.returncode == 0 and result.stdout.strip() == "200"
    except Exception:
        return False


# ── Per-suite test runner ─────────────────────────────────────────────────────
def run_suite_in_pod(kubeconfig: str, namespace: str, pod_name: str,
                     suite: str, service_name: str = "",
                     timeout: int = 120) -> dict:
    """
    Run a specific test suite directory inside the pod.
    Returns: {suite, passed, failed, errors, skipped, duration_s, output}
    """
    t0 = time.monotonic()
    # Determine service directory inside the pod
    svc_dir = f"/app/services/{service_name}" if service_name else "/app"
    pytest_cmd = (
        f"cd {svc_dir} && "
        f"python -m pytest tests/{suite}/ "
        "-q --tb=short --no-header --color=no"
    )
    cmd = [
        "kubectl", "exec", "-n", namespace,
        "--kubeconfig", kubeconfig,
        pod_name, "--",
        "sh", "-c", pytest_cmd,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        duration = time.monotonic() - t0
        output = (result.stdout + result.stderr).strip()

        # Parse pytest summary line: "X passed, Y failed, Z error in Ns"
        passed = failed = errors = skipped = 0
        for line in output.splitlines():
            line_l = line.lower()
            if "passed" in line_l or "failed" in line_l or "error" in line_l:
                import re
                nums = re.findall(r"(\d+)\s+(passed|failed|error|skip)", line_l)
                for count, label in nums:
                    if "pass" in label:   passed  = int(count)
                    elif "fail" in label: failed  = int(count)
                    elif "error" in label: errors = int(count)
                    elif "skip" in label: skipped = int(count)

        # If pytest couldn't find the directory (no tests collected)
        if "no tests ran" in output.lower() or "no such file or directory" in output.lower():
            return {"suite": suite, "passed": 0, "failed": 0, "errors": 0,
                    "skipped": 0, "duration_s": duration,
                    "status": STATUS_NOTESTS, "output": output[:200]}

        status = STATUS_PASS if (result.returncode == 0 and failed == 0 and errors == 0) \
                 else STATUS_FAIL

        return {
            "suite": suite,
            "passed": passed, "failed": failed,
            "errors": errors, "skipped": skipped,
            "duration_s": round(duration, 1),
            "status": status,
            "output": output[-500:] if len(output) > 500 else output,
        }

    except subprocess.TimeoutExpired:
        return {"suite": suite, "passed": 0, "failed": 0, "errors": 1, "skipped": 0,
                "duration_s": round(time.monotonic() - t0, 1),
                "status": STATUS_ERROR, "output": f"kubectl exec timeout after {timeout}s"}
    except Exception as exc:
        return {"suite": suite, "passed": 0, "failed": 0, "errors": 1, "skipped": 0,
                "duration_s": round(time.monotonic() - t0, 1),
                "status": STATUS_ERROR, "output": str(exc)[:200]}


# ── Full per-service test run ─────────────────────────────────────────────────
def test_service_pod(kubeconfig: str, namespace: str, pod: dict,
                     suites: list[str], health_timeout: int = 5,
                     suite_timeout: int = 120) -> dict:
    """
    Run all requested test suites for one service pod.
    Returns a result dict for the service.
    """
    pod_name    = pod["name"]
    svc_name    = pod["service_name"]
    t0          = time.monotonic()

    if pod["phase"] != "Running":
        return {
            "service": svc_name, "pod": pod_name,
            "overall_status": STATUS_SKIP, "phase": pod["phase"],
            "health": False, "suites": [], "duration_s": 0,
        }

    # 1. Quick health gate
    healthy = quick_health_check(kubeconfig, namespace, pod_name, timeout=health_timeout)
    if not healthy:
        return {
            "service": svc_name, "pod": pod_name,
            "overall_status": STATUS_ERROR, "phase": pod["phase"],
            "health": False, "suites": [],
            "duration_s": round(time.monotonic() - t0, 1),
            "detail": "/health did not return 200",
        }

    # 2. Run each suite sequentially inside the pod
    suite_results = []
    any_fail = False
    for suite in suites:
        sr = run_suite_in_pod(kubeconfig, namespace, pod_name, suite, service_name=svc_name, timeout=suite_timeout)
        suite_results.append(sr)
        if sr["status"] in (STATUS_FAIL, STATUS_ERROR):
            any_fail = True

    overall = STATUS_FAIL if any_fail else STATUS_PASS
    total_passed = sum(s["passed"] for s in suite_results)
    total_failed = sum(s["failed"] + s["errors"] for s in suite_results)

    return {
        "service":        svc_name,
        "pod":            pod_name,
        "overall_status": overall,
        "phase":          pod["phase"],
        "health":         True,
        "total_passed":   total_passed,
        "total_failed":   total_failed,
        "suites":         suite_results,
        "duration_s":     round(time.monotonic() - t0, 1),
    }


# ── Parallel sweep ─────────────────────────────────────────────────────────────
def run_all_tests(kubeconfig: str, namespace: str, suites: list[str],
                  workers: int = 10, health_timeout: int = 5,
                  suite_timeout: int = 120) -> list[dict]:
    """Run full test suite on all service pods in parallel."""
    print(f"\n[test-runner] Fetching pods from namespace: {namespace}")
    pods = get_running_service_pods(kubeconfig, namespace)
    print(f"[test-runner] Found {len(pods)} service pods")
    print(f"[test-runner] Test suites: {', '.join(suites)}")
    print(f"[test-runner] Workers: {workers}  Suite timeout: {suite_timeout}s")
    print()

    results: list[dict] = []
    total  = len(pods)
    done   = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                test_service_pod,
                kubeconfig, namespace, pod, suites, health_timeout, suite_timeout
            ): pod
            for pod in pods
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done += 1
            status = result["overall_status"]
            icon   = "✅" if status == STATUS_PASS else (
                     "⏭️" if status == STATUS_SKIP else "❌")
            p = result.get("total_passed", 0)
            f = result.get("total_failed", 0)
            d = f"{result.get('duration_s', 0):.0f}s"
            print(f"  [{done:>3}/{total}] {icon} {result['service']:<55} "
                  f"{status:<10} tests={p}✅/{f}❌  {d}")

    return results


# ── Summary printer ───────────────────────────────────────────────────────────
def print_summary(results: list[dict], suites: list[str]) -> None:
    counts = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_ERROR: 0,
              STATUS_SKIP: 0, STATUS_NOTESTS: 0}
    total_passed = total_failed = 0

    for r in results:
        s = r["overall_status"]
        counts[s] = counts.get(s, 0) + 1
        total_passed += r.get("total_passed", 0)
        total_failed += r.get("total_failed", 0)

    total    = len(results)
    assessed = total - counts[STATUS_SKIP]
    pass_rate = counts[STATUS_PASS] / max(1, assessed)

    print("\n" + "=" * 70)
    print("  POST-DEPLOYMENT TEST SUITE RESULTS")
    print("=" * 70)
    print(f"  Services assessed:  {assessed} / {total}")
    print(f"  ✅ ALL PASS:        {counts[STATUS_PASS]}")
    print(f"  ❌ FAILED:          {counts[STATUS_FAIL]}")
    print(f"  🚫 ERROR:           {counts[STATUS_ERROR]}")
    print(f"  ⏭️  SKIPPED:         {counts[STATUS_SKIP]}")
    print(f"  Individual tests:   {total_passed} passed  /  {total_failed} failed")
    print(f"  Service pass rate:  {pass_rate:.1%}")
    print(f"  Suites run:         {', '.join(suites)}")
    print("=" * 70)

    # Per-suite breakdown
    suite_totals: dict[str, dict] = {s: {"passed": 0, "failed": 0, "notests": 0} for s in suites}
    for r in results:
        for sr in r.get("suites", []):
            suite = sr["suite"]
            if suite in suite_totals:
                suite_totals[suite]["passed"]  += sr.get("passed", 0)
                suite_totals[suite]["failed"]  += sr.get("failed", 0) + sr.get("errors", 0)
                if sr["status"] == STATUS_NOTESTS:
                    suite_totals[suite]["notests"] += 1

    print("\n  PER-SUITE BREAKDOWN:")
    for suite, t in suite_totals.items():
        print(f"    {suite:<20}  {t['passed']:>4} passed  {t['failed']:>4} failed"
              f"  ({t['notests']} services had no {suite}/ tests)")

    # Failed services detail
    failed_svcs = [r for r in results if r["overall_status"] in (STATUS_FAIL, STATUS_ERROR)]
    if failed_svcs:
        print(f"\n  FAILED SERVICES ({len(failed_svcs)}):")
        for r in sorted(failed_svcs, key=lambda x: x["service"]):
            print(f"    ❌ {r['service']}")
            for sr in r.get("suites", []):
                if sr["status"] in (STATUS_FAIL, STATUS_ERROR):
                    print(f"       → {sr['suite']}: {sr['status']}  "
                          f"{sr.get('failed',0)+sr.get('errors',0)} failed")
                    if sr.get("output"):
                        # Print last few lines of pytest output
                        lines = sr["output"].splitlines()
                        for line in lines[-5:]:
                            print(f"         {line}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="JTP Post-Deployment Service Test Suite Runner"
    )
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--namespace", default="exo-jtp-prod")
    parser.add_argument("--workers", type=int, default=10,
                        help="Parallel pod workers (default: 10)")
    parser.add_argument("--suites", nargs="+", default=ALL_SUITES,
                        choices=ALL_SUITES,
                        help=f"Test suites to run (default: all = {ALL_SUITES})")
    parser.add_argument("--health-timeout", type=int, default=5,
                        help="Health check timeout per pod in seconds (default: 5)")
    parser.add_argument("--suite-timeout", type=int, default=120,
                        help="Max seconds per suite per pod (default: 120)")
    parser.add_argument("--output-json", help="Save full results to JSON file")
    parser.add_argument("--fail-threshold", type=float, default=0.80,
                        help="Min fraction of services that must PASS (default: 0.80)")
    args = parser.parse_args()

    ts = datetime.now().isoformat()
    print(f"[test-runner] JTP Post-Deployment Test Suite Runner — {ts}")
    print(f"[test-runner] kubeconfig: {args.kubeconfig}")
    print(f"[test-runner] namespace:  {args.namespace}")
    print(f"[test-runner] workers:    {args.workers}")
    print(f"[test-runner] suites:     {args.suites}")

    try:
        results = run_all_tests(
            kubeconfig    = args.kubeconfig,
            namespace     = args.namespace,
            suites        = args.suites,
            workers       = args.workers,
            health_timeout = args.health_timeout,
            suite_timeout  = args.suite_timeout,
        )
    except Exception as exc:
        print(f"[test-runner] FATAL: {exc}", file=sys.stderr)
        return 1

    print_summary(results, args.suites)

    # Save JSON report
    if args.output_json:
        report = {
            "timestamp":    ts,
            "kubeconfig":   args.kubeconfig,
            "namespace":    args.namespace,
            "suites_run":   args.suites,
            "results":      results,
            "summary": {
                "total":        len(results),
                STATUS_PASS:    sum(1 for r in results if r["overall_status"] == STATUS_PASS),
                STATUS_FAIL:    sum(1 for r in results if r["overall_status"] == STATUS_FAIL),
                STATUS_ERROR:   sum(1 for r in results if r["overall_status"] == STATUS_ERROR),
                STATUS_SKIP:    sum(1 for r in results if r["overall_status"] == STATUS_SKIP),
                "total_tests_passed": sum(r.get("total_passed", 0) for r in results),
                "total_tests_failed": sum(r.get("total_failed", 0) for r in results),
            }
        }
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2))
        print(f"\n[test-runner] Full report saved: {out_path}")

    # Exit code decision
    assessed  = [r for r in results if r["overall_status"] != STATUS_SKIP]
    pass_count = sum(1 for r in assessed if r["overall_status"] == STATUS_PASS)
    rate       = pass_count / max(1, len(assessed))

    if rate < args.fail_threshold:
        print(f"\n[test-runner] ❌ FAIL: {rate:.1%} services passed < "
              f"{args.fail_threshold:.0%} threshold")
        return 1

    print(f"\n[test-runner] ✅ PASS: {rate:.1%} services passed ≥ "
          f"{args.fail_threshold:.0%} threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
