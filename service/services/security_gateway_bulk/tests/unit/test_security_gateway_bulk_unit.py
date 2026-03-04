"""Unit tests for security_gateway_bulk.
Template: svc_monitoring_016 | Port: 8282 | Tier: large
Namespace: jtp | Domain: security
Plan 123 Phase 3 — schema validation on all endpoint responses.
"""
import pytest, sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
from main import app


class TestSecurityGatewayBulkUnit:
    """Unit tests — port 8282 | tier large | ns jtp"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_root_endpoint(self, client):
        r = client.get("/")
        assert r.status_code == 200
        d = r.json()
        assert d["service"] == "security_gateway_bulk"
        assert d["template"] != "unknown", "Plan 123 violation: template=unknown"
        assert d["port"] == 8282, f"Port mismatch: expected 8282 got {d['port']}"
        assert d["resource_tier"] == "large"
        assert d["kubernetes_namespace"] == "jtp"
        assert "registry_sources" in d
        assert len(d["registry_sources"]) == 6, "All 6 registries must be referenced"

    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "healthy"
        assert d["port"] == 8282
        assert d["resource_tier"] == "large"
        assert d["kubernetes_namespace"] == "jtp"
        assert d['biological_harmony'] >= 0.997

    def test_metrics_endpoint(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        d = r.json()
        assert d["port"] == 8282
        assert "api_timeout_seconds" in d
        assert "rate_limit_rpm" in d

    def test_all_6_registries_in_config(self, client):
        """CRITICAL: all 6 FADS registries must be in registry_sources."""
        r = client.get("/")
        assert r.status_code == 200
        sources = r.json().get("registry_sources", {})
        for reg in ["port_registry", "resource_limits", "variable_registry",
                    "deployment_config", "service_catalog", "master_catalog"]:
            assert reg in sources, f"Registry {reg} missing from registry_sources"

    def test_404_for_unknown_endpoint(self, client):
        assert client.get("/nonexistent-xyz-123").status_code == 404

    def test_root_returns_domain_and_template(self, client):
        """Root must return domain, template, and all required metadata keys."""
        r = client.get("/")
        assert r.status_code == 200
        d = r.json()
        assert d.get("domain") == "security", f"Domain mismatch: {d}"
        assert d.get("template") not in ("unknown", None), "template must be resolved"
        for key in ["service", "domain", "port", "resource_tier", "endpoints",
                    "registry_sources", "biological_harmony", "consciousness_level"]:
            assert key in d, f"Missing key in root response: {key}"

    def test_health_returns_harmony_above_threshold(self, client):
        """Biological harmony must be >= 0.997 (GODHOOD SLA)."""
        r = client.get("/health")
        assert r.status_code == 200
        d = r.json()
        h = d.get("biological_harmony", 0)
        threshold = d.get("harmony_threshold", 0.997)
        assert h >= threshold, f"Harmony {h} < threshold {threshold} — GODHOOD SLA breach"


    def test_endpoint_get_security_status(self, client):
        """Test GET /security/status — status + schema validation"""
        response = client.get("/security/status")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "security_gateway_bulk", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "security", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/security/status", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_post_security_scan(self, client):
        """Test POST /security/scan — status + schema validation"""
        response = client.post("/security/scan")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "security_gateway_bulk", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "security", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/security/scan", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_get_threats(self, client):
        """Test GET /threats — status + schema validation"""
        response = client.get("/threats")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "security_gateway_bulk", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "security", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/threats", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_put_policies_id(self, client):
        """Test PUT /policies/{id} — status + schema validation"""
        response = client.put("/policies/{id}")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "security_gateway_bulk", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "security", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/policies/{id}", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_get_alerts(self, client):
        """Test GET /alerts — status + schema validation"""
        response = client.get("/alerts")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "security_gateway_bulk", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "security", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/alerts", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_post_incidents_report(self, client):
        """Test POST /incidents/report — status + schema validation"""
        response = client.post("/incidents/report")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "security_gateway_bulk", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "security", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/incidents/report", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
