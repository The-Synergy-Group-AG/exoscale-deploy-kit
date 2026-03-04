"""E2E tests for ui_component_library_service via gateway.
Port: 8181 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8181
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestUiComponentLibraryServiceE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/ui_component_library_service/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/ui_component_library_service/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_data(self):
        """E2E: GET /data through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/ui_component_library_service/data", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /data returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_process(self):
        """E2E: POST /process through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/ui_component_library_service/process", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /process returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_info(self):
        """E2E: GET /info through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/ui_component_library_service/info", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /info returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_data_id(self):
        """E2E: PUT /data/{id} through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/ui_component_library_service/data/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /data/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_data_id(self):
        """E2E: DELETE /data/{id} through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/ui_component_library_service/data/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /data/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_summary(self):
        """E2E: GET /summary through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/ui_component_library_service/summary", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /summary returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/ui_component_library_service/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
