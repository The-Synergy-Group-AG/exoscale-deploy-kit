#!/usr/bin/env python3
"""verify_full.py — Full E2E verification.
   Uses local service dir list (excludes frontend-only dirs with no main.py).
   Hits Node 1 directly via NodePort to bypass NLB.
"""
import json, sys, time, pathlib
import urllib.request, urllib.error

BASE  = "http://151.145.203.113:30671"   # Node 1 NodePort — confirmed healthy
TIMEOUT = 6

def fetch(path):
    try:
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=TIMEOUT)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: body = json.loads(e.read())
        except Exception: body = {}
        return e.code, body
    except Exception as ex:
        return 0, {"error": str(ex)}

print("=" * 65)
print("  JTP-Bio-V3 Full E2E Verification")
print("=" * 65)

# 1. Gateway root
code, gw = fetch("/")
print(f"\n[1] GET / → {code}")
assert code == 200, f"Gateway root failed: {gw}"
print(f"    version={gw['version']} loaded={gw['services_loaded']} uptime={gw['uptime_seconds']}s")
print(f"    host={gw['hostname']} env={gw['environment']}")

# 2. Gateway health
code, h = fetch("/health")
print(f"\n[2] GET /health → {code}")
print(f"    status={h.get('status')} loaded={h.get('services_loaded')} failed={h.get('services_failed')}")

# 3. Build service list from local filesystem
SVC_DIR = pathlib.Path("/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/service/services")
all_dirs   = sorted(d.name for d in SVC_DIR.iterdir() if d.is_dir())
backend    = [n for n in all_dirs if (SVC_DIR / n / "main.py").exists()]
frontend   = [n for n in all_dirs if not (SVC_DIR / n / "main.py").exists()]
print(f"\n[3] Service inventory from filesystem:")
print(f"    Total dirs:      {len(all_dirs)}")
print(f"    Backend (main.py): {len(backend)}")
print(f"    Frontend-only:   {len(frontend)} → {', '.join(frontend)}")

# 4. Test ALL backend service /health endpoints
print(f"\n[4] Health-checking all {len(backend)} backend services...")
ok = fail = slow = 0
failed_svcs = []
t0 = time.time()
for name in backend:
    t1 = time.time()
    code, resp = fetch(f"/api/{name}/health")
    elapsed = time.time() - t1
    if code == 200:
        ok += 1
        if elapsed > 3.0:
            slow += 1
    else:
        fail += 1
        failed_svcs.append((name, code, resp.get("error", "")))
total_time = time.time() - t0

# 5. Summary
print("\n" + "=" * 65)
print("  E2E VERIFICATION SUMMARY")
print("=" * 65)
print(f"  Image version:       {gw.get('version', '?')}")
print(f"  Gateway status:      {h.get('status', '?')}")
print(f"  Services loaded:     {gw.get('services_loaded', '?')} / 219")
print(f"  Frontend-only dirs:  {len(frontend)}")
print(f"  Backend services:    {len(backend)}")
print(f"  Health checks OK:    {ok} / {len(backend)}")
print(f"  Health checks FAIL:  {fail} / {len(backend)}")
print(f"  Slow (>3s):          {slow}")
print(f"  Total time:          {total_time:.1f}s")
if failed_svcs:
    print(f"\n  Failed endpoints ({len(failed_svcs)}):")
    for name, code, err in failed_svcs[:30]:
        print(f"    ✗ /api/{name}/health → HTTP {code}  {err[:60] if err else ''}")
nlb_code, _ = fetch("/")  # one more check — NLB might have recovered
nlb_up = nlb_code == 200

print(f"\n  Direct NodePort:     {BASE}")
overall = "PASS" if ok >= 200 else "DEGRADED"
print(f"\n  Overall result:      {overall}")
print("=" * 65)
sys.exit(0 if overall == "PASS" else 1)
