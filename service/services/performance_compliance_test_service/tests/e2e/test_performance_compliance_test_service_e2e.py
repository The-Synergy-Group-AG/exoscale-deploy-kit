"""E2E tests for performance_compliance_test_service via gateway.
Port: 8123 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8123
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestPerformanceComplianceTestServiceE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/performance_compliance_test_service/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/performance_compliance_test_service/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_compliance_status(self):
        """E2E: GET /compliance/status through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/performance_compliance_test_service/compliance/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /compliance/status returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_audit_logs(self):
        """E2E: GET /audit/logs through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/performance_compliance_test_service/audit/logs", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /audit/logs returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_audit_report(self):
        """E2E: POST /audit/report through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/performance_compliance_test_service/audit/report", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /audit/report returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_regulations(self):
        """E2E: GET /regulations through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/performance_compliance_test_service/regulations", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /regulations returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_compliance_check(self):
        """E2E: POST /compliance/check through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/performance_compliance_test_service/compliance/check", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /compliance/check returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_violations(self):
        """E2E: GET /violations through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/performance_compliance_test_service/violations", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /violations returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/performance_compliance_test_service/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
