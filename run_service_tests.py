#!/usr/bin/env python3
"""
run_service_tests.py  v3
Tests every deployed service (/, /health, /status) against the live gateway.
  - / and /health are REQUIRED for all services
  - /status is REQUIRED for frontend, OPTIONAL (404 OK) for backend
Workers: 5  |  Timeout: 15s
"""

import json
import pathlib
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

def p(*a, **kw):
    print(*a, **kw, flush=True)

def ep_icon(res):
    """Return human-readable pass/fail string for one endpoint result."""
    if res["ok"]:
        return "200-OK"
    sc = res["status_code"]
    if sc == 404:
        return "404"
    if sc == 0:
        return "TIMEOUT"
    return "ERR-" + str(sc)

GATEWAY      = "http://159.100.249.9"
SERVICES_DIR = pathlib.Path(__file__).parent / "service" / "services"
TIMEOUT      = 15
WORKERS      = 5

REPORT_DIR = pathlib.Path(__file__).parent.parent / "docs" / "plans" / "119-Factory-E2E-Test-3"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
JSON_REPORT = REPORT_DIR / "service_test_results.json"
MD_REPORT   = REPORT_DIR / "SERVICE_TEST_REPORT.md"


def http_get(url, timeout=TIMEOUT):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "jtp-tester/3"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            ms = round((time.time() - t0) * 1000, 1)
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body[:300]}
            return {"ok": True, "status_code": r.status, "body": parsed, "latency_ms": ms}
    except urllib.error.HTTPError as e:
        ms = round((time.time() - t0) * 1000, 1)
        return {"ok": False, "status_code": e.code, "body": {}, "latency_ms": ms, "error": str(e)}
    except Exception as e:
        ms = round((time.time() - t0) * 1000, 1)
        return {"ok": False, "status_code": 0, "body": {}, "latency_ms": ms, "error": str(e)[:120]}


def detect_type(name):
    cfg = SERVICES_DIR / name / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text()).get("type", "backend")
        except Exception:
            pass
    return "frontend" if "frontend" in name else "backend"


def test_service(name):
    svc_type = detect_type(name)
    base = GATEWAY + "/api/" + name
    eps = {}
    req_ok = True

    for ep in ["/", "/health"]:
        r = http_get(base + ep)
        eps[ep] = r
        if not r["ok"]:
            req_ok = False

    r_status = http_get(base + "/status")
    eps["/status"] = r_status

    if svc_type == "frontend":
        status_ok = r_status["ok"]
    else:
        status_ok = r_status["ok"] or r_status["status_code"] == 404

    passed = req_ok and status_ok
    avg = round(sum(eps[e]["latency_ms"] for e in eps) / len(eps), 1)

    return {
        "service": name,
        "type": svc_type,
        "passed": passed,
        "required_ok": req_ok,
        "status_ok": r_status["ok"],
        "endpoints": eps,
        "avg_latency_ms": avg,
    }


