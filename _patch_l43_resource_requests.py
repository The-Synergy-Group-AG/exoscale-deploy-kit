#!/usr/bin/env python3
"""
L43 Patch: gen_service_manifests.py — always use DEPLOY_RESOURCES for requests.

The service engine generates config.json with production-grade resource requests
(cpu_request: "250m", memory_request: "512Mi").  gen_service_manifests.py was
trusting those values, saturating the 3-node test cluster.

Fix: load_service_resources() now ignores the cpu_request/memory_request from
config.json and always uses DEPLOY_RESOURCES (10m / 64Mi).  Limits from config
are preserved so individual services can still burst.
"""
import re, sys
from pathlib import Path

TARGET = Path(__file__).parent / "gen_service_manifests.py"
text   = TARGET.read_text(encoding="utf-8")

OLD = '''def load_service_resources(service_name: str) -> dict[str, str]:
    """Load resource specification from a service's config.json.

    Prefers individual cpu_request/memory_request/cpu_limit/memory_limit fields.
    Falls back to resource_tier lookup. Falls back to RESOURCE_FALLBACK if
    config.json is absent or malformed.

    Args:
        service_name: Filesystem name of the service directory

    Returns:
        Dict with keys: cpu_request, memory_request, cpu_limit, memory_limit
    """
    config_path = SERVICES_DIR / service_name / "config.json"
    if not config_path.exists():
        return RESOURCE_FALLBACK.copy()

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return RESOURCE_FALLBACK.copy()

    # Prefer explicit resource fields over tier lookup
    has_explicit = all(
        k in cfg for k in ("cpu_request", "memory_request", "cpu_limit", "memory_limit")
    )
    if has_explicit:
        return {
            "cpu_request":    str(cfg["cpu_request"]),
            "memory_request": str(cfg["memory_request"]),
            "cpu_limit":      str(cfg["cpu_limit"]),
            "memory_limit":   str(cfg["memory_limit"]),
        }

    # Fall back to tier
    tier = cfg.get("resource_tier", "small")
    return RESOURCE_TIERS.get(tier, RESOURCE_FALLBACK).copy()'''

NEW = '''def load_service_resources(service_name: str) -> dict[str, str]:
    """Return deploy-time safe resource spec for a service.

    LESSON 43: The service engine generates config.json with production-grade
    requests (cpu_request: "250m", memory_request: "512Mi").  Trusting those
    values saturates a 3-node test cluster after ~61 pods.

    Fix: requests are ALWAYS overridden to DEPLOY_RESOURCES safe values
    (10m CPU / 64Mi memory).  Limits are preserved from config.json when
    present so individual services can still burst up to their allocation.

    Args:
        service_name: Filesystem name of the service directory

    Returns:
        Dict with keys: cpu_request, memory_request, cpu_limit, memory_limit
    """
    # Always start from deploy-time safe requests
    result = DEPLOY_RESOURCES.copy()

    config_path = SERVICES_DIR / service_name / "config.json"
    if not config_path.exists():
        return result

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return result

    # Preserve limits from service config (generous limits are fine)
    # but NEVER trust the service-engine cpu_request/memory_request —
    # those are production-scale values, not test-cluster values.
    if "cpu_limit" in cfg:
        result["cpu_limit"] = str(cfg["cpu_limit"])
    if "memory_limit" in cfg:
        result["memory_limit"] = str(cfg["memory_limit"])

    return result'''

if OLD not in text:
    print("ERROR: SEARCH block not found in gen_service_manifests.py — aborting")
    sys.exit(1)

patched = text.replace(OLD, NEW, 1)
TARGET.write_text(patched, encoding="utf-8")
print(f"OK  patched {TARGET} ({TARGET.stat().st_size} bytes)")
