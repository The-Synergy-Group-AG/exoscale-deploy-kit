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

    # ── L72: Sync 12 AI backend services from shared/ ────────────────────
    _AI_BACKEND_SOURCES = [
        ("gpt4_orchestrator",   "shared/ai/gpt4_orchestrator"),
        ("claude_integration",  "shared/ai/claude_integration"),
        ("embeddings_engine",   "shared/ai/embeddings_engine"),
        ("vector_store",        "shared/ai/vector_store"),
        ("job_matcher",         "shared/extended/job_matcher"),
        ("cv_processor",        "shared/extended/cv_processor"),
        ("career_navigator",    "shared/extended/career_navigator"),
        ("skill_bridge",        "shared/extended/skill_bridge"),
        ("memory_system",       "shared/consciousness/memory_system"),
        ("learning_system",     "shared/consciousness/learning_system"),
        ("pattern_recognition", "shared/consciousness/pattern_recognition"),
        ("decision_making",     "shared/consciousness/decision_making"),
    ]
    if not args.dry_run:
        _ai_synced = 0
        for ai_name, ai_rel_path in _AI_BACKEND_SOURCES:
            ai_src = SCRIPT_DIR.parent / ai_rel_path
            ai_dest = DEST / ai_name
            if not ai_src.exists():
                _warn(f"  L72: AI backend source not found: {ai_src}")
                continue
            if ai_dest.exists():
                shutil.rmtree(ai_dest)
            ai_dest.mkdir(parents=True)
            # Copy all files from AI service directory (main.py etc. at root)
            _n = 0
            for f in ai_src.iterdir():
                if f.is_file():
                    shutil.copy2(f, ai_dest / f.name)
                    _n += 1
                elif f.is_dir() and f.name != "__pycache__":
                    shutil.copytree(f, ai_dest / f.name, dirs_exist_ok=True)
                    _n += 1
            _ai_synced += 1
            stats["files_copied"] += _n
            stats["services"].append(ai_name)
            stats["ok"] += 1
        _info(f"L72: {_ai_synced}/{len(_AI_BACKEND_SOURCES)} AI backend services synced")

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

    # Plan 145: Patch interview_prep_service with Pinecone tracking
    for _p145_name, _p145_file, _p145_svc in [
        ("interview", "_patch_interview_wiring.py", "interview_prep_service"),
        ("emotional", "_patch_emotional_wiring.py", "emotional_intelligence_system"),
        ("employer/market", "_patch_employer_research_wiring.py", "swiss_market_service"),
        ("user_profile", "_patch_user_profile_wiring.py", "user_profile_service"),
        ("notification", "_patch_notification_wiring.py", "notification_service"),
        ("email", "_patch_email_wiring.py", "email_integration_service"),
        ("affiliate", "_patch_affiliate_wiring.py", "affiliate_manager_service"),
        ("crm", "_patch_crm_wiring.py", "crm_integration_service"),
        ("credit_system", "_patch_credit_system_wiring.py", "credit_system_service"),
        ("retention", "_patch_retention_wiring.py", "retention_winback_service"),
        ("personality", "_patch_personality_assessment.py", "personality_assessment_service"),
        ("wheel_of_life", "_patch_wheel_of_life.py", "wheel_of_life_service"),
        ("vision_mission", "_patch_vision_mission.py", "vision_mission_service"),
        ("portfolio", "_patch_portfolio_wiring.py", "portfolio_service"),
    ]:
        _p145_path = SCRIPT_DIR / _p145_file
        if _p145_path.exists():
            import subprocess as _sp145
            _p145_result = _sp145.run(
                [sys.executable, str(_p145_path)],
                capture_output=True, text=True, cwd=str(SCRIPT_DIR),
            )
            if "PATCHED" in _p145_result.stdout:
                _ok(f"Plan 145: {_p145_name} service patched with Pinecone persistence")
            elif "SKIP" in _p145_result.stdout:
                _ok(f"Plan 145: {_p145_name} service already patched")

    # Plan 143: Patch subscription_management_service with Stripe + Pinecone
    _sub_patch = SCRIPT_DIR / "_patch_subscription_wiring.py"
    if _sub_patch.exists():
        _info("Plan 143: Patching subscription_management_service...")
        import subprocess as _sp143
        _sp_result = _sp143.run(
            [sys.executable, str(_sub_patch)],
            capture_output=True, text=True, cwd=str(SCRIPT_DIR),
        )
        if "PATCHED" in _sp_result.stdout:
            _ok("Plan 143: Subscription service patched with Stripe + Pinecone")
        elif "SKIP" in _sp_result.stdout:
            _ok("Plan 143: Subscription service already patched")
        else:
            _warn(f"Plan 143: Subscription patch result: {_sp_result.stdout.strip()}")

    # Plan 142: Patch gamification_service with Pinecone wiring
    _gamif_patch = SCRIPT_DIR / "_patch_gamification_wiring.py"
    if _gamif_patch.exists():
        _info("Plan 142: Patching gamification_service with Pinecone wiring...")
        import subprocess as _sp142
        _gp_result = _sp142.run(
            [sys.executable, str(_gamif_patch)],
            capture_output=True, text=True, cwd=str(SCRIPT_DIR),
        )
        if "PATCHED" in _gp_result.stdout:
            _ok("Plan 142: Gamification service patched with real Pinecone persistence")
        elif "SKIP" in _gp_result.stdout:
            _ok("Plan 142: Gamification service already patched")
        else:
            _warn(f"Plan 142: Gamification patch result: {_gp_result.stdout.strip()}")

    # ── Plan 149: Universal Pinecone persistence for ALL services ──────────
    _univ_patch = SCRIPT_DIR / "_patch_universal_persistence.py"
    if _univ_patch.exists():
        _info("Plan 149: Injecting universal Pinecone persistence...")
        import subprocess as _sp149a
        _up_result = _sp149a.run(
            [sys.executable, str(_univ_patch), str(gen_path / "services")],
            capture_output=True, text=True,
        )
        for line in _up_result.stdout.strip().splitlines():
            _info(f"  {line}")

    # ── Plan 149: Fix user story test URLs for in-pod execution ──────────
    _us_patch = SCRIPT_DIR / "_patch_user_story_tests.py"
    if _us_patch.exists():
        _info("Plan 149: Patching user story test URLs for K8s DNS...")
        import subprocess as _sp149b
        _ut_result = _sp149b.run(
            [sys.executable, str(_us_patch), str(gen_path / "services")],
            capture_output=True, text=True,
        )
        for line in _ut_result.stdout.strip().splitlines():
            _info(f"  {line}")

    # ── L62: Re-sync ALL patched services from source → destination ──────
    # Patches modify source (generated-v*/services/*/src/main.py) but the
    # sync already copied UNPATCHED files to service/services/. Re-copy ALL
    # patched files so the Docker build workspace has the real code.
    _resync_count = 0
    services_src = gen_path / "services"
    for _svc_dir in services_src.iterdir():
        if not _svc_dir.is_dir():
            continue
        _src_main = _svc_dir / "src" / "main.py"
        _dst_main = DEST / _svc_dir.name / "main.py"
        if _src_main.exists() and _dst_main.parent.exists():
            shutil.copy2(_src_main, _dst_main)
            _resync_count += 1
        # Also re-sync test files
        _src_us = _svc_dir / "tests" / "user_stories" / "test_user_stories.py"
        _dst_us = DEST / _svc_dir.name / "tests" / "user_stories" / "test_user_stories.py"
        if _src_us.exists() and _dst_us.parent.exists():
            _dst_us.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_src_us, _dst_us)
    if _resync_count:
        _ok(f"L62: Re-synced {_resync_count} services (main.py + tests) to Docker build workspace")

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
