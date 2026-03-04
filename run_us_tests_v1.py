#!/usr/bin/env python3
"""
run_us_tests_v1.py — FADS User Story Endpoint Test Suite
=========================================================
Plan 123-FADS-Service-Implementation — Post-deployment US validation

For each of the 219 FADS services:
  1. Fetches /openapi.json through the gateway to discover all routes
  2. Parses US IDs from each route's description field
     (format: "... | US: US-001, US-002, ...")
  3. Fires a smoke-test HTTP request for every (route, method) combination
     - GET/DELETE: no body
     - POST/PUT/PATCH: empty JSON body {}
     - Path params ({name}, {id}, etc.) replaced with safe placeholders
  4. PASS = HTTP status < 500  (200/201/204/422 all count as PASS)
     FAIL = HTTP status >= 500 (internal server error)
  5. Maps results to US IDs and produces JSON + Markdown reports

Usage:
    python3 run_us_tests_v1.py
    python3 run_us_tests_v1.py --gateway-url http://159.100.254.72:30671
    python3 run_us_tests_v1.py --service auth_service   # single service debug
"""
import argparse
import json
import pathlib
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SERVICES_DIR = pathlib.Path(__file__).parent / "service" / "services"
DEFAULT_GATEWAY = "http://159.100.254.72:30671"
DEFAULT_TIMEOUT = 8

PARAM_PLACEHOLDERS = {
    "id": "1", "name": "test", "slug": "test-item", "key": "test-key",
    "token": "test-token", "user_id": "1", "service_id": "1",
    "feature_id": "1", "metric": "test", "type": "default",
    "category": "general", "tag": "test", "version": "v1", "path": "test",
}
DEFAULT_PARAM_VALUE = "test"

US_PATTERN = re.compile(r'\bUS-\d+\b')
BODY_METHODS = {"post", "put", "patch"}
SKIP_PATHS = {"/", "/health", "/metrics", "/docs", "/redoc", "/openapi.json"}


