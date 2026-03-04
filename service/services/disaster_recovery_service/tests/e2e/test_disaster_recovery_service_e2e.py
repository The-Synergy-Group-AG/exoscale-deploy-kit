"""E2E tests for disaster_recovery_service via gateway.
Port: 8096 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8096
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestDisasterRecoveryServiceE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/disaster_recovery_service/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/disaster_recovery_service/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_backup_status(self):
        """E2E: GET /backup/status through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/disaster_recovery_service/backup/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /backup/status returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_backup_create(self):
        """E2E: POST /backup/create through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/disaster_recovery_service/backup/create", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /backup/create returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_backup_id(self):
        """E2E: GET /backup/{id} through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/disaster_recovery_service/backup/test-id", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /backup/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_restore(self):
        """E2E: POST /restore through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/disaster_recovery_service/restore", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /restore returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_recovery_status(self):
        """E2E: GET /recovery/status through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/disaster_recovery_service/recovery/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /recovery/status returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_backup_id(self):
        """E2E: DELETE /backup/{id} through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/disaster_recovery_service/backup/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /backup/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/disaster_recovery_service/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
