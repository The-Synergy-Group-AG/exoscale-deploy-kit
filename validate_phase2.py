#!/usr/bin/env python3
"""Phase 2 Validation Script — Core Engine Extraction"""
import subprocess
import sys
from pathlib import Path

kit = Path(__file__).parent
errors = []

DELIVERABLES = [
    kit / "deploy_pipeline.py",
    kit / "teardown.py",
    kit / "k8s_manifest_generator.py",
]


def grep_files(pattern: str) -> list[str]:
    hits = []
    for f in DELIVERABLES:
        r = subprocess.run(["grep", "-n", pattern, str(f)], capture_output=True, text=True)
        if r.stdout.strip():
            hits.append(f"{f.name}: {r.stdout.strip()}")
    return hits


print("=" * 52)
print("  PHASE 2 VALIDATION SUITE — Core Engine Extraction")
print("=" * 52)

# ── Check 1: Python syntax ────────────────────────────────
print("\n1. Python syntax validation:")
for f in DELIVERABLES:
    r = subprocess.run([sys.executable, "-m", "py_compile", str(f)], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  PASS -- {f.name}: syntax OK")
    else:
        print(f"  FAIL -- {f.name}: {r.stderr.strip()[:120]}")
        errors.append(f"Syntax error in {f.name}")

# ── Check 2: JTP naming scan ─────────────────────────────
print("\n2. JTP naming scan (deliverables only):")
jtp_hits: list[str] = []
for pat in ["jtp-bio", "jtp_bio"]:
    jtp_hits.extend(grep_files(pat))
if not jtp_hits:
    print("  PASS -- zero jtp-bio/jtp_bio references found")
else:
    print("  FAIL -- JTP REFERENCES FOUND:")
    for h in jtp_hits:
        print(f"    {h}")
    errors.append("JTP naming references found")

# ── Check 3: Absolute path scan ──────────────────────────
print("\n3. Absolute path scan:")
path_hits: list[str] = []
for pat in ["/home/iandre", "jtp-bio-v3"]:
    path_hits.extend(grep_files(pat))
if not path_hits:
    print("  PASS -- zero absolute paths found")
else:
    print("  FAIL -- ABSOLUTE PATHS FOUND:")
    for h in path_hits:
        print(f"    {h}")
    errors.append("Absolute paths found")

# ── Check 4: Real credentials scan ───────────────────────
print("\n4. Real credential scan:")
CRED_FRAGS = [
    "EXO" + "cf9a39124b22090c956b6a94",
    "ZUlcx5CUfTZPq7",
    "dckr_pat_FSeKGd",
    "iandrewitz",
]
cred_hits: list[str] = []
for pat in CRED_FRAGS:
    cred_hits.extend(grep_files(pat))
if not cred_hits:
    print("  PASS -- no real credentials found")
else:
    print("  FAIL -- REAL CREDENTIALS FOUND:")
    for c in cred_hits:
        print(f"    {c}")
    errors.append("Real credentials found")

# ── Check 5: PORT_REGISTRY dependency removed ─────────────
print("\n5. PORT_REGISTRY dependency scan:")
pr_hits: list[str] = []
for pat in ["PORT_REGISTRY", "load_port_from_registry", "service_engine"]:
    pr_hits.extend(grep_files(pat))
if not pr_hits:
    print("  PASS -- no PORT_REGISTRY dependency found")
else:
    print("  FAIL -- PORT_REGISTRY REFERENCES FOUND:")
    for h in pr_hits:
        print(f"    {h}")
    errors.append("PORT_REGISTRY dependency still present")

# ── Check 6: config_loader imported in pipeline scripts ───
print("\n6. config_loader import check:")
for f in [kit / "deploy_pipeline.py", kit / "teardown.py"]:
    content = f.read_text()
    if "from config_loader import load_config" in content:
        print(f"  PASS -- {f.name}: config_loader imported")
    else:
        print(f"  FAIL -- {f.name}: config_loader NOT imported")
        errors.append(f"config_loader not imported in {f.name}")

# ── Check 7: CFG dict removed from pipeline ───────────────
print("\n7. Hardcoded CFG dict removed:")
cfgdict = (kit / "deploy_pipeline.py").read_text()
if "^CFG = {" not in cfgdict and 'CFG = {\n    # Docker' not in cfgdict:
    print("  PASS -- no hardcoded CFG dict found")
else:
    print("  FAIL -- old CFG dict still present")
    errors.append("Hardcoded CFG dict still in deploy_pipeline.py")

# ── Check 8: --nodeport arg in k8s_manifest_generator ─────
print("\n8. --nodeport argument in k8s_manifest_generator.py:")
kg = (kit / "k8s_manifest_generator.py").read_text()
if "--nodeport" in kg:
    print("  PASS -- --nodeport argument present")
else:
    print("  FAIL -- --nodeport argument MISSING")
    errors.append("--nodeport missing from k8s_manifest_generator.py")

# ── Check 9: k8s_manifest_generator --help ────────────────
print("\n9. k8s_manifest_generator.py --help:")
r = subprocess.run(
    [sys.executable, str(kit / "k8s_manifest_generator.py"), "--help"],
    capture_output=True, text=True,
)
if r.returncode == 0 and "--nodeport" in r.stdout:
    print("  PASS -- --help works and --nodeport visible")
else:
    print(f"  FAIL -- --help returncode={r.returncode}, nodeport in output={('--nodeport' in r.stdout)}")
    errors.append("k8s_manifest_generator.py --help failed or missing --nodeport")

# ── Final result ──────────────────────────────────────────
print("\n" + "=" * 52)
if not errors:
    print("  ALL QUALITY GATES PASSED -- Phase 2 COMPLETE")
    print("  QG-SYNTAX:    PASS")
    print("  QG-NOJTPREFS: PASS")
    print("  QG-NOCREDS:   PASS")
    print("  QG-NOPATHS:   PASS")
else:
    print(f"  {len(errors)} issue(s) found:")
    for e in errors:
        print(f"    - {e}")
    sys.exit(1)
print("=" * 52)
