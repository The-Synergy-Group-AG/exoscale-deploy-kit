"""Shared test fixtures for cellular_communication_network_category.
Domain: biological | Port: 8297 | NS: jtp
Plan 123 Phase 3 — conftest.py for all 6 test tiers.
"""
import os
import pytest
from pathlib import Path


# ── Session-scoped constants ────────────────────────────────────────

SERVICE_NAME   = "cellular_communication_network_category"
SERVICE_PORT   = 8297
GATEWAY_URL    = "http://151.145.202.116:30671"
SERVICE_DOMAIN = "biological"
HARMONY_TARGET = 0.997
RESOURCE_TIER  = "large"
K8S_NAMESPACE  = "jtp"


@pytest.fixture(scope="session")
def service_name():
    return "cellular_communication_network_category"


@pytest.fixture(scope="session")
def service_port():
    return 8297


@pytest.fixture(scope="session")
def gateway_url():
    return "http://151.145.202.116:30671"


@pytest.fixture(scope="session")
def service_base(gateway_url):
    return f"{gateway_url}/api/cellular_communication_network_category"


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
        "Authorization": "Bearer test-token-jtp-cellular_communication_network_category",
        "X-Service-Name": "cellular_communication_network_category",
        "X-Domain": "biological",
    }


@pytest.fixture(scope="session")
def test_user_id():
    return "user-test-jtp-001"


@pytest.fixture(scope="session")
def expected_service_meta():
    """Expected metadata that every endpoint response should contain."""
    return {
        "service": "cellular_communication_network_category",
        "domain": "biological",
        "resource_tier": "large",
        "port": 8297,
        "harmony_target": 0.997,
    }
