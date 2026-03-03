"""
JTP Gateway v7 — HTTP Reverse Proxy (Plan 121 Fixes)
=====================================================
Key fixes over v6:
  - PROXY_TIMEOUT default reduced to 2.5s (MUST be < test client timeout of 3s)
  - Reduced connection pool: max_connections=50 (was 500) to prevent pool exhaustion
  - keepalive_expiry=5.0 (was 30s) — faster idle connection cleanup
  - Version 7 health response

CRITICAL INVARIANT (L2 from Plan 120 Lessons Learned):
  PROXY_TIMEOUT < test_client_timeout — always!
  If test client timeout = 3s, gateway must return 504 in < 3s.
  Otherwise: test client disconnects, gateway coroutine gets cancelled,
  connection slot leaked → pool exhaustion → event loop freeze (observed
  at service [74] in Plan 120 where test was stuck for 27 minutes).

Plan: 121-Factory-E2E-Restart
"""
import httpx
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

# Proxy timeout (seconds) — MUST be < test client timeout (3s)
# L2 fix: 2.5s default ensures gateway returns 504 BEFORE client disconnects
# This prevents asyncio.CancelledError + httpx connection slot leaks
PROXY_TIMEOUT = float(os.getenv("PROXY_TIMEOUT", "2.5"))

# Optional service DNS overrides (for edge cases where name conversion fails)
SERVICE_DNS_OVERRIDES: dict[str, str] = {}

# Persistent HTTP client — shared across all requests (connection pooling + DNS cache)
_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create persistent HTTP client on startup, close on shutdown."""
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=PROXY_TIMEOUT,
        limits=httpx.Limits(
            max_connections=50,           # L3 fix: reduced from 500 (prevents pool exhaustion)
            max_keepalive_connections=10,  # Keep-alive slots (was 200)
            keepalive_expiry=5.0,          # Expire idle connections quickly (was 30s)
        ),
    )
    logger.info(f"Gateway v7 started — PROXY_TIMEOUT={PROXY_TIMEOUT}s, pool=50, persistent client ready")
    yield
    await _http_client.aclose()
    logger.info("Gateway v7 shutdown — HTTP client closed")


app = FastAPI(
    title="JTP Gateway v7",
    description="HTTP reverse proxy — 1-pod-per-service, persistent connection pooling (Plan 121)",
    version="7.0.0",
    lifespan=lifespan,
)


def service_to_dns(name: str) -> str:
    """Convert filesystem service name (underscores) to Kubernetes DNS name (hyphens)."""
    return SERVICE_DNS_OVERRIDES.get(name, name.replace("_", "-"))


@app.get("/")
async def root():
    """Gateway root."""
    return {
        "gateway": "docker-jtp-gateway",
        "version": 7,
        "architecture": "1-pod-per-service",
        "status": "running",
        "proxy_timeout": PROXY_TIMEOUT,
    }


@app.get("/health")
async def health():
    """Gateway health check."""
    return {
        "status": "healthy",
        "version": 7,
        "architecture": "1-pod-per-service",
        "proxy_timeout": PROXY_TIMEOUT,
    }


@app.get("/status")
async def status():
    """Gateway status check."""
    return {
        "status": "running",
        "version": 7,
        "proxy_timeout": PROXY_TIMEOUT,
        "client_ready": _http_client is not None,
    }


@app.api_route(
    "/api/{service_name}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy(service_name: str, path: str, request: Request):
    """
    Forward all /api/<service_name>/<path> requests to the individual service pod.
    Service pods are reachable via Kubernetes ClusterIP DNS: <service-dns-name>:8000
    Uses persistent httpx client for connection pooling and DNS caching.

    IMPORTANT: PROXY_TIMEOUT (2.5s) is set BELOW test client timeout (3s).
    This ensures the gateway returns 504 before the client disconnects,
    preventing asyncio.CancelledError and connection slot leaks.
    """
    svc_dns = service_to_dns(service_name)
    url = f"http://{svc_dns}:8000/{path}"
    if request.query_params:
        url += "?" + str(request.query_params)

    logger.info(f"PROXY {request.method} {service_name}/{path} → {url}")

    try:
        resp = await _http_client.request(
            method=request.method,
            url=url,
            headers={
                k: v for k, v in request.headers.items()
                if k.lower() not in ("host", "content-length", "transfer-encoding")
            },
            content=await request.body(),
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )
    except httpx.TimeoutException:
        logger.warning(f"TIMEOUT: {url}")
        return JSONResponse(
            {"error": "service_timeout", "service": service_name, "url": url},
            status_code=504,
        )
    except httpx.ConnectError as exc:
        logger.warning(f"CONNECT_ERROR: {url} — {exc}")
        return JSONResponse(
            {"error": "service_unavailable", "service": service_name, "url": url},
            status_code=503,
        )
    except Exception as exc:
        logger.error(f"PROXY_ERROR: {url} — {exc}")
        return JSONResponse(
            {"error": "proxy_error", "service": service_name, "detail": str(exc)},
            status_code=500,
        )
