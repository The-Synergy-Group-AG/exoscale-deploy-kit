#!/usr/bin/env python3
"""
External CI/CD Test Runner — Lesson 53
=======================================
Runs integration, e2e, security, and user_stories test suites for all 219
services against the live gateway (https://jobtrackerpro.ch).

Patches hardcoded gateway URLs in test modules at collection time via a
temporary root conftest.py injection — no source files are modified.

Usage:
    python3 run_external_tests.py [--gateway URL] [--suites SUITE ...] [--workers N]
                                   [--services SVC ...] [--output FILE]

L49 context: unit tests run in-pod via kubectl exec (run_service_tests.py).
L53: external runner handles the other 4 suites requiring live HTTP access.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.resolve()

DEFAULT_GATEWAY = "https://jobtrackerpro.ch"
EXTERNAL_SUITES = ["integration", "e2e", "security", "user_stories"]
DEFAULT_WORKERS = 20
DEFAULT_OUTPUT  = str(SCRIPT_DIR / "outputs" / "external_test_results.json")


def _find_python_with_pytest() -> str:
    """
    Return the path to a python3 executable that has pytest importable.
    Tries sys.executable first, then well-known locations.
    This is needed because the project venv may not have pytest installed
    while the system python3 does (L53 strategic fix).
    """
    candidates = [
        sys.executable,
        "/usr/bin/python3",
        "/usr/local/bin/python3",
        shutil.which("python3") or "",
    ]
    for py in dict.fromkeys(c for c in candidates if c):  # dedup, preserve order
        try:
            result = subprocess.run(
                [py, "-c", "import pytest"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return py
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    # Last resort: try to install pytest into the current environment
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pytest", "httpx", "--quiet"],
            check=True, timeout=60,
        )
        return sys.executable
    except Exception:
        pass
    raise RuntimeError(
        "pytest not found. Install it: pip install pytest httpx\n"
        "  or: pip3 install pytest httpx --break-system-packages"
    )


PYTHON_WITH_PYTEST: str = ""  # resolved lazily on first use

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_services_dir() -> Path:
    """Resolve the current generation's services directory."""
    current_file = PROJECT_ROOT / "engines" / "service_engine" / "outputs" / "CURRENT"
    generation   = current_file.read_text().strip()
    services_dir = PROJECT_ROOT / "engines" / "service_engine" / "outputs" / generation / "services"
    if not services_dir.is_dir():
        raise FileNotFoundError(f"Services directory not found: {services_dir}")
    return services_dir


