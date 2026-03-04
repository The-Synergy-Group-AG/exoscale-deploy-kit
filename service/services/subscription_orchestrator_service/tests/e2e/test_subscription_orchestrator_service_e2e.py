"""E2E tests for subscription_orchestrator_service via gateway.
Port: 8223 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8223
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestSubscriptionOrchestratorServiceE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/subscription_orchestrator_service/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/subscription_orchestrator_service/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_payments(self):
        """E2E: GET /payments through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/subscription_orchestrator_service/payments", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /payments returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_payments_process(self):
        """E2E: POST /payments/process through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/subscription_orchestrator_service/payments/process", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /payments/process returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_payments_id(self):
        """E2E: GET /payments/{id} through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/subscription_orchestrator_service/payments/test-id", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /payments/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_billing_invoice(self):
        """E2E: POST /billing/invoice through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/subscription_orchestrator_service/billing/invoice", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /billing/invoice returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_subscriptions(self):
        """E2E: GET /subscriptions through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/subscription_orchestrator_service/subscriptions", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /subscriptions returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_credits_apply(self):
        """E2E: POST /credits/apply through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/subscription_orchestrator_service/credits/apply", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /credits/apply returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/subscription_orchestrator_service/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
