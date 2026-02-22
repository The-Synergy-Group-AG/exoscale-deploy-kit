#!/usr/bin/env python3
"""Phase 1 Validation Script — Exoscale Deploy Kit
Scans only actual deliverable files (not this script itself).
"""
import subprocess
import sys
from pathlib import Path

kit = Path(__file__).parent
errors = []

# Deliverable files only — explicitly listed to avoid self-contamination
DELIVERABLES = [
    kit / "config.yaml",
    kit / "config_loader.py",
    kit / ".env.example",
    kit / ".gitignore",
    kit / "requirements.txt",
]


def grep_deliverables(pattern: str) -> list[str]:
    """Search pattern across deliverable files only (not this validator)."""
    hits = []
    for f in DELIVERABLES:
        r = subprocess.run(["grep", "-n", pattern, str(f)], capture_output=True, text=True)
        if r.stdout.strip():
            hits.append(f"{f.name}: {r.stdout.strip()}")
    return hits


print("=" * 44)
print("  PHASE 1 VALIDATION SUITE")
print("=" * 44)

# ── Check 5: JTP reference scan ──────────────────
print("\n5. JTP reference scan (deliverables only):")
JTP_PATTERNS = [
    "jtp-bio", "jtp_bio",
    "iandre",
    "EXO" + "cf9a",    # split to avoid self-match in this script
    "dckr_pat_F",
]
all_hits: list[str] = []
for pat in JTP_PATTERNS:
    all_hits.extend(grep_deliverables(pat))

if not all_hits:
    print("  PASS -- zero JTP-specific references found in deliverables")
else:
    print("  FAIL -- JTP REFERENCES FOUND:")
    for h in all_hits:
        print(f"    {h}")
    errors.append("JTP references found in deliverables")

# ── Check 6: No real credentials ─────────────────
print("\n6. Credential check (deliverables only):")
CRED_FRAGMENTS = [
    "EXO" + "cf9a39124b22090c956b6a94",   # split to avoid self-match
    "ZUlcx5CUfTZPq7",
    "dckr_pat_FSeKGd",
]
cred_hits: list[str] = []
for pat in CRED_FRAGMENTS:
    cred_hits.extend(grep_deliverables(pat))

if not cred_hits:
    print("  PASS -- no real credentials found in deliverables")
else:
    print("  FAIL -- REAL CREDENTIALS FOUND:")
    for c in cred_hits:
        print(f"    {c}")
    errors.append("Real credentials found in deliverables")

# ── Check 7: .env.example credential keys ────────
print("\n7. .env.example credential keys:")
env_ex = (kit / ".env.example").read_text()
for k in ["EXO_API_KEY", "EXO_API_SECRET", "DOCKER_HUB_TOKEN"]:
    if k in env_ex:
        print(f"  PASS -- {k} present")
    else:
        print(f"  FAIL -- {k} MISSING")
        errors.append(f"{k} missing from .env.example")

# ── Check 8: requirements.txt packages ───────────
print("\n8. requirements.txt packages:")
reqs = (kit / "requirements.txt").read_text()
for pkg in ["exoscale", "boto3", "requests", "PyYAML"]:
    if pkg in reqs:
        print(f"  PASS -- {pkg} present")
    else:
        print(f"  FAIL -- {pkg} MISSING")
        errors.append(f"{pkg} missing from requirements.txt")

# ── Check 9: .gitignore critical entries ─────────
print("\n9. .gitignore critical entries:")
gi = (kit / ".gitignore").read_text()
for entry in [".env", "outputs/", "*.kubeconfig", "__pycache__/"]:
    if entry in gi:
        print(f"  PASS -- {entry} excluded")
    else:
        print(f"  FAIL -- {entry} NOT excluded")
        errors.append(f"{entry} missing from .gitignore")

# ── Final result ──────────────────────────────────
print("\n" + "=" * 44)
if not errors:
    print("  ALL QUALITY GATES PASSED -- Phase 1 COMPLETE")
    print("  QG-STRUCT: PASS")
    print("  QG-CONFIG: PASS")
    print("  QG-CLEAN:  PASS")
else:
    print(f"  {len(errors)} issue(s) found:")
    for e in errors:
        print(f"    - {e}")
    sys.exit(1)
print("=" * 44)
