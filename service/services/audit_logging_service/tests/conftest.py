"""Shared test fixtures for audit_logging_service.
Domain: compliance | Port: 8097 | NS: jtp
Plan 123 Phase 3 — conftest.py for all 6 test tiers.
"""
import os
import pytest
from pathlib import Path


# ── Session-scoped constants ────────────────────────────────────────

SERVICE_NAME   = "audit_logging_service"
SERVICE_PORT   = 8097
GATEWAY_URL    = "http://151.145.202.116:30671"
SERVICE_DOMAIN = "compliance"
HARMONY_TARGET = 0.997
RESOURCE_TIER  = "medium"
K8S_NAMESPACE  = "jtp"


@pytest.fixture(scope="session")
def service_name():
    return "audit_logging_service"


@pytest.fixture(scope="session")
def service_port():
    return 8097


@pytest.fixture(scope="session")
def gateway_url():
    return "http://151.145.202.116:30671"


@pytest.fixture(scope="session")
def service_base(gateway_url):
    return f"{gateway_url}/api/audit_logging_service"


@pytest.fixture(scope="module")
def app_client():
    """TestClient fixture — changes cwd to src/ so config.json is found."""
    src_dir = Path(__file__).parent.parent / "src"
    original_cwd = os.getcwd()
    os.chdir(src_dir)
    try:
        from fastapi.testclient import TestClient
        import importlib, sys
        # Remove cached main module to allow fresh import
        for mod in list(sys.modules.keys()):
            if mod in ("main", "models"):
                del sys.modules[mod]
        sys.path.insert(0, str(src_dir))
        from main import app
        yield TestClient(app)
    finally:
        os.chdir(original_cwd)


@pytest.fixture(scope="session")
def auth_headers():
    """Mock auth headers for authenticated endpoint tests."""
    return {
        "Authorization": "Bearer test-token-jtp-audit_logging_service",
        "X-Service-Name": "audit_logging_service",
        "X-Domain": "compliance",
    }


@pytest.fixture(scope="session")
def test_user_id():
    return "user-test-jtp-001"


@pytest.fixture(scope="session")
def expected_service_meta():
    """Expected metadata that every endpoint response should contain."""
    return {
        "service": "audit_logging_service",
        "domain": "compliance",
        "resource_tier": "medium",
        "port": 8097,
        "harmony_target": 0.997,
    }
