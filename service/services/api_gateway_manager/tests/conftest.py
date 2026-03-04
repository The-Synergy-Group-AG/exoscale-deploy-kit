"""Shared test fixtures for api_gateway_manager.
Domain: security | Port: 8102 | NS: jtp
Plan 123 Phase 3 — conftest.py for all 6 test tiers.
"""
import os
import pytest
from pathlib import Path


# ── Session-scoped constants ────────────────────────────────────────

SERVICE_NAME   = "api_gateway_manager"
SERVICE_PORT   = 8102
GATEWAY_URL    = "http://151.145.202.116:30671"
SERVICE_DOMAIN = "security"
HARMONY_TARGET = 0.997
RESOURCE_TIER  = "large"
K8S_NAMESPACE  = "jtp"


@pytest.fixture(scope="session")
def service_name():
    return "api_gateway_manager"


@pytest.fixture(scope="session")
def service_port():
    return 8102


@pytest.fixture(scope="session")
def gateway_url():
    return "http://151.145.202.116:30671"


@pytest.fixture(scope="session")
def service_base(gateway_url):
    return f"{gateway_url}/api/api_gateway_manager"


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
        "Authorization": "Bearer test-token-jtp-api_gateway_manager",
        "X-Service-Name": "api_gateway_manager",
        "X-Domain": "security",
    }


@pytest.fixture(scope="session")
def test_user_id():
    return "user-test-jtp-001"


@pytest.fixture(scope="session")
def expected_service_meta():
    """Expected metadata that every endpoint response should contain."""
    return {
        "service": "api_gateway_manager",
        "domain": "security",
        "resource_tier": "large",
        "port": 8102,
        "harmony_target": 0.997,
    }