def p(*a, **kw):
    print(*a, **kw, flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="FADS US Endpoint Test Suite v1")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY)
    parser.add_argument("--output", default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--service", default=None)
    return parser.parse_args()


def fill_path_params(path: str) -> str:
    def repl(m):
        return PARAM_PLACEHOLDERS.get(m.group(1).lower(), DEFAULT_PARAM_VALUE)
    return re.sub(r'\{([^}]+)\}', repl, path)


def extract_us_ids(description: str) -> list:
    return sorted(set(US_PATTERN.findall(description or "")))


def http_request(url: str, method: str, timeout: int) -> dict:
    body = b"{}" if method in BODY_METHODS else None
    headers = {"User-Agent": "jtp-us-tester/1", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            latency_ms = round(max(0.0, (time.perf_counter() - t0) * 1000), 1)
            return {"ok": True, "status_code": r.status, "latency_ms": latency_ms, "error": ""}
    except urllib.error.HTTPError as e:
        latency_ms = round(max(0.0, (time.perf_counter() - t0) * 1000), 1)
        ok = e.code < 500
        return {"ok": ok, "status_code": e.code, "latency_ms": latency_ms,
                "error": "" if ok else f"HTTP {e.code}"}
    except Exception as e:
        latency_ms = round(max(0.0, (time.perf_counter() - t0) * 1000), 1)
        return {"ok": False, "status_code": 0, "latency_ms": latency_ms, "error": str(e)[:80]}


def fetch_openapi(gateway: str, service: str, timeout: int):
    url = f"{gateway}/api/{service}/openapi.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "jtp-us-tester/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def test_service(service: str, idx: int, total: int, gateway: str, timeout: int) -> dict:
    p(f"\n[{idx}/{total}] {service}")
    spec = fetch_openapi(gateway, service, timeout)
    if spec is None:
        p("  ⚠  Could not fetch openapi.json")
        return {"service": service, "openapi_ok": False, "routes_tested": 0,
                "passed": 0, "failed": 0, "us_ids_covered": [], "endpoint_results": [],
                "error": "openapi_fetch_failed"}

    paths = spec.get("paths", {})
    endpoint_results = []
    us_ids_covered = set()
    passed = failed = 0

    for path, methods in paths.items():
        if path in SKIP_PATHS:
            continue
        for method, op in methods.items():
            if method.lower() in ("head", "options"):
                continue
            us_ids = extract_us_ids(op.get("description", ""))
            filled_path = fill_path_params(path)
            url = f"{gateway}/api/{service}{filled_path}"
            result = http_request(url, method.lower(), timeout)
            result.update({"path": path, "method": method.upper(), "filled_url": url,
                            "us_ids": us_ids, "summary": op.get("summary", "")})
            endpoint_results.append(result)
            icon = "✅" if result["ok"] else "❌"
            p(f"  {icon} {method.upper():6} {path:35} HTTP {result['status_code']:3}"
              f"  {result['latency_ms']:6}ms  US:{len(us_ids)}")
            if result["ok"]:
                passed += 1
                us_ids_covered.update(us_ids)
            else:
                failed += 1

    p(f"  → {passed} passed, {failed} failed, {len(us_ids_covered)} US IDs covered")
    return {"service": service, "openapi_ok": True, "routes_tested": len(endpoint_results),
            "passed": passed, "failed": failed, "us_ids_covered": sorted(us_ids_covered),
            "endpoint_results": endpoint_results, "error": ""}


def main():
    args = parse_args()
    gateway = args.gateway_url.rstrip("/")

    if args.output:
        json_out = pathlib.Path(args.output)
    else:
        report_dir = (pathlib.Path(__file__).parent.parent
                      / "docs" / "plans" / "123-FADS-Service-Implementation")
        report_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_out = report_dir / f"us_test_results_v1_{ts}.json"
    md_out = json_out.with_suffix(".md")

    if args.service:
        services = [args.service]
    else:
        services = sorted(d.name for d in SERVICES_DIR.iterdir()
                          if d.is_dir() and (d / "main.py").exists())
    total = len(services)
    started = datetime.now(timezone.utc).isoformat()
    t_start = time.perf_counter()

    p("=" * 70)
    p("FADS User Story Endpoint Test Suite v1")
    p(f"Gateway:  {gateway}")
    p(f"Services: {total}")
    p(f"Started:  {started}")
    p("=" * 70)

    all_results = []
    all_us_passed: set = set()
    all_us_failed: set = set()
    total_endpoints = total_passed = total_failed = openapi_failed = 0

    for idx, svc in enumerate(services, 1):
        r = test_service(svc, idx, total, gateway, args.timeout)
        all_results.append(r)
        total_endpoints += r["routes_tested"]
        total_passed += r["passed"]
        total_failed += r["failed"]
        if not r["openapi_ok"]:
            openapi_failed += 1
        for ep in r["endpoint_results"]:
            for us in ep.get("us_ids", []):
                if ep["ok"]:
                    all_us_passed.add(us)
                    all_us_failed.discard(us)
                elif us not in all_us_passed:
                    all_us_failed.add(us)

    duration = round(time.perf_counter() - t_start, 1)
    finished = datetime.now(timezone.utc).isoformat()

    all_us_ids = all_us_passed | all_us_failed
    us_pass_rate = round(len(all_us_passed) / len(all_us_ids) * 100, 1) if all_us_ids else 0.0
    ep_pass_rate = round(total_passed / total_endpoints * 100, 1) if total_endpoints else 0.0

    summary = {
        "gateway": gateway, "started_at": started, "finished_at": finished,
        "duration_seconds": duration, "services_total": total,
        "services_openapi_failed": openapi_failed,
        "endpoints_total": total_endpoints, "endpoints_passed": total_passed,
        "endpoints_failed": total_failed, "endpoint_pass_rate_pct": ep_pass_rate,
        "us_ids_total": len(all_us_ids), "us_ids_passed": len(all_us_passed),
        "us_ids_failed": len(all_us_failed), "us_pass_rate_pct": us_pass_rate,
        "timeout_seconds": args.timeout,
    }
    full_report = {"summary": summary, "service_results": all_results,
                   "us_ids_passed": sorted(all_us_passed),
                   "us_ids_failed": sorted(all_us_failed)}
    json_out.write_text(json.dumps(full_report, indent=2))

    failures = [r for r in all_results if r["failed"] > 0 or not r["openapi_ok"]]
    lines = [
        "# FADS User Story Endpoint Test Report",
        f"**Date:** {started[:10]}  ",
        f"**Gateway:** `{gateway}`  ",
        f"**Duration:** {duration}s  ",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Services tested | {total} |",
        f"| Services OpenAPI failed | {openapi_failed} |",
        f"| Total endpoints tested | {total_endpoints} |",
        f"| Endpoints passed | {total_passed} ({ep_pass_rate}%) |",
        f"| Endpoints failed | {total_failed} |",
        f"| Unique US IDs covered | {len(all_us_ids)} |",
        f"| US IDs PASSED | {len(all_us_passed)} ({us_pass_rate}%) |",
        f"| US IDs FAILED | {len(all_us_failed)} |",
        "",
        "> **PASS = HTTP < 500.** HTTP 4xx (422 etc) = endpoint exists, needs real data = PASS.  ",
        "> HTTP 5xx = server error = FAIL.",
        "",
        "---",
        "",
        "## Service Results",
        "",
        "| Service | Routes | Passed | Failed | US IDs |",
        "|---------|--------|--------|--------|--------|",
    ]
    for r in all_results:
        icon = "✅" if r["failed"] == 0 and r["openapi_ok"] else "❌"
        lines.append(f"| {icon} `{r['service']}` | {r['routes_tested']}"
                     f" | {r['passed']} | {r['failed']} | {len(r['us_ids_covered'])} |")

    if failures:
        lines += ["", "---", "", "## Failures", ""]
        for r in failures:
            if not r["openapi_ok"]:
                lines += [f"### `{r['service']}` — OpenAPI fetch failed", ""]
                continue
            lines.append(f"### `{r['service']}`")
            for ep in r["endpoint_results"]:
                if not ep["ok"]:
                    us_preview = ', '.join(ep['us_ids'][:5])
                    if len(ep['us_ids']) > 5:
                        us_preview += '...'
                    lines.append(f"- `{ep['method']} {ep['path']}` → HTTP {ep['status_code']}"
                                 f" {ep['error']}  US: {us_preview}")
            lines.append("")

    lines += ["", "---",
              f"*Generated: {finished} | Duration: {duration}s*",
              "*Plan 123-FADS-Service-Implementation — US Endpoint Validation v1*"]
    md_out.write_text("\n".join(lines))

    p(f"\n{'=' * 70}")
    p(f"RESULT: {total_endpoints} endpoints tested across {total} services")
    p(f"  Endpoints: {total_passed}/{total_endpoints} PASSED ({ep_pass_rate}%)")
    p(f"  US IDs:    {len(all_us_passed)}/{len(all_us_ids)} PASSED ({us_pass_rate}%)")
    if total_failed:
        p(f"  Failed endpoints: {total_failed}")
    if openapi_failed:
        p(f"  OpenAPI fetch failures: {openapi_failed}")
    p(f"Duration: {duration}s")
    p("=" * 70)
    p(f"JSON: {json_out}")
    p(f"MD:   {md_out}")


if __name__ == "__main__":
    main()
