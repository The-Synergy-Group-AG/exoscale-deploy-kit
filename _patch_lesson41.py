#!/usr/bin/env python3
"""Patch teardown.py with LESSON 41: Instance Pool escalation after persistent 409."""
from pathlib import Path

f = Path("teardown.py")
src = f.read_text()

# ── Patch 1: add forbidden_consecutive counter after MAX_ATTEMPTS = 12 ──────
OLD1 = "    MAX_ATTEMPTS = 12\n\n    for attempt in range(1, MAX_ATTEMPTS + 1):"
NEW1 = (
    "    MAX_ATTEMPTS = 12\n"
    "    # LESSON 41: Distinguish transient 409 (race condition) from persistent-forbidden 409\n"
    "    # (Instance Pool locked). After FORBIDDEN_ESCALATE_AFTER consecutive cycles where\n"
    "    # state=\"running\" but DELETE returns 409 \"forbidden\", the API is genuinely refusing.\n"
    "    # In this case, NEVER delete individual instances — the Instance Pool recreates them.\n"
    "    # Escalate with console path: Compute -> Instance Pools -> delete pool manually.\n"
    "    forbidden_consecutive = 0\n"
    "    FORBIDDEN_ESCALATE_AFTER = 3\n"
    "\n"
    "    for attempt in range(1, MAX_ATTEMPTS + 1):"
)

if OLD1 not in src:
    print("PATCH 1 FAILED: target text not found")
    exit(1)
src = src.replace(OLD1, NEW1, 1)
print("Patch 1 OK")

# ── Patch 2: replace the 409/400 retry block with LESSON 41 escalation ───────
OLD2 = (
    '            if ("409" in err_str or "400" in err_str) and attempt < MAX_ATTEMPTS:\n'
    '                # LESSON 40b: min(attempt\u00d760, 300) gives 60s, 120s, 180s, 240s, 300s, 300s...\n'
    '                wait_s = min(attempt * 60, 300)\n'
    '                warn(f"Nodepool {pool_name}: conflict (attempt {attempt}/{MAX_ATTEMPTS}) "\n'
    '                     f"\u2014 VMs still deprovisioning, backing off {wait_s}s...")\n'
    '                time.sleep(wait_s)\n'
    '            else:\n'
    '                warn(f"Nodepool {pool_name}: {err_str[:120]}")\n'
    '                results["errors"].append({"type": "nodepool", "id": pool_id, "error": err_str[:120]})\n'
    '                return False'
)

NEW2 = (
    '            if ("409" in err_str or "400" in err_str) and attempt < MAX_ATTEMPTS:\n'
    '                # LESSON 40b: min(attempt\u00d760, 300) gives 60s, 120s, 180s, 240s, 300s, 300s...\n'
    '                wait_s = min(attempt * 60, 300)\n'
    '                # LESSON 41: track consecutive "state=running + 409 forbidden" cycles.\n'
    '                # Transient 409 clears when the deprovisioning window ends (backoff handles it).\n'
    '                # Persistent 409 = Instance Pool locked \u2014 escalate after 3 consecutive cycles.\n'
    '                if "forbidden" in err_str.lower():\n'
    '                    forbidden_consecutive += 1\n'
    '                    if forbidden_consecutive >= FORBIDDEN_ESCALATE_AFTER:\n'
    '                        warn(f"Nodepool {pool_name}: 409 \'forbidden\' on {forbidden_consecutive} "\n'
    '                             f"consecutive attempts \u2014 Exoscale Instance Pool is locked.")\n'
    '                        warn("  The API is refusing deletion; retrying will not help.")\n'
    '                        warn("  MANUAL ACTION REQUIRED:")\n'
    '                        warn("  1. Open https://portal.exoscale.com")\n'
    '                        warn("  2. Navigate: Compute -> Instance Pools")\n'
    '                        warn(f"  3. Find and delete the pool: {pool_name}")\n'
    '                        warn("  4. Wait for all instances to terminate (~2-5 min)")\n'
    '                        warn("  5. Re-run: python3 teardown.py --force")\n'
    '                        results["errors"].append({\n'
    '                            "type": "nodepool", "id": pool_id, "name": pool_name,\n'
    '                            "error": "Instance Pool locked \u2014 manual console deletion required: "\n'
    '                                     "Compute -> Instance Pools -> delete " + pool_name\n'
    '                        })\n'
    '                        return False\n'
    '                else:\n'
    '                    forbidden_consecutive = 0  # reset on non-forbidden 409\n'
    '                warn(f"Nodepool {pool_name}: conflict (attempt {attempt}/{MAX_ATTEMPTS}) "\n'
    '                     f"\u2014 backing off {wait_s}s...")\n'
    '                time.sleep(wait_s)\n'
    '            else:\n'
    '                warn(f"Nodepool {pool_name}: {err_str[:120]}")\n'
    '                results["errors"].append({"type": "nodepool", "id": pool_id, "error": err_str[:120]})\n'
    '                return False'
)

if OLD2 not in src:
    print("PATCH 2 FAILED: target text not found")
    # Debug: show the actual text at that region
    idx = src.find('if ("409" in err_str')
    if idx >= 0:
        print("Found 409 block at char", idx, ":")
        print(repr(src[idx:idx+300]))
    exit(1)
src = src.replace(OLD2, NEW2, 1)
print("Patch 2 OK")

f.write_text(src)
print(f"teardown.py patched: {len(src.splitlines())} lines")
