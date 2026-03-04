"""Integration tests for encryption_service_communication.
Port: 8132 | Tier: large | Namespace: jtp
Plan 123 Phase 3 — domain endpoint tests + harmony integration check.
"""
import pytest, httpx, os

SERVICE_PORT   = 8132
RESOURCE_TIER  = "large"
K8S_NAMESPACE  = "jtp"


class TestEncryptionServiceCommunicationIntegration:

    @pytest.fixture
    def base_url(self):
        return os.environ.get("SERVICE_BASE_URL", f"http://localhost:{SERVICE_PORT}")

    def test_health_check(self, base_url):
        try:
            r = httpx.get(f"{base_url}/health", timeout=10.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
            assert r.json()["resource_tier"] == RESOURCE_TIER
        except httpx.ConnectError:
            pytest.skip('Service not running')

    def test_template_is_not_unknown(self, base_url):
        try:
            r = httpx.get(f"{base_url}/", timeout=10.0)
            assert r.status_code == 200
            assert r.json().get("template", "unknown") != "unknown", "PLAN 123 VIOLATION"
        except httpx.ConnectError:
            pytest.skip('Service not running')

    def test_all_registries_present(self, base_url):
        try:
            r = httpx.get(f"{base_url}/", timeout=10.0)
            sources = r.json().get("registry_sources", {})
            assert len(sources) == 6, f"Expected 6 registries, got {len(sources)}"
        except httpx.ConnectError:
            pytest.skip('Service not running')

    def test_variables_loaded(self, base_url):
        try:
            r = httpx.get(f"{base_url}/", timeout=10.0)
            vars_loaded = r.json().get("variables_loaded", [])
            assert "api_timeout" in vars_loaded
            assert "log_level" in vars_loaded
        except httpx.ConnectError:
            pytest.skip('Service not running')

    def test_domain_endpoint_security_status(self, base_url):
        """Integration: GET /security/status responds correctly."""
        try:
            r = httpx.get(f"{base_url}/security/status", timeout=10.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Domain endpoint /security/status returned {r.status_code}"
            data = r.json()
            assert data is not None
            assert "service" in data, "Response must include service key"
        except httpx.ConnectError:
            pytest.skip('Service not running')

    def test_domain_endpoint_security_scan(self, base_url):
        """Integration: POST /security/scan responds correctly."""
        try:
            r = httpx.post(f"{base_url}/security/scan", json={}, timeout=10.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Domain endpoint /security/scan returned {r.status_code}"
            data = r.json()
            assert data is not None
            assert "service" in data, "Response must include service key"
        except httpx.ConnectError:
            pytest.skip('Service not running')

    def test_domain_endpoint_threats(self, base_url):
        """Integration: GET /threats responds correctly."""
        try:
            r = httpx.get(f"{base_url}/threats", timeout=10.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Domain endpoint /threats returned {r.status_code}"
            data = r.json()
            assert data is not None
            assert "service" in data, "Response must include service key"
        except httpx.ConnectError:
            pytest.skip('Service not running')

    def test_biological_harmony_integration(self, base_url):
        """Harmony from running service must meet GODHOOD threshold."""
        try:
            r = httpx.get(f"{base_url}/health", timeout=10.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Service not running')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
