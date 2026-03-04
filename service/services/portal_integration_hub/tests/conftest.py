"""Shared test fixtures for portal_integration_hub.
Domain: workflow | Port: 8273 | NS: jtp
Plan 123 Phase 3 — conftest.py for all 6 test tiers.
"""
import os
import pytest
from pathlib import Path


# ── Session-scoped constants ────────────────────────────────────────

SERVICE_NAME   = "portal_integration_hub"
SERVICE_PORT   = 8273
GATEWAY_URL    = "http://151.145.202.116:30671"
SERVICE_DOMAIN = "workflow"
HARMONY_TARGET = 0.997
RESOURCE_TIER  = "medium"
K8S_NAMESPACE  = "jtp"


@pytest.fixture(scope="session")
def service_name():
    return "portal_integration_hub"


@pytest.fixture(scope="session")
def service_port():
    return 8273


@pytest.fixture(scope="session")
def gateway_url():
    return "http://151.145.202.116:30671"


@pytest.fixture(scope="session")
def service_base(gateway_url):
    return f"{gateway_url}/api/portal_integration_hub"


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
        "Authorization": "Bearer test-token-jtp-portal_integration_hub",
        "X-Service-Name": "portal_integration_hub",
        "X-Domain": "workflow",
    }


@pytest.fixture(scope="session")
def test_user_id():
    return "user-test-jtp-001"


@pytest.fixture(scope="session")
def expected_service_meta():
    """Expected metadata that every endpoint response should contain."""
    return {
        "service": "portal_integration_hub",
        "domain": "workflow",
        "resource_tier": "medium",
        "port": 8273,
        "harmony_target": 0.997,
    }
