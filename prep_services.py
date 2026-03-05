#!/usr/bin/env python3
"""
prep_services.py — Copy service src/ dirs into service/services/
=================================================================
Run BEFORE docker build. Copies each service's src/ contents into
exoscale-deploy-kit/service/services/{service_name}/ so the Dockerfile
COPY instruction can include them all.

Also copies tests/ alongside src/ (added in Phase 4 — Plan 123).

DYNAMIC VERSION SELECTION (updated — no longer hardcoded):
    Automatically discovers the latest generated-v* snapshot in
    engines/service_engine/outputs/ by parsing semantic version numbers
    (MAJOR.MINOR.PATCH).  This ensures a new generation is picked up
    automatically without editing this file.

Usage:
    python3 prep_services.py                  # auto-select latest generation
    python3 prep_services.py --version 8.2.22 # pin to a specific generation
"""
import argparse
import re
import shutil
import json
from pathlib import Path

# Base outputs directory — scanned for generated-v* snapshots
OUTPUTS_DIR = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs"
DEST = Path(__file__).parent / "service" / "services"


def _parse_version(name: str):
    """
    Extract (major, minor, patch) tuple from a directory name like
    'generated-v8.2.24'.  Returns None if the name doesn't match.
    """
    m = re.match(r"^generated-v(\d+)\.(\d+)\.(\d+)$", name)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def find_latest_generation(outputs_dir: Path) -> Path:
    """
    Scan *outputs_dir* for generated-v* directories, sort by semantic
    version, and return the Path to the highest one.

    Raises RuntimeError if no valid snapshot is found.
    """
    candidates = []
    for entry in outputs_dir.iterdir():
        if not entry.is_dir():
            continue
        ver = _parse_version(entry.name)
        if ver is not None:
            candidates.append((ver, entry))

    if not candidates:
        raise RuntimeError(
            f"No generated-v* directories found under {outputs_dir}"
        )

    candidates.sort(key=lambda x: x[0])          # sort ascending by (major, minor, patch)
    latest_ver, latest_path = candidates[-1]      # last = highest
    print(
        f"[prep_services] Discovered {len(candidates)} generation(s). "
        f"Latest: {latest_path.name}  "
        f"(v{'.'.join(str(n) for n in latest_ver)})"
    )
    return latest_path


def main():
    parser = argparse.ArgumentParser(description="Stage service source dirs for Docker build")
    parser.add_argument(
        "--version", "-v",
        default=None,
        metavar="MAJOR.MINOR.PATCH",
        help=(
            "Pin to a specific generation, e.g. --version 8.2.22.  "
            "Omit to auto-select the latest."
        ),
    )
    args = parser.parse_args()

    # ── Resolve source directory ──────────────────────────────────────────
    if args.version:
        generation_name = f"generated-v{args.version}"
        services_src = OUTPUTS_DIR / generation_name / "services"
        print(f"[prep_services] Pinned to: {generation_name}")
    else:
        try:
            gen_dir = find_latest_generation(OUTPUTS_DIR)
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            return 1
        services_src = gen_dir / "services"
        generation_name = gen_dir.name

    if not services_src.exists():
        print(f"ERROR: services source not found: {services_src}")
        return 1

    print(f"[prep_services] Source generation : {generation_name}")
    print(f"[prep_services] Source services   : {services_src}")
    print(f"[prep_services] Destination       : {DEST}")

    # ── Clean destination ─────────────────────────────────────────────────
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    services = sorted(p for p in services_src.iterdir() if p.is_dir())
    print(f"[prep_services] Copying {len(services)} service(s)...")

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

        # Copy tests/ directory tree alongside src/ files
        tests_dir = svc / "tests"
        if tests_dir.exists():
            shutil.copytree(tests_dir, dest_svc / "tests", dirs_exist_ok=True)

        ok += 1
        if ok % 50 == 0:
            print(f"  ... {ok}/{len(services)} done")

    print(f"\n[prep_services] Done: {ok} service(s) copied, {len(failed)} skipped")
    if failed:
        print(f"[prep_services] Skipped: {failed}")

    # ── Write manifest ────────────────────────────────────────────────────
    manifest = {
        "generation": generation_name,
        "total": ok,
        "failed": failed,
        "services": sorted(svc.name for svc in DEST.iterdir() if svc.is_dir()),
    }
    manifest_path = DEST.parent / "services_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"[prep_services] Manifest written: {manifest_path}")
    return 0


if __name__ == "__main__":
    exit(main())
