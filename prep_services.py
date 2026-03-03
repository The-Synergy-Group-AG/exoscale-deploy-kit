#!/usr/bin/env python3
"""
prep_services.py — Copy 219 service src/ dirs into service/services/
======================================================================
Run BEFORE docker build. Copies each service's src/ contents into
exoscale-deploy-kit/service/services/{service_name}/ so the Dockerfile
COPY instruction can include them all.

Usage:
    python3 prep_services.py
"""
import shutil
import json
from pathlib import Path

SERVICES_SRC = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / "generated-v8.2.16" / "services"
DEST = Path(__file__).parent / "service" / "services"

def main():
    if not SERVICES_SRC.exists():
        print(f"ERROR: services source not found: {SERVICES_SRC}")
        return 1

    print(f"Source: {SERVICES_SRC}")
    print(f"Dest:   {DEST}")

    # Clean destination
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    services = sorted(p for p in SERVICES_SRC.iterdir() if p.is_dir())
    print(f"Copying {len(services)} services...")

    ok = 0
    failed = []
    for svc in services:
        src_dir = svc / "src"
        if not src_dir.exists():
            print(f"  WARN: {svc.name} has no src/ — skipping")
            failed.append(svc.name)
            continue
        dest_svc = DEST / svc.name
        dest_svc.mkdir(parents=True, exist_ok=True)
        for f in src_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, dest_svc / f.name)
        ok += 1
        if ok % 50 == 0:
            print(f"  ... {ok}/{len(services)} done")

    print(f"\nDone: {ok} services copied, {len(failed)} skipped")
    if failed:
        print(f"Skipped: {failed}")

    # Write manifest
    manifest = {
        "total": ok,
        "failed": failed,
        "services": [svc.name for svc in DEST.iterdir() if svc.is_dir()],
    }
    (DEST.parent / "services_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Manifest: {DEST.parent}/services_manifest.json")
    return 0

if __name__ == "__main__":
    exit(main())
