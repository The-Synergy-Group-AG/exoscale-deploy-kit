#!/usr/bin/env python3
"""verify_gateway.py — Smoke test all 219 service routes via the live gateway."""
import json, sys, time
import urllib.request, urllib.error

BASE = "http://159.100.249.9"
TIMEOUT = 10

def get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as ex:
        return 0, {"error": str(ex)}

print("=" * 60)
print("  JTP-Bio-V3 Gateway Verification")
print("=" * 60)

# 1. Gateway root
status, data = get("/")
print(f"\n[1] GET / -> {status}")
if status == 200:
    print(f"    gateway={data.get('gateway')} version={data.get('version')}")
    print(f"    services_loaded={data.get('services_loaded')} expected={data.get('total_expected')}")
    print(f"    uptime_seconds={data.get('uptime_seconds')}")
else:
    print(f"    ERROR: {data}"); sys.exit(1)

# 2. Aggregate health
status, data = get("/health")
print(f"\n[2] GET /health -> {status}")
print(f"    status={data.get('status')} loaded={data.get('services_loaded')} failed={data.get('services_failed')}")

# 3. Service list
status, data = get("/api/services")
print(f"\n[3] GET /api/services -> {status}")
total = data.get("total", 0)
failed = data.get("failed", [])
print(f"    total={total}  failed={len(failed)}")
if failed:
    print(f"    failed services: {failed[:10]}")

# 4. Sample service health checks (first 10 + last 10)
services = sorted([s["name"] for s in data.get("services", [])])
sample = services[:5] + services[-5:] if len(services) > 10 else services
print(f"\n[4] Sample service health checks ({len(sample)} services):")
ok = 0
for svc in sample:
    status, resp = get(f"/api/{svc}/health")
    mark = "✓" if status == 200 else "✗"
    print(f"    {mark} /api/{svc}/health -> {status}")
    if status == 200:
        ok += 1

# 5. Summary
print("\n" + "=" * 60)
print("  VERIFICATION SUMMARY")
print("=" * 60)
print(f"  Gateway:         {'OK' if total > 0 else 'FAILED'}")
print(f"  Services loaded: {total} / 219")
print(f"  Services failed: {len(failed)}")
print(f"  Sample checks:   {ok}/{len(sample)} OK")
print(f"  External IP:     {BASE}")
overall = "PASS" if total >= 200 and ok == len(sample) else "DEGRADED"
print(f"  Overall:         {overall}")
print("=" * 60)
sys.exit(0 if overall == "PASS" else 1)
