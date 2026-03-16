#!/usr/bin/env python3
"""
prep_services.py — Service Engine → Docker Build Workspace Sync
================================================================
Synchronises the current service-engine generation into the Docker
build workspace (service/services/).  The workspace is a build-time
artifact: it is listed in .gitignore and is NEVER committed.

Source of truth hierarchy (highest priority first):
  1. --version CLI flag          (explicit pin for debugging / rollback)
  2. outputs/CURRENT file        (maintained by the service engine after
                                  each successful generation run)
  3. Auto-discovery              (highest semantic version in outputs/)

What gets synced per service:
  {generation}/services/{svc}/src/*       → service/services/{svc}/
  {generation}/services/{svc}/tests/      → service/services/{svc}/tests/

The flat copy of src/ is intentional — start.sh expects main.py at the
root of each service directory inside the Docker image.

Usage:
  python3 prep_services.py                  # use CURRENT pointer (or latest)
  python3 prep_services.py --version 8.2.22 # pin to specific generation
  python3 prep_services.py --dry-run        # preview without writing anything
  python3 prep_services.py --validate-only  # check CURRENT without syncing

Exit codes:
  0   Success
  1   Source not found / no generations available
  2   Validation failures (some services missing main.py after sync)
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
OUTPUTS_DIR = SCRIPT_DIR.parent / "engines" / "service_engine" / "outputs"
DEST        = SCRIPT_DIR / "service" / "services"
CURRENT_PTR = OUTPUTS_DIR / "CURRENT"


# ── Version helpers ───────────────────────────────────────────────────────────

def _parse_version(name: str):
    """Return (major, minor, patch) tuple from 'generated-vX.Y.Z', else None."""
    m = re.match(r"^generated-v(\d+)\.(\d+)\.(\d+)$", name)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def resolve_generation(outputs_dir: Path, version_arg: str | None) -> Path:
    """
    Resolve which generation to sync using the priority hierarchy:
      1. --version CLI arg
      2. CURRENT pointer file
      3. Auto-discovery (latest semantic version)

    Returns the resolved generation directory Path.
    Raises SystemExit(1) on failure.
    """
    # Priority 1: explicit --version flag
    if version_arg:
        gen_name = f"generated-v{version_arg}"
        gen_path = outputs_dir / gen_name
        if not gen_path.is_dir():
            _fatal(f"Pinned generation not found: {gen_path}")
        _info(f"Resolution: --version flag → {gen_name}")
        return gen_path

    # Priority 2: CURRENT pointer file
    if CURRENT_PTR.exists():
        current = CURRENT_PTR.read_text().strip()
        if current:
            gen_path = outputs_dir / current
            if gen_path.is_dir():
                _info(f"Resolution: CURRENT pointer → {current}")
                return gen_path
            else:
                _warn(
                    f"CURRENT points to '{current}' but that directory does not "
                    f"exist. Falling back to auto-discovery."
                )
        else:
            _warn("CURRENT file is empty — falling back to auto-discovery.")

    # Priority 3: auto-discover latest semantic version
    candidates = []
    for entry in outputs_dir.iterdir():
        if not entry.is_dir():
            continue
        ver = _parse_version(entry.name)
        if ver is not None:
            candidates.append((ver, entry))

    if not candidates:
        _fatal(f"No generated-v* directories found under {outputs_dir}")

    candidates.sort(key=lambda x: x[0])
    latest_ver, latest_path = candidates[-1]
    _info(
        f"Resolution: auto-discovery ({len(candidates)} generations found) "
        f"→ {latest_path.name}"
    )
    return latest_path


# ── Output helpers ────────────────────────────────────────────────────────────

def _info(msg: str):  print(f"[prep_services]  {msg}")
def _ok(msg: str):    print(f"[prep_services] ✅ {msg}")
def _warn(msg: str):  print(f"[prep_services] ⚠️  {msg}", file=sys.stderr)
def _fatal(msg: str): print(f"[prep_services] ❌ {msg}", file=sys.stderr); sys.exit(1)


# ── Core sync ─────────────────────────────────────────────────────────────────

def sync_services(
    services_src: Path,
    dest: Path,
    dry_run: bool = False,
) -> dict:
    """
    Sync all services from *services_src* into *dest*.

    Per service:
      - Wipe existing dest/{svc}/
      - Flat-copy {svc}/src/* → dest/{svc}/        (main.py etc. at root)
      - Copy      {svc}/tests/ → dest/{svc}/tests/  (full tree)

    Returns a stats dict with keys: ok, skipped, files_copied, services.
    """
    services = sorted(p for p in services_src.iterdir() if p.is_dir())
    stats = {"ok": 0, "skipped": [], "files_copied": 0, "services": []}

    _info(f"Syncing {len(services)} service(s) {'[DRY RUN]' if dry_run else ''}...")

    for svc in services:
        src_dir = svc / "src"
        if not src_dir.exists():
            _warn(f"  {svc.name}: no src/ directory — skipping")
            stats["skipped"].append(svc.name)
            continue

        dest_svc = dest / svc.name

        if not dry_run:
            # Clean destination first to avoid stale files from previous runs
            if dest_svc.exists():
                shutil.rmtree(dest_svc)
            dest_svc.mkdir(parents=True)

            # Flat-copy src/ contents → dest_svc/
            n_files = 0
            for f in src_dir.iterdir():
                if f.is_file():
                    shutil.copy2(f, dest_svc / f.name)
                    n_files += 1

            # Copy tests/ tree alongside src/ files
            tests_dir = svc / "tests"
            if tests_dir.exists():
                shutil.copytree(tests_dir, dest_svc / "tests", dirs_exist_ok=True)
                for _ in (dest_svc / "tests").rglob("*"):
                    if _.is_file():
                        n_files += 1

            # L69: Copy job_scraper module into career domain services
            _job_scraper_src = SCRIPT_DIR.parent / "shared" / "extended" / "job_scraper"
            if _job_scraper_src.exists():
                _cfg_path = src_dir / "config.json"
                if _cfg_path.exists():
                    try:
                        _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
                        if _cfg.get("domain") == "career":
                            shutil.copytree(
                                _job_scraper_src,
                                dest_svc / "job_scraper",
                                dirs_exist_ok=True,
                            )
                            n_files += 2
                    except Exception as exc:
                        _warn(f"  job_scraper copy failed for {svc.name}: {exc}")

            stats["files_copied"] += n_files

        stats["ok"] += 1
        stats["services"].append(svc.name)

        if stats["ok"] % 50 == 0:
            _info(f"  ... {stats['ok']}/{len(services)} services synced")

    return stats


def validate_sync(dest: Path, expected_services: list[str]) -> list[str]:
    """
    After sync, verify every expected service has a main.py at its root.
    Returns list of service names that are missing main.py.
    """
    missing = []
    for svc_name in expected_services:
        main_py = dest / svc_name / "main.py"
        if not main_py.exists():
            missing.append(svc_name)
    return missing


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync service-engine output into the Docker build workspace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--version", "-v",
        default=None,
        metavar="MAJOR.MINOR.PATCH",
        help="Pin to a specific generation (e.g. --version 8.2.22).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without writing anything.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Resolve and print the current generation, then exit (no sync).",
    )
    args = parser.parse_args()

    print()
    print("=" * 64)
    print("  Service Engine → Docker Build Workspace Sync")
    print("=" * 64)

    # ── Resolve generation ────────────────────────────────────────────────
    gen_path = resolve_generation(OUTPUTS_DIR, args.version)
    services_src = gen_path / "services"

    if not services_src.is_dir():
        _fatal(f"services/ directory not found in generation: {gen_path}")

    service_count = sum(1 for p in services_src.iterdir() if p.is_dir())
    _info(f"Generation     : {gen_path.name}")
    _info(f"Source path    : {services_src}")
    _info(f"Dest path      : {DEST}")
    _info(f"Services found : {service_count}")
    print()

    if args.validate_only:
        _ok(f"Generation resolved: {gen_path.name}  ({service_count} services)")
        return 0

    # ── Sync ─────────────────────────────────────────────────────────────
    if not args.dry_run:
        DEST.mkdir(parents=True, exist_ok=True)

    stats = sync_services(services_src, DEST, dry_run=args.dry_run)

    print()
    _info(f"Services synced : {stats['ok']} / {service_count}")
    _info(f"Services skipped: {len(stats['skipped'])}")
    if not args.dry_run:
        _info(f"Files copied    : {stats['files_copied']}")

    if stats["skipped"]:
        _warn(f"Skipped (no src/): {stats['skipped']}")

    if args.dry_run:
        _ok("Dry run complete — no files written")
        return 0

    # ── Validate ─────────────────────────────────────────────────────────
    _info("Validating sync (checking for main.py in each service)...")
    missing = validate_sync(DEST, stats["services"])
    if missing:
        _warn(f"Validation FAILED: {len(missing)} service(s) missing main.py")
        for svc in missing:
            _warn(f"  ✗ {svc}")
        # Non-fatal: write manifest then exit 2 so caller can decide
        exit_code = 2
    else:
        _ok(f"Validation passed — all {stats['ok']} services have main.py")
        exit_code = 0

    # ── Write manifest ────────────────────────────────────────────────────
    manifest = {
        "generation"   : gen_path.name,
        "synced_at"    : __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat() + "Z",
        "total_synced" : stats["ok"],
        "total_skipped": len(stats["skipped"]),
        "files_copied" : stats["files_copied"],
        "skipped"      : stats["skipped"],
        "missing_main" : missing,
        "services"     : stats["services"],
    }
    manifest_path = DEST.parent / "services_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    _info(f"Manifest written: {manifest_path}")

    # ── L54: Patch generated test files (3 codegen bugs) ───────────────────
    # Run _patch_generated_tests.py against the source generation so that
    # test bugs (wrong HTTP method, duplicate names, delete+json) are fixed
    # every time a new generation is synced. Idempotent — safe to rerun.
    patch_script = SCRIPT_DIR / "_patch_generated_tests.py"
    if patch_script.exists():
        services_src = gen_path / "services"
        _info(f"L54: Patching generated test files in {services_src.name}...")
        import subprocess as _sp
        patch_result = _sp.run(
            [sys.executable, str(patch_script), str(services_src)],
            capture_output=True, text=True
        )
        patched_count = patch_result.stdout.count("PATCHED")
        if patched_count:
            _info(f"L54: {patched_count} test files patched (codegen bug fixes)")
        else:
            _ok("L54: No test patches needed (already clean)")
        if patch_result.returncode != 0:
            _warn(f"L54: Patch script warnings: {patch_result.stderr.strip()}")
    else:
        _warn("L54: _patch_generated_tests.py not found — skipping test patch")

    print()
    if exit_code == 0:
        print("=" * 64)
        _ok(f"SYNC COMPLETE — {gen_path.name} → Docker build workspace")
        print("=" * 64)
    else:
        print("=" * 64)
        _warn(f"SYNC COMPLETE WITH WARNINGS — {len(missing)} services need attention")
        print("=" * 64)

    print()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
