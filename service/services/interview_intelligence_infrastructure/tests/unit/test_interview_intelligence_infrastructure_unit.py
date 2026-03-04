"""Unit tests for interview_intelligence_infrastructure.
Template: svc_catalog_008 | Port: 8242 | Tier: medium
Namespace: jtp | Domain: career
Plan 123 Phase 3 — schema validation on all endpoint responses.
"""
import pytest, sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
from main import app


class TestInterviewIntelligenceInfrastructureUnit:
    """Unit tests — port 8242 | tier medium | ns jtp"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_root_endpoint(self, client):
        r = client.get("/")
        assert r.status_code == 200
        d = r.json()
        assert d["service"] == "interview_intelligence_infrastructure"
        assert d["template"] != "unknown", "Plan 123 violation: template=unknown"
        assert d["port"] == 8242, f"Port mismatch: expected 8242 got {d['port']}"
        assert d["resource_tier"] == "medium"
        assert d["kubernetes_namespace"] == "jtp"
        assert "registry_sources" in d
        assert len(d["registry_sources"]) == 6, "All 6 registries must be referenced"

    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "healthy"
        assert d["port"] == 8242
        assert d["resource_tier"] == "medium"
        assert d["kubernetes_namespace"] == "jtp"
        assert d['biological_harmony'] >= 0.997

    def test_metrics_endpoint(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        d = r.json()
        assert d["port"] == 8242
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
        assert d.get("domain") == "career", f"Domain mismatch: {d}"
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


    def test_endpoint_get_jobs(self, client):
        """Test GET /jobs — status + schema validation"""
        response = client.get("/jobs")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "interview_intelligence_infrastructure", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "career", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/jobs", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_post_applications(self, client):
        """Test POST /applications — status + schema validation"""
        response = client.post("/applications")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "interview_intelligence_infrastructure", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "career", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/applications", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_get_interviews(self, client):
        """Test GET /interviews — status + schema validation"""
        response = client.get("/interviews")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "interview_intelligence_infrastructure", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "career", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/interviews", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_get_cv_id(self, client):
        """Test GET /cv/{id} — status + schema validation"""
        response = client.get("/cv/{id}")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "interview_intelligence_infrastructure", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "career", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/cv/{id}", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_get_career_advice(self, client):
        """Test GET /career/advice — status + schema validation"""
        response = client.get("/career/advice")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "interview_intelligence_infrastructure", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "career", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/career/advice", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_post_cv_generate(self, client):
        """Test POST /cv/generate — status + schema validation"""
        response = client.post("/cv/generate")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "interview_intelligence_infrastructure", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "career", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/cv/generate", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
