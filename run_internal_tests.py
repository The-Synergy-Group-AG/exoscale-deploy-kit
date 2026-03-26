#!/usr/bin/env python3
"""
In-Cluster Per-Service Test Runner — Plan 175
==============================================
Runs INSIDE the K8s cluster (via kubectl exec or Job) with direct access
to all service ClusterIPs. Tests each of the 234 services individually.

Usage (from outside cluster):
    kubectl exec -n exo-jtp-prod deployment/docker-jtp -- \
        python3 /app/run_internal_tests.py --all

Or via deploy pipeline Stage 7:
    Automatically launched as a K8s Job after pod verification.

Results published to event bus + JSON output file.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NAMESPACE = os.environ.get("NAMESPACE", "exo-jtp-prod")
KUBECONFIG = os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/config"))


def discover_services() -> list[dict]:
    """Discover all JTP services in the cluster via kubectl."""
    try:
        r = subprocess.run(
            [
                "kubectl", "get", "svc", "-n", NAMESPACE,
                "-o", "jsonpath={range .items[*]}{.metadata.name}\\t{.spec.ports[0].port}\\t{.metadata.labels.jtp-zone}\\n{end}",
            ],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "KUBECONFIG": KUBECONFIG},
        )
        services = []
        for line in r.stdout.strip().split("\n"):
            parts = line.strip().split("\t")
            if len(parts) >= 2 and parts[0] not in ("kubernetes", "prometheus", "grafana"):
                services.append({
                    "name": parts[0],
                    "port": int(parts[1]) if parts[1].isdigit() else 8000,
                    "zone": parts[2] if len(parts) > 2 else "",
                    "url": f"http://{parts[0]}.{NAMESPACE}.svc.cluster.local:{parts[1]}",
                })
        return services
    except Exception as e:
        logger.error(f"Service discovery failed: {e}")
        return []


def test_service(svc: dict) -> dict:
    """Test a single service via its ClusterIP. Returns result dict."""
    name = svc["name"]
    url = svc["url"]
    result = {
        "service": name,
        "port": svc["port"],
        "zone": svc["zone"],
        "health": False,
        "endpoints_tested": 0,
        "endpoints_passed": 0,
        "errors": [],
    }

    try:
        import httpx
        client = httpx.Client(timeout=10.0, verify=False)

        # Test 1: Health check
        try:
            r = client.get(f"{url}/health")
            result["health"] = r.status_code == 200
        except Exception as e:
            result["errors"].append(f"health: {e}")

        # Test 2: Root endpoint
        try:
            r = client.get(f"{url}/")
            result["endpoints_tested"] += 1
            if r.status_code == 200:
                result["endpoints_passed"] += 1
        except Exception as e:
            result["endpoints_tested"] += 1
            result["errors"].append(f"root: {e}")

        # Test 3: POST endpoints (if chat-capable)
        try:
            r = client.post(f"{url}/", json={"message": "test"})
            result["endpoints_tested"] += 1
            if r.status_code in (200, 201, 405):  # 405 = no POST handler, acceptable
                result["endpoints_passed"] += 1
        except Exception:
            result["endpoints_tested"] += 1

        client.close()

    except ImportError:
        # httpx not available — use urllib
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            req = urllib.request.Request(f"{url}/health")
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            result["health"] = resp.status == 200
            result["endpoints_tested"] += 1
            result["endpoints_passed"] += 1
        except Exception as e:
            result["errors"].append(str(e))

    total = result["endpoints_tested"]
    passed = result["endpoints_passed"]
    result["pass_rate"] = passed / total if total > 0 else 0.0
    result["status"] = "passing" if result["health"] and result["pass_rate"] >= 0.5 else "failing"

    return result


def run_all_tests(workers: int = 20) -> dict:
    """Test ALL services in parallel. Returns comprehensive report."""
    logger.info("Discovering services...")
    services = discover_services()
    logger.info(f"Found {len(services)} services")

    if not services:
        return {"error": "No services discovered", "total": 0}

    results = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(test_service, svc): svc for svc in services}
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
                icon = "OK" if result["status"] == "passing" else "!!"
                logger.info(f"  [{icon}] {result['service']:40s} health={result['health']}")
            except Exception as e:
                svc = futures[future]
                logger.error(f"  [ER] {svc['name']}: {e}")

    elapsed = time.time() - t0
    total = len(results)
    healthy = sum(1 for r in results if r["health"])
    passing = sum(1 for r in results if r["status"] == "passing")

    # Group by zone
    by_zone = {}
    for r in results:
        zone = r.get("zone", "unknown")
        by_zone.setdefault(zone, {"total": 0, "passing": 0})
        by_zone[zone]["total"] += 1
        if r["status"] == "passing":
            by_zone[zone]["passing"] += 1

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(elapsed, 1),
        "total_services": total,
        "healthy": healthy,
        "passing": passing,
        "failing": total - passing,
        "pass_rate": round(passing / total, 3) if total > 0 else 0.0,
        "by_zone": by_zone,
        "services": {r["service"]: r for r in sorted(results, key=lambda x: x["service"])},
        "failing_services": [r["service"] for r in results if r["status"] == "failing"],
    }

    logger.info(f"\n{'='*60}")
    logger.info(f"  {passing}/{total} services passing ({report['pass_rate']:.0%})")
    logger.info(f"  {healthy}/{total} healthy")
    logger.info(f"  Duration: {elapsed:.1f}s")
    logger.info(f"{'='*60}")

    return report


def main():
    parser = argparse.ArgumentParser(description="In-Cluster Per-Service Test Runner")
    parser.add_argument("--all", action="store_true", help="Test all services")
    parser.add_argument("--service", type=str, help="Test one specific service")
    parser.add_argument("--workers", type=int, default=20, help="Parallel workers")
    parser.add_argument("--output", type=str, default="/tmp/per_service_test_results.json", help="Output JSON path")
    args = parser.parse_args()

    if args.service:
        svc = {"name": args.service, "port": 8000, "zone": "",
               "url": f"http://{args.service}.{NAMESPACE}.svc.cluster.local:8000"}
        result = test_service(svc)
        print(json.dumps(result, indent=2))
    elif args.all:
        report = run_all_tests(workers=args.workers)
        Path(args.output).write_text(json.dumps(report, indent=2))
        print(f"Results written to {args.output}")
        sys.exit(0 if report.get("pass_rate", 0) >= 0.95 else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
