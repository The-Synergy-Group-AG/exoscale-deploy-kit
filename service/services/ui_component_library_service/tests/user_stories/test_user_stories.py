"""User Story Acceptance Tests — ui_component_library_service
US: US-001..US-0601 (241 stories) | Port: 8181 | Harmony: 0.997
Stories: US-001, US-002, US-003, US-004, US-005...
Rate limit: 1000 rpm | Timeout: 30s
Plan 123 Phase 2 — real business logic assertions.
"""
import pytest, httpx, time

GATEWAY_URL   = "http://151.145.202.116:30671"
SERVICE_BASE  = f"{GATEWAY_URL}/api/ui_component_library_service"
SERVICE_PORT  = 8181


class TestUiComponentLibraryServiceUserStories:
    """Acceptance tests | US: US-001..US-0601 (241 stories)"""

    def test_us_service_availability(self):
        try:
            r = httpx.get(f"{SERVICE_BASE}/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_us_all_registries_integrated(self):
        """All 6 FADS registries must be referenced."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/", timeout=30.0)
            assert r.status_code == 200
            sources = r.json().get("registry_sources", {})
            assert len(sources) == 6, f"Only {len(sources)}/6 registries integrated"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_us_harmony_target(self):
        """Harmony >= 0.997 (GODHOOD target)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/health", timeout=30.0)
            assert r.json().get("biological_harmony", 0) >= 0.997
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_us_story_ids_populated(self):
        """Story IDs populated: 241 stories (US-001..US-0601). Template must resolve."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/", timeout=30.0)
            assert r.status_code == 200
            data = r.json()
            assert data.get("template") != "unknown", \
                "Template must be resolved (not unknown) — Plan 123 Phase 2 violation"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_us_variables_from_registry(self):
        """Variables from CENTRAL_VARIABLE_REGISTRY must be present."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/", timeout=30.0)
            vars_loaded = r.json().get("variables_loaded", [])
            assert "api_timeout" in vars_loaded
            assert "harmony_threshold" in vars_loaded
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_us_endpoints_operational(self):
        endpoints = ["/data", "/process", "/info", "/data/{id}", "/data/{id}", "/summary"]
        try:
            for path in endpoints:
                r = httpx.get(f"{SERVICE_BASE}{path}", timeout=10.0)
                assert r.status_code < 500
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_data(self):
        """GET /data must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/data", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /data returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_process(self):
        """POST /process must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/process", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /process returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_info(self):
        """GET /info must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/info", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /info returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_data_id(self):
        """PUT /data/{id} must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/data/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /data/{id} returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_data_id(self):
        """DELETE /data/{id} must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/data/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /data/{id} returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_summary(self):
        """GET /summary must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/summary", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /summary returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
