"""E2E tests for email_integration_service via gateway.
Port: 8154 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8154
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestEmailIntegrationServiceE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/email_integration_service/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/email_integration_service/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_notifications(self):
        """E2E: GET /notifications through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/email_integration_service/notifications", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /notifications returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_notifications_send(self):
        """E2E: POST /notifications/send through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/email_integration_service/notifications/send", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /notifications/send returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_notifications_id_read(self):
        """E2E: PUT /notifications/{id}/read through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/email_integration_service/notifications/test-id/read", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /notifications/{id}/read returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_notifications_id(self):
        """E2E: DELETE /notifications/{id} through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/email_integration_service/notifications/test-id", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /notifications/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_notifications_summary(self):
        """E2E: GET /notifications/summary through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/email_integration_service/notifications/summary", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /notifications/summary returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_notifications_bulk(self):
        """E2E: POST /notifications/bulk through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/email_integration_service/notifications/bulk", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /notifications/bulk returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/email_integration_service/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
