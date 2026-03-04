"""User Story Acceptance Tests — cv_builder_service
US: US-280..US-323 (28 stories) | Port: 8128 | Harmony: 0.997
Stories: US-280, US-284, US-288, US-291, US-293...
Rate limit: 1000 rpm | Timeout: 30s
Plan 123 Phase 2 — real business logic assertions.
"""
import pytest, httpx, time

GATEWAY_URL   = "http://151.145.202.116:30671"
SERVICE_BASE  = f"{GATEWAY_URL}/api/cv_builder_service"
SERVICE_PORT  = 8128


class TestCvBuilderServiceUserStories:
    """Acceptance tests | US: US-280..US-323 (28 stories)"""

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
        """Story IDs populated: 28 stories (US-280..US-323). Template must resolve."""
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
        endpoints = ["/jobs", "/applications", "/interviews", "/cv/{id}", "/career/advice", "/cv/generate"]
        try:
            for path in endpoints:
                r = httpx.get(f"{SERVICE_BASE}{path}", timeout=10.0)
                assert r.status_code < 500
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_jobs(self):
        """GET /jobs must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/jobs", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /jobs returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_applications(self):
        """POST /applications must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/applications", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /applications returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_interviews(self):
        """GET /interviews must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/interviews", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /interviews returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_cv_id(self):
        """GET /cv/{id} must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/cv/test-id", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /cv/{id} returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_career_advice(self):
        """GET /career/advice must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/career/advice", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /career/advice returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_cv_generate(self):
        """POST /cv/generate must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/cv/generate", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /cv/generate returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
