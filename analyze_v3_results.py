#!/usr/bin/env python3
"""Analyze v3 test JSON: extract true pass/fail based on / and /health only."""
import json
import pathlib

JSON = pathlib.Path("/home/iandre/projects/jtp-bio-v3/docs/plans/119-Factory-E2E-Test-3/service_test_results.json")

d = json.loads(JSON.read_text())
tests = d["service_tests"]

def core_pass(r):
    eps = r["endpoints"]
    return eps["/"]["ok"] and eps["/health"]["ok"]

truly_passing = [r for r in tests if core_pass(r)]
truly_failing  = [r for r in tests if not core_pass(r)]
status_ok      = [r for r in tests if r["endpoints"]["/status"]["ok"]]
status_404     = [r for r in tests if r["endpoints"]["/status"]["status_code"] == 404]
status_tmo     = [r for r in tests if r["endpoints"]["/status"]["status_code"] == 0]

print("=" * 60)
print("V3 Result Analysis — True Pass/Fail (/ and /health only)")
print("=" * 60)
print("Total services:                  ", len(tests))
print("/ AND /health both 200-OK (PASS):", len(truly_passing))
print("/ OR /health failed (FAIL):      ", len(truly_failing))
print("/status 200-OK:                  ", len(status_ok))
print("/status 404 (not implemented):   ", len(status_404))
print("/status TIMEOUT (gateway hang):  ", len(status_tmo))
print()

if truly_failing:
    print("Services with / or /health failures (potential issues):")
    for r in truly_failing:
        e = r["endpoints"]
        root_sc   = e["/"]["status_code"]
        health_sc = e["/health"]["status_code"]
        root_err   = e["/"].get("error", "")
        health_err = e["/health"].get("error", "")
        # Distinguish timeout from real error
        root_label   = "TMO" if root_sc == 0 else str(root_sc)
        health_label = "TMO" if health_sc == 0 else str(health_sc)
        print("  -", r["service"], " /=" + root_label, "/health=" + health_label,
              "   err:", root_err or health_err)
else:
    print("All services pass / and /health!")

print()
print("Passing services (" + str(len(truly_passing)) + "):")
for r in truly_passing:
    avg = round((r["endpoints"]["/"]["latency_ms"] + r["endpoints"]["/health"]["latency_ms"]) / 2, 1)
    print("  PASS", r["service"], "avg=" + str(avg) + "ms")
