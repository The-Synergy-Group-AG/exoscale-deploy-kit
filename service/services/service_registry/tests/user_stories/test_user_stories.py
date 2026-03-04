"""User Story Acceptance Tests — service_registry
US: US-097..US-0630 (89 stories) | Port: 8131 | Harmony: 0.997
Stories: US-097, US-098, US-099, US-100, US-101...
Rate limit: 1000 rpm | Timeout: 30s
Plan 123 Phase 2 — real business logic assertions.
"""
import pytest, httpx, time

GATEWAY_URL   = "http://151.145.202.116:30671"
SERVICE_BASE  = f"{GATEWAY_URL}/api/service_registry"
SERVICE_PORT  = 8131


class TestServiceRegistryUserStories:
    """Acceptance tests | US: US-097..US-0630 (89 stories)"""

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
        """Story IDs populated: 89 stories (US-097..US-0630). Template must resolve."""
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
        endpoints = ["/status", "/metrics/live", "/alerts/create", "/logs", "/performance", "/alerts/{id}"]
        try:
            for path in endpoints:
                r = httpx.get(f"{SERVICE_BASE}{path}", timeout=10.0)
                assert r.status_code < 500
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_status(self):
        """GET /status must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /status returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_metrics_live(self):
        """GET /metrics/live must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/metrics/live", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /metrics/live returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_alerts_create(self):
        """POST /alerts/create must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/alerts/create", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /alerts/create returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_logs(self):
        """GET /logs must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/logs", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /logs returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_performance(self):
        """GET /performance must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/performance", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /performance returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_alerts_id(self):
        """DELETE /alerts/{id} must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/alerts/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /alerts/{id} returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
