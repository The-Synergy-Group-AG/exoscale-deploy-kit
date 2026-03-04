"""Shared test fixtures for service_health_monitor.
Domain: monitoring | Port: 8250 | NS: jtp
Plan 123 Phase 3 — conftest.py for all 6 test tiers.
"""
import os
import pytest
from pathlib import Path


# ── Session-scoped constants ────────────────────────────────────────

SERVICE_NAME   = "service_health_monitor"
SERVICE_PORT   = 8250
GATEWAY_URL    = "http://151.145.202.116:30671"
SERVICE_DOMAIN = "monitoring"
HARMONY_TARGET = 0.997
RESOURCE_TIER  = "small"
K8S_NAMESPACE  = "jtp"


@pytest.fixture(scope="session")
def service_name():
    return "service_health_monitor"


@pytest.fixture(scope="session")
def service_port():
    return 8250


@pytest.fixture(scope="session")
def gateway_url():
    return "http://151.145.202.116:30671"


@pytest.fixture(scope="session")
def service_base(gateway_url):
    return f"{gateway_url}/api/service_health_monitor"


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
        "Authorization": "Bearer test-token-jtp-service_health_monitor",
        "X-Service-Name": "service_health_monitor",
        "X-Domain": "monitoring",
    }


@pytest.fixture(scope="session")
def test_user_id():
    return "user-test-jtp-001"


@pytest.fixture(scope="session")
def expected_service_meta():
    """Expected metadata that every endpoint response should contain."""
    return {
        "service": "service_health_monitor",
        "domain": "monitoring",
        "resource_tier": "small",
        "port": 8250,
        "harmony_target": 0.997,
    }
