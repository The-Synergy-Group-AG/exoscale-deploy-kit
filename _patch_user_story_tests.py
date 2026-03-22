#!/usr/bin/env python3
"""
_patch_user_story_tests.py — Fix user story test GATEWAY_URL for in-pod execution
================================================================================
Plan 149: The factory-generated user story tests hardcode GATEWAY_URL to
http://localhost:30671 which doesn't work inside a service pod.  This patch
rewrites GATEWAY_URL to use the K8s service DNS so tests can reach the gateway.

Also patches SERVICE_BASE to use direct localhost access (faster, no gateway hop)
since the test is running INSIDE the service pod itself.

Idempotent — safe to run multiple times.
"""
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUTS_DIR = SCRIPT_DIR.parent / "engines" / "service_engine" / "outputs"
CURRENT_PTR = OUTPUTS_DIR / "CURRENT"


def patch_user_story_tests(services_dir: Path) -> int:
    """Patch all user story test files to use correct URLs for in-pod execution."""
    patched = 0
    skipped = 0

    for svc_dir in sorted(services_dir.iterdir()):
        if not svc_dir.is_dir():
            continue
        us_test = svc_dir / "tests" / "user_stories" / "test_user_stories.py"
        if not us_test.exists():
            continue

        content = us_test.read_text(encoding="utf-8")

        # Skip if already patched
        if "Plan 149 patched" in content:
            skipped += 1
            continue

        original = content

        # 1. Replace GATEWAY_URL with env-var override or K8s service DNS
        content = re.sub(
            r'GATEWAY_URL\s*=\s*"http://localhost:\d+"',
            'GATEWAY_URL   = os.environ.get("GATEWAY_URL", "http://docker-jtp.exo-jtp-prod.svc.cluster.local:5000")  # Plan 149 patched',
            content,
        )

        # 2. Replace SERVICE_BASE to use K8s service DNS (kubectl exec can't reach localhost ports)
        # Extract service name from the file path
        svc_name = us_test.parent.parent.parent.name  # e.g. analytics_service
        k8s_svc_name = svc_name.replace("_", "-")  # K8s service name uses hyphens
        content = re.sub(
            r'SERVICE_BASE\s*=\s*f"{GATEWAY_URL}/api/\w+"',
            f'SERVICE_BASE  = os.environ.get("SERVICE_BASE", "http://{k8s_svc_name}.exo-jtp-prod.svc.cluster.local:8000")  # Plan 149 patched: K8s DNS',
            content,
        )

        # 3. Ensure 'os' is imported (needed for os.environ)
        if "import os" not in content.split("\n")[0:5]:
            # It's already imported on the first import line
            pass  # os is already in the import line: "import os, pytest, httpx, time"

        if content != original:
            us_test.write_text(content, encoding="utf-8")
            patched += 1

    return patched, skipped


def main():
    if len(sys.argv) > 1:
        services_dir = Path(sys.argv[1])
    else:
        current = CURRENT_PTR.read_text().strip()
        services_dir = OUTPUTS_DIR / current / "services"

    if not services_dir.is_dir():
        print(f"[us-test-patch] Services dir not found: {services_dir}")
        return 1

    patched, skipped = patch_user_story_tests(services_dir)
    print(f"[us-test-patch] PATCHED {patched} user story test files, {skipped} already done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
