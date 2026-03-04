"""E2E tests for authentication_middleware_api via gateway.
Port: 8288 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8288
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestAuthenticationMiddlewareApiE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/authentication_middleware_api/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/authentication_middleware_api/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_auth_status(self):
        """E2E: GET /auth/status through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/authentication_middleware_api/auth/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /auth/status returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_auth_login(self):
        """E2E: POST /auth/login through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/authentication_middleware_api/auth/login", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /auth/login returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_auth_logout(self):
        """E2E: POST /auth/logout through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/authentication_middleware_api/auth/logout", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /auth/logout returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_auth_refresh(self):
        """E2E: POST /auth/refresh through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/authentication_middleware_api/auth/refresh", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /auth/refresh returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_users_user_id(self):
        """E2E: GET /users/{user_id} through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/authentication_middleware_api/users/test-id", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /users/{user_id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_auth_verify(self):
        """E2E: POST /auth/verify through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/authentication_middleware_api/auth/verify", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /auth/verify returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/authentication_middleware_api/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
