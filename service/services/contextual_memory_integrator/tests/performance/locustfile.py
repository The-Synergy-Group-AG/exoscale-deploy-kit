"""Performance tests for contextual_memory_integrator.
Port: 8232 | Rate limit: 1000 rpm
Plan 123 Phase 3 — business endpoint @task + SLA comments.
Run: locust -f locustfile.py --host http://151.145.202.116:30671
"""
from locust import HttpUser, task, between

SERVICE_PORT = 8232


class ContextualMemoryIntegratorUser(HttpUser):
    wait_time = between(0.1, 0.5)
    host = "http://151.145.202.116:30671"

    @task(3)
    def health_check(self):
        """Health check — p99 SLA: <200ms."""
        with self.client.get("/api/contextual_memory_integrator/health", catch_response=True) as r:
            if r.status_code != 200: r.failure(f"Failed: {r.status_code}")
            elif r.elapsed.total_seconds() > 0.2: r.failure('p99 SLA breach: >200ms')

    @task(1)
    def service_root(self):
        """Service root — p99 SLA: <300ms."""
        with self.client.get("/api/contextual_memory_integrator/", catch_response=True) as r:
            if r.status_code != 200: r.failure(f"Failed: {r.status_code}")
            elif r.elapsed.total_seconds() > 0.3: r.failure('p99 SLA breach: >300ms')

    @task(2)
    def business_endpoint(self):
        """Business domain endpoint — p99 SLA: <500ms."""
        with self.client.post("/api/contextual_memory_integrator/ai/process",
                              json={}, catch_response=True) as r:
            if r.status_code not in (200, 201, 400, 422):
                r.failure(f"Business endpoint failed: {r.status_code}")
            elif r.elapsed.total_seconds() > 0.5:
                r.failure('p99 SLA breach: >500ms for business endpoint')

    def on_start(self):
        """Verify gateway is reachable before load test."""
        r = self.client.get("/api/contextual_memory_integrator/health")
        assert r.status_code == 200, f"Service not reachable: {r.status_code}"
