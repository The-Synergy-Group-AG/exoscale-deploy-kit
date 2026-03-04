"""E2E tests for credits-redemption-frontend via gateway.
Port: 8108 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8108
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestCreditsRedemptionFrontendE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/credits-redemption-frontend/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/credits-redemption-frontend/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_root(self):
        """E2E: GET / through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/credits-redemption-frontend/", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint / returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_api_status(self):
        """E2E: GET /api/status through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/credits-redemption-frontend/api/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /api/status returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_assets_manifest(self):
        """E2E: GET /assets/manifest through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/credits-redemption-frontend/assets/manifest", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /assets/manifest returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/credits-redemption-frontend/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
