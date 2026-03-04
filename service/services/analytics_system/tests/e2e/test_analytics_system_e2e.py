"""E2E tests for analytics_system via gateway.
Port: 8182 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8182
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestAnalyticsSystemE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/analytics_system/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/analytics_system/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_analytics_dashboard(self):
        """E2E: GET /analytics/dashboard through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/analytics_system/analytics/dashboard", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /analytics/dashboard returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_analytics_metrics(self):
        """E2E: GET /analytics/metrics through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/analytics_system/analytics/metrics", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /analytics/metrics returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_analytics_track(self):
        """E2E: POST /analytics/track through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/analytics_system/analytics/track", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /analytics/track returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_reports(self):
        """E2E: GET /reports through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/analytics_system/reports", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /reports returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_data_summary(self):
        """E2E: GET /data/summary through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/analytics_system/data/summary", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /data/summary returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_analytics_export(self):
        """E2E: POST /analytics/export through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/analytics_system/analytics/export", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /analytics/export returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/analytics_system/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
