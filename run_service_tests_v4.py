#!/usr/bin/env python3
"""
run_service_tests_v4.py — JTP Service Health Test Suite
=========================================================
Plan 122-DEH Phase 1: Deploy Engine Hardening

CHANGES (Plan 122-DEH, 2026-03-03):
  ISSUE-002 FIX: Removed hardcoded GATEWAY IP. Gateway URL is now discovered
    dynamically via:
      1. --gateway-url CLI flag (highest priority)
      2. --report deployment_report.json (reads gateway_url field)
      3. kubectl get nodes -o wide + configured NodePort (--nodeport, default 30671)
    ValueError raised with clear instructions if none succeed.

  ISSUE-007 FIX: http_get() now retries up to 3 times with 10s delay between
    attempts before recording a failure. HTTP 4xx/5xx errors are NOT retried
    (they are definitive). Connection errors and timeouts ARE retried.
    Result dict now includes retry_count and error_type for Grafana visibility.

  NEW: --gateway-url, --report, --kubeconfig, --nodeport, --output CLI flags.
  NEW: preflight_gateway_check() validates gateway /health before running suite.

SEQUENTIAL service test — tests only / and /health per service.
/status is documented but backend services don't implement it, so excluded.
Sequential (1 worker) to avoid saturating the gateway event loop.
"""

import argparse
import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def p(*a, **kw):
    print(*a, **kw, flush=True)


SERVICES_DIR = pathlib.Path(__file__).parent / "service" / "services"
DEFAULT_NODEPORT = 30671
DEFAULT_TIMEOUT = 5
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 10  # seconds between retry attempts


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI ARGUMENT PARSER
#  Plan 122-DEH ISSUE-002: All gateway config comes from CLI — never hardcoded
# ═══════════════════════════════════════════════════════════════════════════════
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JTP Service Health Test Suite v4 (Plan 122-DEH hardened)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Gateway URL Discovery Order:
  1. --gateway-url flag (explicit override — highest priority)
  2. --report path (reads gateway_url from deployment_report.json)
  3. kubectl get nodes -o wide (first Ready node EXTERNAL-IP + --nodeport)

Examples:
  python3 run_service_tests_v4.py --gateway-url http://159.100.249.9:30671
  python3 run_service_tests_v4.py --report outputs/20260303_085439/deployment_report.json
  python3 run_service_tests_v4.py --kubeconfig outputs/20260303_085439/kubeconfig.yaml
