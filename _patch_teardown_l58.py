#!/usr/bin/env python3
"""
Patch teardown.py — Lesson 58 fixes for correct teardown sequence.

Two bugs fixed:

BUG 1 — NLB discovery too narrow (LESSON 32 / LESSON 43 regression):
  teardown.py filters NLBs by project name:
    proj_nlbs = [n for n in nlb_list if project in n.get("name", "")]
  K8s CCM creates NLBs named "kubernetes-<hash>" — NO project prefix.
  These NLBs lock the nodepool, causing 409 "forbidden" on every delete attempt.
  Fix: discover ALL NLBs in the zone, not just project-named ones.
  (_nuke_all.py already does this correctly — align teardown.py with it.)

BUG 2 — FORBIDDEN_ESCALATE_AFTER = 3 too low (LESSON 41 over-eager):
  After 3 consecutive 409 "forbidden" responses the script gives up and
  prints "Instance Pool is locked — MANUAL ACTION REQUIRED".
  But VMs take 5-10 min to deprovision after namespace deletion;
  3 consecutive 409s in the first 3-7 minutes is NORMAL, not a stuck lock.
  With exponential backoff (60s, 120s, 180s...) the 3-attempt threshold is
  hit at ~7 min — before Exoscale has finished stopping the VMs.
  Fix: raise FORBIDDEN_ESCALATE_AFTER to MAX_ATTEMPTS (12) so all 12
  retry slots run before escalating.  If all 12 fail (~34 min patience)
  the existing "exhausted N attempts" error at the bottom fires instead.
"""

from pathlib import Path

TEARDOWN = Path(__file__).parent / "teardown.py"
src = TEARDOWN.read_text(encoding="utf-8")
orig = src

# ── FIX 1: Discover ALL NLBs (no project-name filter) ────────────────────────
OLD_NLB_FILTER = (
    "    # Find NLBs matching {project_name}-*\n"
    "    nlb_list  = c.list_load_balancers().get(\"load-balancers\", [])\n"
    "    proj_nlbs = [n for n in nlb_list if project in n.get(\"name\", \"\")]"
)
NEW_NLB_FILTER = (
    "    # Find ALL NLBs — K8s CCM creates NLBs named 'kubernetes-<hash>',\n"
    "    # NOT prefixed with the project name. Filtering by project name misses\n"
    "    # these CCM NLBs which lock the nodepool (LESSON 32/43/58).\n"
    "    # _nuke_all.py already does this correctly — no name filter here.\n"
    "    nlb_list  = c.list_load_balancers().get(\"load-balancers\", [])\n"
    "    proj_nlbs = nlb_list  # ALL NLBs in zone — CCM ones have no project prefix"
)
assert OLD_NLB_FILTER in src, "BUG 1: old NLB filter not found — already patched?"
src = src.replace(OLD_NLB_FILTER, NEW_NLB_FILTER, 1)

# ── FIX 2: Raise FORBIDDEN_ESCALATE_AFTER from 3 to MAX_ATTEMPTS ─────────────
OLD_ESCALATE = "    FORBIDDEN_ESCALATE_AFTER = 3"
NEW_ESCALATE = (
    "    # LESSON 58: Was 3 — too low. VMs take 5-10 min to deprovision after\n"
    "    # namespace deletion; 3 consecutive 409s in the first 7 min is NORMAL.\n"
    "    # Run ALL 12 attempts before escalating to manual console path.\n"
    "    FORBIDDEN_ESCALATE_AFTER = MAX_ATTEMPTS  # 12"
)
assert OLD_ESCALATE in src, "BUG 2: old FORBIDDEN_ESCALATE_AFTER = 3 not found — already patched?"
src = src.replace(OLD_ESCALATE, NEW_ESCALATE, 1)

TEARDOWN.write_text(src, encoding="utf-8")

if src != orig:
    print("teardown.py patched successfully (2 fixes applied)")
    print("  FIX 1: NLB discovery now catches ALL NLBs (no project-name filter)")
    print("  FIX 2: FORBIDDEN_ESCALATE_AFTER raised from 3 → MAX_ATTEMPTS (12)")
else:
    print("ERROR: no changes were made — check assertions")
    raise SystemExit(1)