def list_services(services_dir: Path) -> list[str]:
    """Return sorted list of service directory names."""
    return sorted(
        d.name for d in services_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


def build_conftest_injection(gateway_url: str) -> str:
    """
    Returns conftest.py content that patches hardcoded gateway URLs.
    Uses pytest_runtest_setup (fires before every test item) for reliability.

    Patch targets (module-level variables set by the service engine):
      - GATEWAY_URL  — used by e2e, user_stories
      - SERVICE_BASE — used by security, user_stories (includes /api/<svc>)

    Integration tests use base_url fixture → SERVICE_BASE_URL env var,
    which is set in the environment before pytest is called.
    """
    return f'''"""
Injected by run_external_tests.py (L53) — patches hardcoded gateway URLs.
Auto-generated; do not edit manually.
"""
LIVE_GATEWAY = "{gateway_url}"


def pytest_runtest_setup(item):
    """Patch module-level URL constants before each test runs."""
    mod = item.module

    if hasattr(mod, "GATEWAY_URL"):
        mod.GATEWAY_URL = LIVE_GATEWAY

    if hasattr(mod, "SERVICE_BASE"):
        old = mod.SERVICE_BASE
        if "/api/" in old:
            api_suffix = old[old.index("/api/"):]
            mod.SERVICE_BASE = LIVE_GATEWAY + api_suffix
        else:
            mod.SERVICE_BASE = LIVE_GATEWAY
'''


def _get_pytest_python() -> str:
    """Return cached python path with pytest, resolving on first call."""
    global PYTHON_WITH_PYTEST
    if not PYTHON_WITH_PYTEST:
        PYTHON_WITH_PYTEST = _find_python_with_pytest()
    return PYTHON_WITH_PYTEST


def run_suite_for_service(
    service_name: str,
    suite: str,
    services_dir: Path,
    gateway_url: str,
) -> dict:
    """
    Run a single (service, suite) pytest job.
    Returns a result dict with pass/fail/error counts.
    """
    suite_dir = services_dir / service_name / "tests" / suite
    if not suite_dir.is_dir():
        return {
            "service": service_name,
            "suite": suite,
            "status": "skipped",
            "reason": "suite directory not found",
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "duration_s": 0.0,
        }

    # Find test files
    test_files = sorted(suite_dir.glob("test_*.py"))
    if not test_files:
        return {
            "service": service_name,
            "suite": suite,
            "status": "skipped",
            "reason": "no test files found",
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "duration_s": 0.0,
        }

    # Environment: set SERVICE_BASE_URL so integration test base_url fixture
    # reads from env var rather than localhost (L53).
    env = os.environ.copy()
    env["SERVICE_BASE_URL"] = f"{gateway_url}/api/{service_name.replace('_', '-')}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    # Inject conftest.py into the suite directory so pytest auto-discovers it.
    # The generated-v* directories are gitignored, so writing here is safe.
    # If a conftest already exists there, we temporarily append our hooks and
    # restore the original afterwards.
    suite_conftest = suite_dir / "conftest.py"
    original_content: str | None = None
    try:
        if suite_conftest.exists():
            original_content = suite_conftest.read_text()
            suite_conftest.write_text(
                original_content
                + "\n\n# --- injected by run_external_tests.py (L53) ---\n"
                + build_conftest_injection(gateway_url)
            )
        else:
            suite_conftest.write_text(build_conftest_injection(gateway_url))

        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{suite_dir.parent.parent}:{existing_pp}"

        cmd = [
            _get_pytest_python(), "-m", "pytest",
            "--tb=no",       # no tracebacks — keep output compact
            "-q",            # quiet
            "--no-header",
            "--import-mode=importlib",
            f"--rootdir={suite_dir}",
            str(suite_dir),
        ]

        start = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,   # 5 min (9 tests × 30s httpx timeout = 270s worst case)
                env=env,
                cwd=str(suite_dir),
            )
            duration = time.monotonic() - start
        except subprocess.TimeoutExpired:
            return {
                "service": service_name,
                "suite": suite,
                "status": "timeout",
                "passed": 0,
                "failed": 0,
                "errors": 1,
                "duration_s": 300.0,
            }
    finally:
        # Restore original conftest or remove injected one
        if original_content is not None:
            suite_conftest.write_text(original_content)
        elif suite_conftest.exists():
            suite_conftest.unlink()

    # Parse pytest output for counts
    passed = failed = errors = 0
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        # pytest -q summary line: "3 passed, 1 failed in 2.31s"
        if " passed" in line or " failed" in line or " error" in line:
            import re
            m = re.findall(r"(\d+) (passed|failed|error)", line)
            for count, label in m:
                if label == "passed":
                    passed += int(count)
                elif label == "failed":
                    failed += int(count)
                elif label == "error":
                    errors += int(count)

    overall = "passed" if result.returncode == 0 else ("failed" if failed > 0 else "error")

    return {
        "service": service_name,
        "suite": suite,
        "status": overall,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "duration_s": round(duration, 2),
        "returncode": result.returncode,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="External CI/CD runner — 4 test suites against live gateway (L53)"
    )
    parser.add_argument(
        "--gateway",
        default=os.environ.get("JTP_GATEWAY_URL", DEFAULT_GATEWAY),
        help=f"Live gateway URL (default: {DEFAULT_GATEWAY})",
    )
    parser.add_argument(
        "--suites",
        nargs="+",
        default=EXTERNAL_SUITES,
        choices=EXTERNAL_SUITES,
        help="Suites to run (default: all 4 external suites)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--services",
        nargs="+",
        default=None,
        help="Specific service names to test (default: all 219)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"JSON report output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print job list without running tests",
    )
    args = parser.parse_args()

    # Preflight: find pytest-capable python
    try:
        py = _get_pytest_python()
        print(f"[L53] Using python: {py}")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    # Resolve services
    services_dir = get_services_dir()
    all_services = list_services(services_dir)
    target_services = args.services if args.services else all_services
    unknown = set(target_services) - set(all_services)
    if unknown:
        print(f"ERROR: Unknown services: {sorted(unknown)}", file=sys.stderr)
        sys.exit(1)

    # Build job list
    jobs = [
        (svc, suite)
        for svc in target_services
        for suite in args.suites
    ]

    print(f"[L53] External CI/CD runner")
    print(f"      Gateway : {args.gateway}")
    print(f"      Services: {len(target_services)}")
    print(f"      Suites  : {args.suites}")
    print(f"      Jobs    : {len(jobs)}")
    print(f"      Workers : {args.workers}")
    print()

    if args.dry_run:
        for svc, suite in jobs:
            print(f"  {svc}/{suite}")
        return

    # Create output dir
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Temporary dir for conftest injection (shared reference, content generated per job)
    results: list[dict] = []
    start_total = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_to_job = {
            pool.submit(
                run_suite_for_service,
                svc, suite, services_dir, args.gateway
            ): (svc, suite)
            for svc, suite in jobs
        }

        completed = 0
        for future in as_completed(future_to_job):
            completed += 1
            svc, suite = future_to_job[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "service": svc,
                    "suite": suite,
                    "status": "exception",
                    "error": str(exc),
                    "passed": 0,
                    "failed": 0,
                    "errors": 1,
                    "duration_s": 0.0,
                }
            results.append(result)

            status_icon = {"passed": "✓", "failed": "✗", "skipped": "-", "error": "!", "timeout": "T", "exception": "E"}.get(result["status"], "?")
            print(
                f"  [{completed:4d}/{len(jobs)}] {status_icon} {svc}/{suite} "
                f"({result['passed']}p/{result['failed']}f/{result['errors']}e "
                f"{result['duration_s']}s)"
            )

    total_duration = round(time.monotonic() - start_total, 1)

    # Aggregate
    total_passed  = sum(r["passed"] for r in results)
    total_failed  = sum(r["failed"] for r in results)
    total_errors  = sum(r["errors"] for r in results)
    total_skipped = sum(1 for r in results if r["status"] == "skipped")
    job_passed    = sum(1 for r in results if r["status"] == "passed")
    job_failed    = sum(1 for r in results if r["status"] in ("failed", "error", "timeout", "exception"))

    report = {
        "runner": "run_external_tests.py",
        "lesson": "L53",
        "gateway": args.gateway,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_s": total_duration,
        "summary": {
            "services": len(target_services),
            "suites": args.suites,
            "total_jobs": len(jobs),
            "jobs_passed": job_passed,
            "jobs_failed": job_failed,
            "jobs_skipped": total_skipped,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_errors": total_errors,
        },
        "results": sorted(results, key=lambda r: (r["service"], r["suite"])),
    }

    output_path.write_text(json.dumps(report, indent=2))

    print()
    print("─" * 60)
    print(f"[L53] External CI/CD Results")
    print(f"      Duration : {total_duration}s")
    print(f"      Jobs     : {job_passed} passed / {job_failed} failed / {total_skipped} skipped")
    print(f"      Tests    : {total_passed} passed / {total_failed} failed / {total_errors} errors")
    print(f"      Report   : {output_path}")
    print("─" * 60)

    # Exit non-zero if any jobs failed
    sys.exit(0 if job_failed == 0 else 1)


if __name__ == "__main__":
    main()
