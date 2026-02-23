#!/usr/bin/env python3
"""Phase 3 Validation — Full Kit-Wide Self-Containment Check"""
import subprocess
import sys
from pathlib import Path

kit = Path(__file__).parent
PASS = 0
FAIL = 0


def check(label: str, ok: bool) -> None:
    global PASS, FAIL
    if ok:
        print(f"  OK   {label}")
        PASS += 1
    else:
        print(f"  FAIL {label}")
        FAIL += 1


def exists(p: str) -> bool:
    return (kit / p).exists()


def syntax(p: str) -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "py_compile", str(kit / p)], capture_output=True
    )
    return r.returncode == 0


def no_grep(pattern: str) -> bool:
    """Return True if pattern NOT found in kit files.
    Excludes: __pycache__/, validate_phase*.py, .env (credentials file).
    Pure Python — no grep binary needed (Windows-compatible).
    """
    EXCLUDE_FILES = {
        "validate_phase1.py", "validate_phase2.py", "validate_phase3.py",
        ".env",  # credentials file — intentionally contains real values
    }
    for f in kit.rglob("*"):
        if not f.is_file():
            continue
        if "__pycache__" in f.parts:
            continue
        if f.name in EXCLUDE_FILES:
            continue
        try:
            if pattern in f.read_text(encoding="utf-8", errors="ignore"):
                return False
        except Exception:
            pass
    return True


print("=" * 52)
print("  PHASE 3 — FULL KIT VALIDATION")
print("=" * 52)

# ── File existence ─────────────────────────────────────
print("\nFile existence:")
REQUIRED_FILES = [
    "deploy_pipeline.py",
    "teardown.py",
    "k8s_manifest_generator.py",
    "config_loader.py",
    "config.yaml",
    ".env.example",
    ".gitignore",
    "requirements.txt",
    "README.md",
    "service/app.py",
    "service/Dockerfile",
    "service/requirements.txt",
]
for f in REQUIRED_FILES:
    check(f"{f} exists", exists(f))

# ── Python syntax ──────────────────────────────────────
print("\nPython syntax:")
PYTHON_FILES = [
    "deploy_pipeline.py",
    "teardown.py",
    "k8s_manifest_generator.py",
    "config_loader.py",
    "service/app.py",
]
for f in PYTHON_FILES:
    check(f"{f} syntax OK", syntax(f))

# ── Zero JTP references (excl. __pycache__ + validate scripts) ──
print("\nZero JTP references (kit-wide, excl. __pycache__ + validate scripts):")
check("No jtp-bio references", no_grep("jtp-bio"))
check("No jtp_bio references", no_grep("jtp_bio"))
check("No /home/iandre paths", no_grep("/home/iandre"))
check("No real EXO key", no_grep("EXOcf9a39124b22090c956b6a94"))
check("No real Docker token", no_grep("dckr_pat_FSeKGd"))
check("No PORT_REGISTRY dependency", no_grep("PORT_REGISTRY"))
check("No load_port_from_registry", no_grep("load_port_from_registry"))

# ── Config completeness ────────────────────────────────
print("\nConfig completeness:")
cfg = (kit / "config.yaml").read_text()
for key in [
    "project_name", "service_name", "docker_hub_user",
    "exoscale_zone", "k8s_namespace", "k8s_nodeport",
    "node_count", "k8s_port",
]:
    check(f"config.yaml has {key}", f"{key}:" in cfg)

# ── README quality ─────────────────────────────────────
print("\nREADME quality:")
readme = (kit / "README.md").read_text()
check("README has What This Kit Does", "What This Kit Does" in readme)
check("README has Prerequisites", "Prerequisites" in readme)
check("README has Quick Start", "Quick Start" in readme)
check("README has Configuration Reference", "Configuration Reference" in readme)
check("README has 12 Critical Lessons", "12 Critical Lessons" in readme)
check("README has Troubleshooting", "Troubleshooting" in readme)
check("README has Cost Reference", "Cost Reference" in readme)
check("README has Kit Structure", "Kit Structure" in readme)

lesson_count = sum(1 for i in range(1, 13) if f"### {i}." in readme)
check(f"README has all 12 lessons ({lesson_count}/12 found)", lesson_count == 12)

readme_jtp = "jtp-bio" not in readme.lower() and "jtp_bio" not in readme.lower()
check("README has no JTP branding", readme_jtp)

# ── Service files ──────────────────────────────────────
print("\nService files:")
app_py = (kit / "service/app.py").read_text()
check(
    "service/app.py no JTP branding",
    "jtp-bio" not in app_py and "deployment-engine-test-service" not in app_py,
)
check("service/app.py has /health endpoint", "/health" in app_py)
check("service/app.py uses SERVICE_NAME env var", "SERVICE_NAME" in app_py)

# ── Gitignore ──────────────────────────────────────────
print("\nGitignore:")
gi = (kit / ".gitignore").read_text()
check(".gitignore excludes .env", ".env" in gi)
check(".gitignore excludes outputs/", "outputs/" in gi)
check(".gitignore excludes kubeconfig", "kubeconfig" in gi)

# ── Final result ───────────────────────────────────────
print()
print("=" * 52)
print(f"  RESULTS: {PASS} passed | {FAIL} failed")
if FAIL == 0:
    print("  KIT IS SELF-CONTAINED AND READY")
    print("  QG-SERVICE:  PASS")
    print("  QG-README:   PASS")
    print("  QG-KITCLEAN: PASS")
    print("  Phase 3 COMPLETE")
else:
    print("  Fix failures before marking complete")
    sys.exit(1)
print("=" * 52)
