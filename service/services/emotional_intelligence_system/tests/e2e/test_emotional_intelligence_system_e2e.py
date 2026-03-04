"""E2E tests for emotional_intelligence_system via gateway.
Port: 8247 | NS: jtp
Plan 123 Phase 3 — per-endpoint gateway calls + harmony SLA.
"""
import pytest, httpx

SERVICE_PORT = 8247
GATEWAY_URL  = "http://151.145.202.116:30671"


class TestEmotionalIntelligenceSystemE2E:

    def test_gateway_health(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/emotional_intelligence_system/health", timeout=30.0)
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            assert r.json()["port"] == SERVICE_PORT
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_all_registries(self):
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/emotional_intelligence_system/", timeout=30.0)
            assert r.status_code == 200
            assert len(r.json().get("registry_sources", {})) == 6
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_ai_process(self):
        """E2E: POST /ai/process through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/emotional_intelligence_system/ai/process", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /ai/process returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_models(self):
        """E2E: GET /models through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/emotional_intelligence_system/models", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /models returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_models_predict(self):
        """E2E: POST /models/predict through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/emotional_intelligence_system/models/predict", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /models/predict returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_training_status(self):
        """E2E: GET /training/status through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/emotional_intelligence_system/training/status", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /training/status returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_pipeline_run(self):
        """E2E: POST /pipeline/run through Exoscale gateway."""
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/emotional_intelligence_system/pipeline/run", json={}, timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /pipeline/run returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_endpoint_predictions_id(self):
        """E2E: GET /predictions/{id} through Exoscale gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/emotional_intelligence_system/predictions/test-id", timeout=30.0)
            assert r.status_code in (200, 201, 400, 422), \
                f"Gateway endpoint /predictions/{id} returned {r.status_code}"
            assert r.json() is not None
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_gateway_harmony_sla(self):
        """E2E: Biological harmony must meet GODHOOD SLA through gateway."""
        try:
            r = httpx.get(f"{GATEWAY_URL}/api/emotional_intelligence_system/health", timeout=30.0)
            assert r.status_code == 200
            h = r.json().get("biological_harmony", 0)
            assert h >= 0.997, f"Harmony {h} below GODHOOD SLA"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
