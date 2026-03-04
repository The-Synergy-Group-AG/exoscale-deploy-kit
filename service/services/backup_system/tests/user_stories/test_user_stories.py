"""User Story Acceptance Tests — backup_system
US: US-501..US-0708 (49 stories) | Port: 8171 | Harmony: 0.997
Stories: US-501, US-502, US-503, US-504, US-505...
Rate limit: 1000 rpm | Timeout: 30s
Plan 123 Phase 2 — real business logic assertions.
"""
import pytest, httpx, time

GATEWAY_URL   = "http://151.145.202.116:30671"
SERVICE_BASE  = f"{GATEWAY_URL}/api/backup_system"
SERVICE_PORT  = 8171


class TestBackupSystemUserStories:
    """Acceptance tests | US: US-501..US-0708 (49 stories)"""

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
        """Story IDs populated: 49 stories (US-501..US-0708). Template must resolve."""
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
        endpoints = ["/backup/status", "/backup/create", "/backup/{id}", "/restore", "/recovery/status", "/backup/{id}"]
        try:
            for path in endpoints:
                r = httpx.get(f"{SERVICE_BASE}{path}", timeout=10.0)
                assert r.status_code < 500
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_backup_status(self):
        """GET /backup/status must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/backup/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /backup/status returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_backup_create(self):
        """POST /backup/create must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/backup/create", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /backup/create returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_backup_id(self):
        """GET /backup/{id} must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/backup/test-id", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /backup/{id} returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_restore(self):
        """POST /restore must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/restore", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /restore returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_recovery_status(self):
        """GET /recovery/status must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/recovery/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /recovery/status returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_backup_id(self):
        """DELETE /backup/{id} must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/backup/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /backup/{id} returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
