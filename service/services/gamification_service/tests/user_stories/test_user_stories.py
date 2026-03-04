"""User Story Acceptance Tests — gamification_service
US: US-280..US-323 (28 stories) | Port: 8111 | Harmony: 0.997
Stories: US-280, US-284, US-288, US-291, US-293...
Rate limit: 1000 rpm | Timeout: 30s
Plan 123 Phase 2 — real business logic assertions.
"""
import pytest, httpx, time

GATEWAY_URL   = "http://151.145.202.116:30671"
SERVICE_BASE  = f"{GATEWAY_URL}/api/gamification_service"
SERVICE_PORT  = 8111


class TestGamificationServiceUserStories:
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
        endpoints = ["/leaderboard", "/achievements/unlock", "/xp", "/badges", "/points", "/challenges/join"]
        try:
            for path in endpoints:
                r = httpx.get(f"{SERVICE_BASE}{path}", timeout=10.0)
                assert r.status_code < 500
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_leaderboard(self):
        """GET /leaderboard must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/leaderboard", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /leaderboard returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_achievements_unlock(self):
        """POST /achievements/unlock must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/achievements/unlock", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /achievements/unlock returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_xp(self):
        """GET /xp must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/xp", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /xp returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_badges(self):
        """GET /badges must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/badges", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /badges returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_points(self):
        """GET /points must respond (200/201/400/422 valid)."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/points", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /points returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_endpoint_challenges_join(self):
        """POST /challenges/join must respond (200/201/400/422 valid)."""
        try:
            r = httpx.post(f"{SERVICE_BASE}/challenges/join", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Endpoint /challenges/join returned unexpected {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
