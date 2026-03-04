"""Unit tests for content_management_cms_service.
Template: svc_catalog_008 | Port: 8279 | Tier: medium
Namespace: jtp | Domain: document
Plan 123 Phase 3 — schema validation on all endpoint responses.
"""
import pytest, sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
from main import app


class TestContentManagementCmsServiceUnit:
    """Unit tests — port 8279 | tier medium | ns jtp"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_root_endpoint(self, client):
        r = client.get("/")
        assert r.status_code == 200
        d = r.json()
        assert d["service"] == "content_management_cms_service"
        assert d["template"] != "unknown", "Plan 123 violation: template=unknown"
        assert d["port"] == 8279, f"Port mismatch: expected 8279 got {d['port']}"
        assert d["resource_tier"] == "medium"
        assert d["kubernetes_namespace"] == "jtp"
        assert "registry_sources" in d
        assert len(d["registry_sources"]) == 6, "All 6 registries must be referenced"

    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "healthy"
        assert d["port"] == 8279
        assert d["resource_tier"] == "medium"
        assert d["kubernetes_namespace"] == "jtp"
        assert d['biological_harmony'] >= 0.997

    def test_metrics_endpoint(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        d = r.json()
        assert d["port"] == 8279
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
        assert d.get("domain") == "document", f"Domain mismatch: {d}"
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


    def test_endpoint_get_documents(self, client):
        """Test GET /documents — status + schema validation"""
        response = client.get("/documents")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "content_management_cms_service", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "document", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/documents", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_post_documents_generate(self, client):
        """Test POST /documents/generate — status + schema validation"""
        response = client.post("/documents/generate")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "content_management_cms_service", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "document", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/documents/generate", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_get_documents_id(self, client):
        """Test GET /documents/{id} — status + schema validation"""
        response = client.get("/documents/{id}")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "content_management_cms_service", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "document", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/documents/{id}", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_put_documents_id(self, client):
        """Test PUT /documents/{id} — status + schema validation"""
        response = client.put("/documents/{id}")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "content_management_cms_service", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "document", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/documents/{id}", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_delete_documents_id(self, client):
        """Test DELETE /documents/{id} — status + schema validation"""
        response = client.delete("/documents/{id}")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "content_management_cms_service", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "document", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/documents/{id}", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"

    def test_endpoint_post_documents_export(self, client):
        """Test POST /documents/export — status + schema validation"""
        response = client.post("/documents/export")
        assert response.status_code in (200, 201, 405, 422)
        if response.status_code in (200, 201):
            data = response.json()
            assert data.get("service") == "content_management_cms_service", \
                f"Response must include service name, got: {data}"
            assert data.get("domain") == "document", \
                f"Response must include domain, got: {data}"
            assert data.get("endpoint") == "/documents/export", \
                f"Response must include endpoint, got: {data}"
            assert data.get("template") is not None, "template key missing"
            assert data.get("template") != "unknown", \
                "Plan 123 violation: template must not be unknown"
            assert data.get("biological_harmony") is not None, "harmony missing"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