""",
    )
    parser.add_argument(
        "--gateway-url",
        default=None,
        metavar="URL",
        help="Gateway base URL (e.g. http://159.100.249.9:30671). "
             "Skips auto-discovery when set.",
    )
    parser.add_argument(
        "--report",
        default=None,
        metavar="PATH",
        help="Path to deployment_report.json. Reads gateway_url field.",
    )
    parser.add_argument(
        "--kubeconfig",
        default=None,
        metavar="PATH",
        help="Path to kubeconfig file for kubectl node discovery.",
    )
    parser.add_argument(
        "--nodeport",
        type=int,
        default=DEFAULT_NODEPORT,
        help=f"NodePort for gateway (default: {DEFAULT_NODEPORT}).",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Write JSON test report to this path. "
             "Default: docs/plans/122-Deploy-Engine-Hardening/service_test_results_v4.json",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP request timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Max HTTP retry attempts per service (default: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=DEFAULT_RETRY_DELAY,
        help=f"Seconds between retry attempts (default: {DEFAULT_RETRY_DELAY}).",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip gateway preflight health check before running suite.",
    )
    return parser.parse_args()


# ═══════════════════════════════════════════════════════════════════════════════
#  GATEWAY DISCOVERY
#  Plan 122-DEH ISSUE-002: Dynamic discovery replaces hardcoded IP
# ═══════════════════════════════════════════════════════════════════════════════
def discover_gateway(
    report_path: str | None = None,
    nodeport: int = DEFAULT_NODEPORT,
    kubeconfig: str | None = None,
) -> str:
    """
    Discover the gateway URL for the current deployment.

    Discovery priority order:
      1. deployment_report.json gateway_url field (set by deploy_pipeline.py)
      2. kubectl get nodes -o wide (first Ready node EXTERNAL-IP + NodePort)

    Returns:
        Gateway URL string e.g. "http://159.100.249.9:30671"

    Raises:
        ValueError: If gateway cannot be discovered. Message includes instructions.
    """
    # --- Priority 1: deployment_report.json ---
    if report_path:
        report_file = pathlib.Path(report_path)
        if report_file.exists():
            try:
                data = json.loads(report_file.read_text())
                # Try top-level gateway_url first, then nested resources
                gw = (
                    data.get("gateway_url")
                    or data.get("resources", {}).get("gateway_url")
                )
                if gw:
                    p(f"[DISCOVER] Gateway from deployment report: {gw}")
                    return gw.rstrip("/")
            except (json.JSONDecodeError, OSError) as e:
                p(f"[DISCOVER] Warning: Could not read report {report_path}: {e}")
        else:
            p(f"[DISCOVER] Report not found: {report_path} — trying kubectl")

    # --- Priority 2: kubectl node discovery ---
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    try:
        r = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "wide", "--no-headers"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in r.stdout.strip().split("\n"):
            parts = line.split()
            # Expected columns: NAME STATUS ROLES AGE VERSION INTERNAL-IP EXTERNAL-IP ...
            if len(parts) >= 7 and "Ready" in parts[1] and "NotReady" not in parts[1]:
                external_ip = parts[6]
                if external_ip and external_ip not in ("<none>", ""):
                    gateway_url = f"http://{external_ip}:{nodeport}"
                    p(f"[DISCOVER] Gateway from kubectl node: {gateway_url}")
                    return gateway_url
    except FileNotFoundError:
        p("[DISCOVER] kubectl not found in PATH")
    except subprocess.TimeoutExpired:
        p("[DISCOVER] kubectl timed out")
    except Exception as e:
        p(f"[DISCOVER] kubectl error: {e}")

    raise ValueError(
        "\n"
        "  Gateway URL could not be discovered automatically.\n"
        "\n"
        "  Fix options (in order of preference):\n"
        "    1. python3 run_service_tests_v4.py --gateway-url http://<NODE_IP>:30671\n"
        "    2. python3 run_service_tests_v4.py --report outputs/<TS>/deployment_report.json\n"
        "    3. python3 run_service_tests_v4.py --kubeconfig outputs/<TS>/kubeconfig.yaml\n"
        "\n"
        "  To find node IPs manually:\n"
        "    kubectl get nodes -o wide\n"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  PREFLIGHT GATEWAY CHECK
#  Validates gateway /health before running 200+ service tests
# ═══════════════════════════════════════════════════════════════════════════════
def preflight_gateway_check(gateway_url: str, timeout: int = 10) -> bool:
    """
    Check gateway /health endpoint before running the full test suite.
    Returns True if gateway is reachable and returns HTTP 200.
    Returns False (with warning) if unreachable — suite continues with degraded results.
    """
    health_url = f"{gateway_url}/health"
    p(f"[PREFLIGHT] Checking gateway: {health_url}")
    try:
        req = urllib.request.Request(
            health_url, headers={"User-Agent": "jtp-tester-preflight/4"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            if r.status == 200:
                try:
                    info = json.loads(body)
                    loaded = info.get("services_loaded", "?")
                    failed = info.get("services_failed", "?")
                    p(f"[PREFLIGHT] Gateway UP (HTTP 200) — "
                      f"services_loaded={loaded} services_failed={failed}")
                except Exception:
                    p(f"[PREFLIGHT] Gateway UP (HTTP 200)")
                return True
            p(f"[PREFLIGHT] WARNING: Gateway returned HTTP {r.status} — "
              f"results may be unreliable")
            return False
    except Exception as e:
        p(f"[PREFLIGHT] WARNING: Gateway UNREACHABLE: {e}")
        p(f"[PREFLIGHT] Verify manually: curl {health_url}")
        p(f"[PREFLIGHT] Continuing test suite — all results will FAIL")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  HTTP GET WITH RETRY
#  Plan 122-DEH ISSUE-007: Retry logic to distinguish transient from permanent failures
# ═══════════════════════════════════════════════════════════════════════════════
def http_get(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: int = DEFAULT_RETRY_DELAY,
) -> dict:
    """
    HTTP GET with retry logic for transient failures.

    Retry policy:
      - Connection errors and timeouts: retried up to max_retries times
      - HTTP 4xx/5xx errors: NOT retried (definitive application failures)
      - Successful 2xx/3xx: returned immediately, no retry needed

    Returns dict with keys:
      ok:           bool — True if HTTP status < 400
      status_code:  int  — HTTP status code (0 if connection failed)
      body:         dict — parsed JSON body or {"raw": "..."}
      latency_ms:   float — round-trip time in milliseconds
      retry_count:  int  — number of retry attempts made (0 = first attempt succeeded)
      error_type:   str  — "none" | "timeout" | "connection_refused" | "http_error" | "unknown"
      error:        str  — error message if not ok (empty string if ok)
    """
    last_error_type = "none"
    last_error_msg = ""

    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jtp-tester/4"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body_raw = r.read().decode("utf-8", errors="replace")
                latency_ms = round((time.time() - t0) * 1000, 1)
                try:
                    parsed_body = json.loads(body_raw)
                except Exception:
                    parsed_body = {"raw": body_raw[:200]}
                return {
                    "ok": True,
                    "status_code": r.status,
                    "body": parsed_body,
                    "latency_ms": latency_ms,
                    "retry_count": attempt - 1,
                    "error_type": "none",
                    "error": "",
                }

        except urllib.error.HTTPError as e:
            # HTTP errors (4xx, 5xx) are definitive — do NOT retry
            latency_ms = round((time.time() - t0) * 1000, 1)
            return {
                "ok": False,
                "status_code": e.code,
                "body": {},
                "latency_ms": latency_ms,
                "retry_count": attempt - 1,
                "error_type": "http_error",
                "error": f"HTTP {e.code}",
            }

        except urllib.error.URLError as e:
            latency_ms = round((time.time() - t0) * 1000, 1)
            reason_str = str(e.reason).lower()
            if "refused" in reason_str:
                last_error_type = "connection_refused"
            elif "timed out" in reason_str or "timeout" in reason_str:
                last_error_type = "timeout"
            else:
                last_error_type = "url_error"
            last_error_msg = str(e)[:80]

        except TimeoutError:
            last_error_type = "timeout"
            last_error_msg = "request timed out"

        except Exception as e:
            last_error_type = "unknown"
            last_error_msg = str(e)[:80]

        # Wait before retry (skip wait on last attempt)
        if attempt < max_retries:
            time.sleep(retry_delay)

    # All attempts exhausted
    return {
        "ok": False,
        "status_code": 0,
        "body": {},
        "latency_ms": 0.0,
        "retry_count": max_retries - 1,
        "error_type": last_error_type,
        "error": last_error_msg,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SERVICE TYPE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════
def detect_type(name: str) -> str:
    cfg = SERVICES_DIR / name / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text()).get("type", "backend")
        except Exception:
            pass
    return "frontend" if "frontend" in name else "backend"


# ═══════════════════════════════════════════════════════════════════════════════
#  SERVICE TEST
# ═══════════════════════════════════════════════════════════════════════════════
def test_service(
    name: str,
    idx: int,
    total: int,
    gateway: str,
    timeout: int,
    max_retries: int,
    retry_delay: int,
) -> dict:
    svc_type = detect_type(name)
    base = gateway + "/api/" + name
    root = http_get(base + "/", timeout, max_retries, retry_delay)
    health = http_get(base + "/health", timeout, max_retries, retry_delay)
    passed = root["ok"] and health["ok"]
    avg = round((root["latency_ms"] + health["latency_ms"]) / 2, 1)

    def icon(res: dict) -> str:
        if res["ok"]:
            return "OK"
        sc = res["status_code"]
        if sc == 0:
            return f"TMO({res['error_type']})"
        return f"E{sc}"

    retry_note = ""
    total_retries = root["retry_count"] + health["retry_count"]
    if total_retries > 0:
        retry_note = f" [retried x{total_retries}]"

    status_char = "." if passed else "F"
    line = (
        f"[{idx}/{total}] {status_char} {name}"
        f"  /={icon(root)} /health={icon(health)} avg={avg}ms{retry_note}"
    )
    p(line)

    return {
        "service": name,
        "type": svc_type,
        "passed": passed,
        "root": root,
        "health": health,
        "avg_latency_ms": avg,
        "total_retries": total_retries,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    args = parse_args()

    # Resolve gateway URL
    if args.gateway_url:
        gateway = args.gateway_url.rstrip("/")
        p(f"[GATEWAY] Using explicit --gateway-url: {gateway}")
    else:
        try:
            gateway = discover_gateway(
                report_path=args.report,
                nodeport=args.nodeport,
                kubeconfig=args.kubeconfig,
            )
        except ValueError as e:
            p(f"\n[ERROR] {e}")
            raise SystemExit(1)

    # Resolve output paths
    if args.output:
        json_report_path = pathlib.Path(args.output)
    else:
        report_dir = (
            pathlib.Path(__file__).parent.parent
            / "docs" / "plans" / "122-Deploy-Engine-Hardening"
        )
        report_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_report_path = report_dir / f"service_test_results_v4_{ts}.json"

    md_report_path = json_report_path.with_suffix(".md")

    now = datetime.now(timezone.utc).isoformat()
    p("=" * 60)
    p("Service Test Run v4 — Sequential (Plan 122-DEH hardened)")
    p(f"Gateway: {gateway}")
    p(f"Started: {now}")
    p(f"Retries: {args.retries} attempts, {args.retry_delay}s delay")
    p("=" * 60)

    # Gateway preflight
    gateway_up = True
    if not args.no_preflight:
        gateway_up = preflight_gateway_check(gateway, timeout=10)
    else:
        p("[PREFLIGHT] Skipped (--no-preflight)")

    # Discover services
    services = sorted(
        d.name for d in SERVICES_DIR.iterdir()
        if d.is_dir() and (d / "main.py").exists()
    )
    total = len(services)
    p(f"\nServices: {total}  Timeout: {args.timeout}s\n")

    # Gateway health check (for report data)
    p("[Gateway] /health ...")
    gw = http_get(gateway + "/health", timeout=args.timeout,
                  max_retries=args.retries, retry_delay=args.retry_delay)
    svc_loaded = gw.get("body", {}).get("services_loaded", "?")
    svc_failed = gw.get("body", {}).get("services_failed", "?")
    p(
        f"  services_loaded={svc_loaded}  services_failed={svc_failed}"
        f"  {'OK' if gw['ok'] else 'FAIL'}  {gw['latency_ms']}ms\n"
    )

    # Sequential service tests
    p(f"Testing {total} services (sequential, / and /health)...\n")
    results = []
    passed_count = 0
    failed_count = 0
    total_retries_all = 0

    for idx, name in enumerate(services, 1):
        r = test_service(
            name, idx, total, gateway,
            args.timeout, args.retries, args.retry_delay,
        )
        results.append(r)
        if r["passed"]:
            passed_count += 1
        else:
            failed_count += 1
        total_retries_all += r["total_retries"]

    finished = datetime.now(timezone.utc).isoformat()
    duration = (
        datetime.fromisoformat(finished) - datetime.fromisoformat(now)
    ).total_seconds()

    failures = [r for r in results if not r["passed"]]
    avg_lat = round(sum(r["avg_latency_ms"] for r in results) / total, 1) if total else 0
    n_frontend = sum(1 for r in results if r["type"] == "frontend")
    n_backend = sum(1 for r in results if r["type"] == "backend")
    passed_backend = sum(1 for r in results if r["type"] == "backend" and r["passed"])
    passed_frontend = sum(1 for r in results if r["type"] == "frontend" and r["passed"])

    # JSON report
    summary = {
        "gateway": gateway,
        "gateway_discovered": not bool(args.gateway_url),
        "gateway_up": gateway_up,
        "started_at": now,
        "finished_at": finished,
        "duration_seconds": round(duration, 1),
        "total_services": total,
        "passed": passed_count,
        "failed": failed_count,
        "frontend_services": n_frontend,
        "backend_services": n_backend,
        "passed_frontend": passed_frontend,
        "passed_backend": passed_backend,
        "gateway_health_ok": gw["ok"],
        "services_loaded_at_gateway": svc_loaded,
        "avg_service_latency_ms": avg_lat,
        "total_retries_across_suite": total_retries_all,
        "test_config": {
            "timeout": args.timeout,
            "max_retries": args.retries,
            "retry_delay": args.retry_delay,
        },
        "failures": [
            {
                "service": r["service"],
                "type": r["type"],
                "root_status": r["root"]["status_code"],
                "root_error_type": r["root"]["error_type"],
                "root_error": r["root"].get("error", ""),
                "health_status": r["health"]["status_code"],
                "health_error_type": r["health"]["error_type"],
                "health_error": r["health"].get("error", ""),
                "total_retries": r["total_retries"],
            }
            for r in failures
        ],
    }
    full = {"summary": summary, "gateway_health": gw, "service_tests": results}
    json_report_path.write_text(json.dumps(full, indent=2))

    # Markdown report
    result_label = (
        "ALL PASS" if failed_count == 0
        else f"{passed_count}/{total} PASSED"
    )
    lines = [
        "# Service Test Report",
        f"**Date:** {now[:10]}  ",
        f"**Gateway:** `{gateway}`  ",
        f"**Result:** {result_label} | {failed_count} failed  ",
        f"**Duration:** {round(duration, 1)}s  ",
        f"**Avg latency:** {avg_lat} ms  ",
        f"**Gateway:** services_loaded={svc_loaded} | services_failed={svc_failed}  ",
        f"**Service types:** {n_frontend} frontend ({passed_frontend} passed) | "
        f"{n_backend} backend ({passed_backend} passed)  ",
        f"**Total retries:** {total_retries_all} across {total} services  ",
        "",
        "> Endpoints tested: `GET /` and `GET /health` (sequential)  ",
        "> Each endpoint retried up to "
        f"{args.retries}x with {args.retry_delay}s delay on connection errors  ",
        "> HTTP 4xx/5xx errors are NOT retried (definitive failures)  ",
        "",
        "---",
        "",
        "## Service Results",
        "",
        "| # | Service | Type | / | /health | Avg ms | Retries | Result |",
        "|---|---------|------|---|---------|--------|---------|--------|",
    ]

    for i, r in enumerate(results, 1):
        def c(res: dict) -> str:
            if res["ok"]:
                return "200 OK"
            sc = res["status_code"]
            if sc == 0:
                return f"TIMEOUT ({res['error_type']})"
            return f"ERR {sc}"
        result_cell = "PASS" if r["passed"] else "FAIL"
        lines.append(
            f"| {i} | `{r['service']}` | {r['type']} | "
            f"{c(r['root'])} | {c(r['health'])} | "
            f"{r['avg_latency_ms']} | {r['total_retries']} | {result_cell} |"
        )

    if failures:
        lines += ["", "---", "", "## Failures", ""]
        for r in failures:
            lines.append(f"### `{r['service']}` ({r['type']})")
            lines.append(
                f"- `/`      : HTTP {r['root']['status_code']} "
                f"({r['root']['error_type']}) {r['root'].get('error', '')}"
            )
            lines.append(
                f"- `/health`: HTTP {r['health']['status_code']} "
                f"({r['health']['error_type']}) {r['health'].get('error', '')}"
            )
            if r["total_retries"] > 0:
                lines.append(f"- Retries: {r['total_retries']} total")
            lines.append("")

    lines += [
        "",
        "---",
        f"*Generated: {finished}  Duration: {round(duration, 1)}s*",
        f"*Plan 122-DEH — Deploy Engine Hardening (ISSUE-002 + ISSUE-007 fixed)*",
    ]
    md_report_path.write_text("\n".join(lines))

    # Final summary
    p(f"\n{'=' * 60}")
    p(f"RESULT: {passed_count}/{total} PASSED  |  {failed_count} FAILED")
    p(f"  Backend:  {passed_backend}/{n_backend} passed")
    p(f"  Frontend: {passed_frontend}/{n_frontend} passed")
    p(f"Duration: {round(duration, 1)}s  |  Avg latency: {avg_lat}ms")
    p(f"Gateway: services_loaded={svc_loaded}")
    p(f"Total retries across suite: {total_retries_all}")
    if failures:
        p(f"\nFailed ({len(failures)}):")
        for r in failures:
            p(
                f"  x {r['service']} ({r['type']})"
                f" /={r['root']['status_code']}({r['root']['error_type']})"
                f" /health={r['health']['status_code']}({r['health']['error_type']})"
                + (f" retried x{r['total_retries']}" if r["total_retries"] > 0 else "")
            )
    p("=" * 60)
    p(f"JSON: {json_report_path}")
    p(f"MD:   {md_report_path}")


if __name__ == "__main__":
    main()