def main():
    now = datetime.now(timezone.utc).isoformat()
    p("[" + now + "] Service test run v3 — " + GATEWAY)
    p("Workers: " + str(WORKERS) + "  Timeout: " + str(TIMEOUT) + "s\n")

    services = sorted(
        d.name for d in SERVICES_DIR.iterdir()
        if d.is_dir() and (d / "main.py").exists()
    )
    total = len(services)
    p("Services to test: " + str(total))

    # Gateway health
    p("\n[1/3] Gateway /health ...")
    gw = http_get(GATEWAY + "/health", timeout=5)
    svc_loaded = gw.get("body", {}).get("services_loaded", "?")
    svc_failed = gw.get("body", {}).get("services_failed", "?")
    gw_ok = "OK" if gw["ok"] else "FAIL"
    p("  /health: " + gw_ok + "  services_loaded=" + str(svc_loaded) +
      "  services_failed=" + str(svc_failed) + "  " + str(gw["latency_ms"]) + "ms")

    # Per-service tests
    p("\n[2/3] Testing " + str(total) + " services (" + str(WORKERS) + " workers) ...")
    results = []
    passed = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(test_service, name): name for name in services}
        done = 0
        for future in as_completed(futures):
            done += 1
            r = future.result()
            results.append(r)
            if r["passed"]:
                passed += 1
            else:
                failed += 1
                parts = []
                for ep in r["endpoints"]:
                    parts.append(ep + "=" + ep_icon(r["endpoints"][ep]))
                p("  FAIL [" + str(done) + "/" + str(total) + "] " +
                  r["service"] + "  " + " | ".join(parts))
            if done % 50 == 0:
                p("  ... " + str(done) + "/" + str(total) +
                  " pass=" + str(passed) + " fail=" + str(failed))

    p("  Complete " + str(total) + "/" + str(total) +
      " pass=" + str(passed) + " fail=" + str(failed))

    results.sort(key=lambda x: x["service"])
    finished = datetime.now(timezone.utc).isoformat()

    failures    = [r for r in results if not r["passed"]]
    avg_lat     = round(sum(r["avg_latency_ms"] for r in results) / total, 1)
    n_frontend  = sum(1 for r in results if r["type"] == "frontend")
    n_backend   = sum(1 for r in results if r["type"] == "backend")
    n_status_ok = sum(1 for r in results if r["status_ok"])

    # JSON report
    summary = {
        "gateway": GATEWAY,
        "started_at": now,
        "finished_at": finished,
        "total_services": total,
        "passed": passed,
        "failed": failed,
        "frontend_services": n_frontend,
        "backend_services": n_backend,
        "services_with_status_endpoint": n_status_ok,
        "gateway_health_ok": gw["ok"],
        "services_loaded_at_gateway": svc_loaded,
        "avg_service_latency_ms": avg_lat,
        "failures": [
            {
                "service": r["service"],
                "type": r["type"],
                "endpoints": {
                    ep: {
                        "ok": r["endpoints"][ep]["ok"],
                        "status_code": r["endpoints"][ep]["status_code"],
                        "error": r["endpoints"][ep].get("error", ""),
                    }
                    for ep in r["endpoints"]
                },
            }
            for r in failures
        ],
    }
    full = {"summary": summary, "gateway_health": gw, "service_tests": results}
    JSON_REPORT.write_text(json.dumps(full, indent=2))
    p("\n[3/3] JSON: " + str(JSON_REPORT))

    # Markdown report
    status_icon = "PASS" if failed == 0 else "PARTIAL"
    lines = [
        "# Service Test Report — All 219 Services",
        "**Date:** " + now[:10] + "  ",
        "**Gateway:** " + GATEWAY + "  ",
        "**Status:** " + status_icon + " " + str(passed) + "/" + str(total) +
        " PASSED | " + str(failed) + " failed  ",
        "**Avg latency:** " + str(avg_lat) + " ms  ",
        "**Gateway:** services_loaded=" + str(svc_loaded) +
        " | services_failed=" + str(svc_failed) + "  ",
        "**Breakdown:** " + str(n_frontend) + " frontend | " +
        str(n_backend) + " backend | " +
        str(n_status_ok) + " have /status endpoint  ",
        "",
        "---",
        "",
        "## Service Results",
        "",
        "| # | Service | Type | / | /health | /status | Avg ms | Result |",
        "|---|---------|------|---|---------|---------|--------|--------|",
    ]

    def cell(res):
        if res["ok"]:
            return "OK"
        sc = res["status_code"]
        if sc == 404:
            return "404"
        if sc == 0:
            return "TMO"
        return "E" + str(sc)

    for i, r in enumerate(results, 1):
        e = r["endpoints"]
        result_cell = "PASS" if r["passed"] else "FAIL"
        lines.append(
            "| " + str(i) + " | `" + r["service"] + "` | " + r["type"] + " | " +
            cell(e["/"]) + " | " + cell(e["/health"]) + " | " + cell(e["/status"]) + " | " +
            str(r["avg_latency_ms"]) + " | " + result_cell + " |"
        )

    if failures:
        lines += ["", "---", "", "## Failures Detail", ""]
        for r in failures:
            lines.append("### `" + r["service"] + "` (" + r["type"] + ")")
            for ep, d in r["endpoints"].items():
                status = "OK" if d["ok"] else ("404-expected" if d["status_code"] == 404 else "FAIL")
                lines.append("- **" + ep + "**: HTTP " + str(d["status_code"]) +
                             " [" + status + "] " + d.get("error", ""))
            lines.append("")

    lines += ["", "---",
              "*Generated: " + finished + "*  ",
              "*JSON: `" + JSON_REPORT.name + "`*"]
    MD_REPORT.write_text("\n".join(lines))
    p("Markdown: " + str(MD_REPORT))

    # Console summary
    p("\n" + "=" * 60)
    p("RESULT:  " + str(passed) + "/" + str(total) + " PASSED  |  " + str(failed) + " FAILED")
    p("Frontend: " + str(n_frontend) + "  Backend: " + str(n_backend))
    p("Services with /status: " + str(n_status_ok))
    p("Avg latency: " + str(avg_lat) + " ms")
    if failures:
        p("\nFailed services (" + str(len(failures)) + "):")
        for r in failures:
            p("  x " + r["service"] + " (" + r["type"] + ")")
    p("=" * 60)


if __name__ == "__main__":
    main()
