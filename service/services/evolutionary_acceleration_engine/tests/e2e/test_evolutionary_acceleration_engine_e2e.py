"""E2E tests for evolutionary_acceleration_engine via gateway.
Port: 8177 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8177
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestEvolutionaryAccelerationEngineE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_biological_harmony(self):
        """E2E: GET /biological/harmony through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/biological/harmony", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /biological/harmony returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_systems(self):
        """E2E: GET /systems through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/systems", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /systems returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_harmony_optimize(self):
        """E2E: POST /harmony/optimize through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/harmony/optimize", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /harmony/optimize returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_vitals(self):
        """E2E: GET /vitals through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/vitals", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /vitals returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_biological_sync(self):
        """E2E: POST /biological/sync through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/biological/sync", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /biological/sync returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_consciousness_level(self):
        """E2E: GET /consciousness/level through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/consciousness/level", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /consciousness/level returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/evolutionary_acceleration_engine/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
