#!/usr/bin/env python3
"""diag_gateway.py — Diagnose 208/219 gap and health endpoint behaviour."""
import json, sys
import urllib.request, urllib.error

BASE = "http://159.100.249.9"

def fetch(path, timeout=15):
    try:
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return e.code, body
    except Exception as ex:
        return 0, {"error": str(ex)}

# ── /health (allow 207) ─────────────────────────────────────────────────────
print("\n[1] GET /health")
code, data = fetch("/health")
print(f"  HTTP {code}: {data}")

# ── /api/services — find the 11 missing ones ────────────────────────────────
print("\n[2] GET /api/services — identify missing services")
code, data = fetch("/api/services")
loaded_names = sorted(s["name"] for s in data.get("services", []))
print(f"  Loaded count : {len(loaded_names)}")
print(f"  Bootstrap fail: {data.get('failed', [])}")

# All dirs in services/
import pathlib, subprocess
result = subprocess.run(
    ["python3", "-c",
     "import pathlib; p=pathlib.Path('/app/services'); "
     "print('\\n'.join(sorted(d.name for d in p.iterdir() if d.is_dir())))"],
    capture_output=True, text=True
)
# That won't work locally — instead compare loaded vs local prep dirs
import os
svc_dir = pathlib.Path("/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/service/services")
if svc_dir.exists():
    all_dirs = sorted(d.name for d in svc_dir.iterdir() if d.is_dir())
    loaded_set = set(loaded_names)
    missing = [n for n in all_dirs if n not in loaded_set]
    print(f"\n  Total dirs locally: {len(all_dirs)}")
    print(f"  Missing from gateway ({len(missing)}):")
    for m in missing:
        print(f"    - {m}")
        mp = svc_dir / m / "main.py"
        if mp.exists():
            # Check what error might occur
            try:
                import importlib.util
                orig = os.getcwd()
                os.chdir(str(svc_dir / m))
                spec = importlib.util.spec_from_file_location("test_svc", str(mp))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                os.chdir(orig)
                print(f"      main.py: OK locally")
            except Exception as e:
                os.chdir(orig)
                print(f"      main.py ERROR: {e}")

# ── Sample /health endpoints — all loaded services ──────────────────────────
print("\n[3] Sampling ALL health endpoints (first 20)")
ok = fail = 0
for name in loaded_names[:20]:
    code, resp = fetch(f"/api/{name}/health", timeout=8)
    mark = "✓" if code == 200 else "✗"
    if code == 200: ok += 1
    else: fail += 1
    print(f"  {mark} /api/{name}/health -> {code}")

print(f"\n  First-20 sample: {ok} OK, {fail} failed")
