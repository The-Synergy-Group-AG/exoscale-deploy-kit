"""E2E tests for portal_integration_hub via gateway.
Port: 8273 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8273
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestPortalIntegrationHubE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/portal_integration_hub/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/portal_integration_hub/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_workflows(self):
        """E2E: GET /workflows through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/portal_integration_hub/workflows", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /workflows returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_workflows_execute(self):
        """E2E: POST /workflows/execute through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/portal_integration_hub/workflows/execute", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /workflows/execute returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_workflows_id_status(self):
        """E2E: GET /workflows/{id}/status through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/portal_integration_hub/workflows/test-id/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /workflows/{id}/status returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_workflows_id_cancel(self):
        """E2E: PUT /workflows/{id}/cancel through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/portal_integration_hub/workflows/test-id/cancel", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /workflows/{id}/cancel returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_pipelines(self):
        """E2E: GET /pipelines through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/portal_integration_hub/pipelines", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /pipelines returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_pipelines_trigger(self):
        """E2E: POST /pipelines/trigger through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/portal_integration_hub/pipelines/trigger", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /pipelines/trigger returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/portal_integration_hub/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
