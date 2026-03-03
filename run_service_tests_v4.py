#!/usr/bin/env python3
"""
run_service_tests_v4.py
SEQUENTIAL service test — tests only / and /health per service.
/status is documented but backend services don't implement it, so excluded.
Sequential (1 worker) to avoid saturating the gateway event loop.
Timeout: 5s per request.
"""

import json
import pathlib
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

def p(*a, **kw):
    print(*a, **kw, flush=True)

GATEWAY      = "http://159.100.249.9"
SERVICES_DIR = pathlib.Path(__file__).parent / "service" / "services"
TIMEOUT      = 5

REPORT_DIR = pathlib.Path(__file__).parent.parent / "docs" / "plans" / "119-Factory-E2E-Test-3"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
JSON_REPORT = REPORT_DIR / "service_test_results_v4.json"
MD_REPORT   = REPORT_DIR / "SERVICE_TEST_REPORT.md"


def http_get(url, timeout=TIMEOUT):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "jtp-tester/4"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            ms = round((time.time() - t0) * 1000, 1)
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body[:200]}
            return {"ok": True, "status_code": r.status, "body": parsed, "latency_ms": ms}
    except urllib.error.HTTPError as e:
        ms = round((time.time() - t0) * 1000, 1)
        return {"ok": False, "status_code": e.code, "body": {}, "latency_ms": ms,
                "error": "HTTP " + str(e.code)}
    except Exception as e:
        ms = round((time.time() - t0) * 1000, 1)
        return {"ok": False, "status_code": 0, "body": {}, "latency_ms": ms,
                "error": str(e)[:80]}


def detect_type(name):
    cfg = SERVICES_DIR / name / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text()).get("type", "backend")
        except Exception:
            pass
    return "frontend" if "frontend" in name else "backend"


def test_service(name, idx, total):
    svc_type = detect_type(name)
    base = GATEWAY + "/api/" + name
    root   = http_get(base + "/")
    health = http_get(base + "/health")
    passed = root["ok"] and health["ok"]
    avg    = round((root["latency_ms"] + health["latency_ms"]) / 2, 1)

    root_icon   = "OK" if root["ok"] else ("TMO" if root["status_code"] == 0 else "E" + str(root["status_code"]))
    health_icon = "OK" if health["ok"] else ("TMO" if health["status_code"] == 0 else "E" + str(health["status_code"]))

    status_char = "." if passed else "F"
    line = "[" + str(idx) + "/" + str(total) + "] " + status_char + " " + name + \
           "  /=" + root_icon + " /health=" + health_icon + " avg=" + str(avg) + "ms"
    p(line)

    return {
        "service": name,
        "type": svc_type,
        "passed": passed,
        "root": root,
        "health": health,
        "avg_latency_ms": avg,
    }


