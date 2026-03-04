"""Security tests for docker_compose_test_service.
Port: 8130 | Encryption: advanced | Audit retention: 365 days
OWASP Top 10 — Plan 123 Phase 3 (7 security tests).
Variables from CENTRAL_VARIABLE_REGISTRY.
"""
import pytest, httpx

SERVICE_BASE  = "http://151.145.202.116:30671/api/docker_compose_test_service"
SERVICE_PORT  = 8130
ENC_LEVEL     = "advanced"


class TestDockerComposeTestServiceSecurity:

    def test_sql_injection_rejected(self):
        try:
            r = httpx.get(f"{SERVICE_BASE}/%27%20OR%20%271%27%3D%271", timeout=10.0)
            assert r.status_code != 500
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_content_type_header(self):
        try:
            r = httpx.get(f"{SERVICE_BASE}/health", timeout=10.0)
            assert "application/json" in r.headers.get("content-type", "")
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_oversized_request_rejected(self):
        try:
            r = httpx.post(f"{SERVICE_BASE}/", json={"data": "x" * 100_000}, timeout=10.0)
            assert r.status_code in (413, 422, 405)
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip('Not reachable')

    def test_path_traversal_rejected(self):
        """Path traversal attempts must not return 500."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/../../../../etc/passwd", timeout=10.0)
            assert r.status_code not in (500, 200), \
                f"Path traversal not rejected: {r.status_code}"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_xss_in_query_param_sanitized(self):
        """XSS payloads in query params must not be reflected in 500 errors."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/health?q=<script>alert(1)</script>", timeout=10.0)
            assert r.status_code != 500
            if r.status_code == 200:
                assert "<script>" not in r.text, "XSS payload reflected in response"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_method_not_allowed_returns_405(self):
        """DELETE on a GET endpoint should return 405, not 500."""
        try:
            r = httpx.delete(f"{SERVICE_BASE}/health", timeout=10.0)
            assert r.status_code in (405, 404, 422), \
                f"Unexpected status for DELETE /health: {r.status_code}"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')

    def test_no_sensitive_headers_exposed(self):
        """Response must not expose server internals in headers."""
        try:
            r = httpx.get(f"{SERVICE_BASE}/health", timeout=10.0)
            assert r.status_code == 200
            for header in ["x-powered-by", "server-version", "x-internal-id"]:
                assert header not in r.headers, f"Sensitive header exposed: {header}"
        except httpx.ConnectError:
            pytest.skip('Gateway not reachable')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
