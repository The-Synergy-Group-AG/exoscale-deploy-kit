"""E2E tests for user_profile_manager_service via gateway.
Port: 8191 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8191
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestUserProfileManagerServiceE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/user_profile_manager_service/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/user_profile_manager_service/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_users(self):
        """E2E: GET /users through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/user_profile_manager_service/users", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /users returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_users(self):
        """E2E: POST /users through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/user_profile_manager_service/users", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /users returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_users_id(self):
        """E2E: GET /users/{id} through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/user_profile_manager_service/users/test-id", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /users/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_users_id(self):
        """E2E: PUT /users/{id} through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/user_profile_manager_service/users/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /users/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_users_id(self):
        """E2E: DELETE /users/{id} through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/user_profile_manager_service/users/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /users/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_users_id_profile(self):
        """E2E: GET /users/{id}/profile through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/user_profile_manager_service/users/test-id/profile", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /users/{id}/profile returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/user_profile_manager_service/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