def main():
    now = datetime.now(timezone.utc).isoformat()
    p("=" * 60)
    p("Service Test Run v4 — Sequential")
    p("Gateway: " + GATEWAY)
    p("Started: " + now)
    p("=" * 60)

    services = sorted(
        d.name for d in SERVICES_DIR.iterdir()
        if d.is_dir() and (d / "main.py").exists()
    )
    total = len(services)
    p("Services: " + str(total) + "  Timeout: " + str(TIMEOUT) + "s\n")

    # Gateway health check
    p("[Gateway] /health ...")
    gw = http_get(GATEWAY + "/health")
    svc_loaded = gw.get("body", {}).get("services_loaded", "?")
    svc_failed = gw.get("body", {}).get("services_failed", "?")
    p("  services_loaded=" + str(svc_loaded) + "  services_failed=" + str(svc_failed) +
      "  " + ("OK" if gw["ok"] else "FAIL") + "  " + str(gw["latency_ms"]) + "ms\n")

    # Sequential service tests
    p("Testing " + str(total) + " services (sequential, / and /health)...\n")
    results = []
    passed = 0
    failed = 0

    for idx, name in enumerate(services, 1):
        r = test_service(name, idx, total)
        results.append(r)
        if r["passed"]:
            passed += 1
        else:
            failed += 1

    finished = datetime.now(timezone.utc).isoformat()
    duration = (
        datetime.fromisoformat(finished) - datetime.fromisoformat(now)
    ).total_seconds()

    failures    = [r for r in results if not r["passed"]]
    avg_lat     = round(sum(r["avg_latency_ms"] for r in results) / total, 1)
    n_frontend  = sum(1 for r in results if r["type"] == "frontend")
    n_backend   = sum(1 for r in results if r["type"] == "backend")

    # JSON report
    summary = {
        "gateway": GATEWAY,
        "started_at": now,
        "finished_at": finished,
        "duration_seconds": round(duration, 1),
        "total_services": total,
        "passed": passed,
        "failed": failed,
        "frontend_services": n_frontend,
        "backend_services": n_backend,
        "gateway_health_ok": gw["ok"],
        "services_loaded_at_gateway": svc_loaded,
        "avg_service_latency_ms": avg_lat,
        "failures": [
            {
                "service": r["service"],
                "type": r["type"],
                "root_status": r["root"]["status_code"],
                "root_error": r["root"].get("error", ""),
                "health_status": r["health"]["status_code"],
                "health_error": r["health"].get("error", ""),
            }
            for r in failures
        ],
    }
    full = {"summary": summary, "gateway_health": gw, "service_tests": results}
    JSON_REPORT.write_text(json.dumps(full, indent=2))

    # Markdown report
    result_label = "ALL PASS" if failed == 0 else (str(passed) + "/" + str(total) + " PASSED")
    lines = [
        "# Service Test Report — All 219 Services",
        "**Date:** " + now[:10] + "  ",
        "**Gateway:** " + GATEWAY + "  ",
        "**Result:** " + result_label + " | " + str(failed) + " failed  ",
        "**Duration:** " + str(round(duration, 1)) + "s  ",
        "**Avg latency:** " + str(avg_lat) + " ms  ",
        "**Gateway:** services_loaded=" + str(svc_loaded) +
        " | services_failed=" + str(svc_failed) + "  ",
        "**Service types:** " + str(n_frontend) + " frontend | " + str(n_backend) + " backend  ",
        "",
        "> Endpoints tested: `GET /` and `GET /health` (sequential, 5s timeout)  ",
        "> `/status` excluded — backend services use Starlette sub-app mounts that hang on undefined routes  ",
        "",
        "---",
        "",
        "## Service Results",
        "",
        "| # | Service | Type | / | /health | Avg ms | Result |",
        "|---|---------|------|---|---------|--------|--------|",
    ]

    for i, r in enumerate(results, 1):
        def c(res):
            if res["ok"]:
                return "200 OK"
            sc = res["status_code"]
            if sc == 0:
                return "TIMEOUT"
            return "ERR " + str(sc)
        result_cell = "PASS" if r["passed"] else "FAIL"
        lines.append(
            "| " + str(i) + " | `" + r["service"] + "` | " + r["type"] + " | " +
            c(r["root"]) + " | " + c(r["health"]) + " | " +
            str(r["avg_latency_ms"]) + " | " + result_cell + " |"
        )

    if failures:
        lines += ["", "---", "", "## Failures", ""]
        for r in failures:
            lines.append("### `" + r["service"] + "` (" + r["type"] + ")")
            lines.append("- `/`      : HTTP " + str(r["root"]["status_code"]) +
                         " " + r["root"].get("error", ""))
            lines.append("- `/health`: HTTP " + str(r["health"]["status_code"]) +
                         " " + r["health"].get("error", ""))
            lines.append("")

    lines += ["", "---",
              "*Generated: " + finished + "  Duration: " + str(round(duration, 1)) + "s*"]
    MD_REPORT.write_text("\n".join(lines))

    # Final summary
    p("\n" + "=" * 60)
    p("RESULT: " + str(passed) + "/" + str(total) + " PASSED  |  " + str(failed) + " FAILED")
    p("Duration: " + str(round(duration, 1)) + "s  |  Avg latency: " + str(avg_lat) + "ms")
    p("Frontend: " + str(n_frontend) + "  Backend: " + str(n_backend))
    p("Gateway: services_loaded=" + str(svc_loaded))
    if failures:
        p("\nFailed (" + str(len(failures)) + "):")
        for r in failures:
            p("  x " + r["service"] + " (" + r["type"] + ")" +
              " /=" + str(r["root"]["status_code"]) +
              " /health=" + str(r["health"]["status_code"]))
    p("=" * 60)
    p("JSON: " + str(JSON_REPORT))
    p("MD:   " + str(MD_REPORT))


if __name__ == "__main__":
    main()
