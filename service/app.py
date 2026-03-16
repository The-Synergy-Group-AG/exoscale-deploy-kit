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
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

# L62: Runtime API catalog — loaded from catalog.json baked into Docker image
_CATALOG_PATH = Path("/app/catalog.json")
_SERVICE_CATALOG: dict = {}
if _CATALOG_PATH.exists():
    _SERVICE_CATALOG = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))

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


@app.get("/", response_class=HTMLResponse)
async def root():
    """AI-First home page — dual mode interface (L56)."""
    with open("/app/home.html") as f:
        return f.read()


@app.get("/api-info")
async def api_info():
    """Machine-readable gateway metadata (replaces old GET / JSON response)."""
    return {
        "gateway": "docker-jtp-gateway",
        "version": 7,
        "architecture": "1-pod-per-service",
        "status": "running",
        "proxy_timeout": PROXY_TIMEOUT,
        "dashboard": "/service-dashboard",
    }


@app.get("/service-dashboard", response_class=HTMLResponse)
async def service_dashboard():
    """Service status dashboard — all 219 services with live health checks."""
    with open("/app/dashboard.html") as f:
        return f.read()


@app.get("/api/catalog")
async def api_catalog():
    """L62: Runtime API catalog — all services, endpoints, and dependencies."""
    return {
        "total": len(_SERVICE_CATALOG),
        "domains": sorted({v.get("domain", "general") for v in _SERVICE_CATALOG.values()}),
        "services": _SERVICE_CATALOG,
    }


# ── Server-side intent routing (L56 + L64 catalog-driven) ────────────────────
# Curated routes have priority — hand-tuned patterns for core user-facing services
_CURATED_ROUTES = [
    # ── Core job-seeker journey (7 routes) ────────────────────────────────────
    {"patterns": ["job", "jobs", "vacancy", "position", "hire", "hiring"],
     "service": "job-search-service", "path": "/jobs", "method": "GET"},
    {"patterns": ["cv", "resume", "curriculum", "generate cv"],
     "service": "cv-generation-service", "path": "/cv/generate", "method": "POST"},
    {"patterns": ["interview", "interviews", "prep", "interview schedule"],
     "service": "interview-prep-service", "path": "/interviews", "method": "GET"},
    {"patterns": ["application", "applications", "track", "tracking", "applied"],
     "service": "application-service", "path": "/data", "method": "GET"},
    {"patterns": ["career", "advice", "growth", "path", "guidance"],
     "service": "career-search-core-service", "path": "/career/advice", "method": "GET"},
    {"patterns": ["skill", "skills", "learn", "training", "development", "course"],
     "service": "skill-development-infrastructure", "path": "/jobs", "method": "GET"},
    {"patterns": ["network", "networking", "connections", "connect", "contacts"],
     "service": "networking-service", "path": "/data", "method": "GET"},
    # ── User account & platform (5 routes) ────────────────────────────────────
    {"patterns": ["profile", "my profile", "preferences", "my account"],
     "service": "user-profile-service", "path": "/users", "method": "GET"},
    {"patterns": ["user", "users", "admin", "manage users"],
     "service": "admin-service", "path": "/users", "method": "GET"},
    {"patterns": ["notification", "notifications", "alert", "message", "inbox"],
     "service": "notification-service", "path": "/notifications", "method": "GET"},
    {"patterns": ["onboarding", "welcome", "setup", "getting started"],
     "service": "onboarding-service", "path": "/users", "method": "GET"},
    {"patterns": ["email", "smtp", "mail", "recruiter"],
     "service": "email-integration-service", "path": "/notifications", "method": "GET"},
    # ── Monetization & billing (3 routes) ─────────────────────────────────────
    {"patterns": ["payment", "billing", "invoice", "pay"],
     "service": "payment-processor-service", "path": "/auth/status", "method": "GET"},
    {"patterns": ["subscription", "subscriptions", "plan", "upgrade", "downgrade"],
     "service": "subscription-management-service", "path": "/subscriptions", "method": "GET"},
    {"patterns": ["credit", "credits", "balance", "redeem", "points"],
     "service": "credits-service", "path": "/payments", "method": "GET"},
    # ── Intelligence & analytics (4 routes) ───────────────────────────────────
    {"patterns": ["analytic", "analytics", "metric", "dashboard", "report", "insight"],
     "service": "advanced-analytics-bi-service", "path": "/analytics/dashboard", "method": "GET"},
    {"patterns": ["ai", "ml", "model", "predict", "pipeline"],
     "service": "advanced-ai-ml-service", "path": "/ai/process", "method": "POST"},
    {"patterns": ["recommend", "recommendation", "personaliz", "suggest"],
     "service": "personalization-ai-adaptor", "path": "/models", "method": "GET"},
    {"patterns": ["predictive", "forecast", "prediction"],
     "service": "predictive-analytics-engine", "path": "/analytics/dashboard", "method": "GET"},
    # ── Operations & infrastructure (7 routes) ────────────────────────────────
    {"patterns": ["status", "health", "system", "monitor", "uptime"],
     "service": "monitoring-system-bulk", "path": "/status", "method": "GET"},
    {"patterns": ["security", "threat", "scan", "firewall", "vulnerability"],
     "service": "access-control-service", "path": "/security/status", "method": "GET"},
    {"patterns": ["compliance", "regulation", "regulations", "rav", "gdpr"],
     "service": "swiss-compliance-service", "path": "/regulations", "method": "GET"},
    {"patterns": ["log", "logs", "audit log", "audit trail"],
     "service": "audit-logging-service", "path": "/compliance/status", "method": "GET"},
    {"patterns": ["document", "documents", "file", "export"],
     "service": "document-management-service", "path": "/documents", "method": "GET"},
    {"patterns": ["workflow", "automation", "process", "pipeline"],
     "service": "workflow-engines-service", "path": "/workflows", "method": "GET"},
    {"patterns": ["webhook", "integration", "linkedin", "indeed", "sync"],
     "service": "webhook-integrations-service", "path": "/workflows", "method": "GET"},
    # ── System & config (4 routes) ────────────────────────────────────────────
    {"patterns": ["config", "configuration", "settings", "feature flag"],
     "service": "configuration-management", "path": "/config", "method": "GET"},
    {"patterns": ["backup", "restore", "recovery"],
     "service": "backup-recovery-system", "path": "/backup/status", "method": "GET"},
    {"patterns": ["biological", "harmony", "consciousness"],
     "service": "biological-analytics-performance-test", "path": "/status", "method": "GET"},
    {"patterns": ["gamification", "achievement", "badge", "leaderboard", "xp"],
     "service": "gamification-service", "path": "/leaderboard", "method": "GET"},
]

# Noise words excluded from service name pattern extraction
_NOISE = {"service", "system", "engine", "api", "the", "for", "and", "test", "bulk", "category"}


def _build_dynamic_routes() -> list:
    """L64: Build chat routes from catalog.json for ALL 219 services."""
    curated_services = {r["service"] for r in _CURATED_ROUTES}
    routes = []
    for svc_name, spec in _SERVICE_CATALOG.items():
        dns_name = svc_name.replace("_", "-")
        if dns_name in curated_services:
            continue  # already covered by curated route
        # Extract keywords from service name
        patterns = [w for w in svc_name.replace("-", "_").split("_")
                    if len(w) > 2 and w.lower() not in _NOISE]
        domain = spec.get("domain", "")
        if domain and domain not in patterns:
            patterns.append(domain)
        if not patterns:
            continue  # skip services with no usable keywords
        # Find first GET endpoint as default path
        endpoints = spec.get("endpoints", [])
        get_eps = [e for e in endpoints if e.get("method") == "GET"]
        path = get_eps[0]["path"] if get_eps else "/health"
        routes.append({
            "patterns": patterns,
            "service": dns_name,
            "path": path,
            "method": "GET",
        })
    return routes


# L64: Curated routes first (better patterns), then dynamic for remaining 199 services
_CHAT_ROUTES = _CURATED_ROUTES + _build_dynamic_routes()
logger.info("L64: %d chat routes (%d curated + %d dynamic from catalog)",
            len(_CHAT_ROUTES), len(_CURATED_ROUTES), len(_CHAT_ROUTES) - len(_CURATED_ROUTES))


def _find_chat_route(msg: str):
    lower = msg.lower()
    for route in _CHAT_ROUTES:
        if any(p in lower for p in route["patterns"]):
            return route
    return None


# ── L68: AI-powered conversational chat ──────────────────────────────────────
import httpx as _sync_httpx
from collections import deque
from datetime import datetime, timezone as _dt

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_CHAT_ENABLED = bool(ANTHROPIC_API_KEY)
AI_MODEL = "claude-haiku-4-5-20251001"

if AI_CHAT_ENABLED:
    logger.info("L68: AI chat enabled (Claude Haiku)")
else:
    logger.warning("L68: AI chat DISABLED — no ANTHROPIC_API_KEY found. Set via K8s secret.")


async def _ai_respond(user_msg: str, service_data: dict, service_name: str, client_ip: str = "") -> str:
    """Call Claude to generate a conversational response from service data."""
    if not AI_CHAT_ENABLED:
        return ""
    try:
        # Build context from service data
        data_json = json.dumps(service_data.get("data", {}), indent=2, default=str)[:2000]
        system_prompt = (
            "You are the AI assistant for JobTrackerPro, a Swiss job search platform. "
            "Respond conversationally based on the service data provided. Be helpful, concise, "
            "and format key information clearly. If the data contains lists, summarize the top items. "
            "If the user's query filtered the results (check for 'query' key in data), acknowledge what they searched for. "
            "Keep responses under 150 words. Do not mention internal service names or technical details."
        )
        # L68: Include conversation history for context
        history = _CONV_MEMORY.get(client_ip, [])[-4:]  # last 2 turns
        history_text = ""
        if history:
            history_text = "Recent conversation:\n" + "\n".join(
                f"{'User' if h['role']=='user' else 'Assistant'}: {h['content'][:100]}" for h in history
            ) + "\n\n"
        user_prompt = (
            f"{history_text}"
            f"User asked: \"{user_msg}\"\n\n"
            f"Service data:\n{data_json}\n\n"
            "Generate a helpful, natural response."
        )
        # Use httpx for async API call
        async with _sync_httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": AI_MODEL,
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "system": system_prompt,
                },
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
            else:
                logger.warning(f"L68: Claude API error {resp.status_code}: {resp.text[:200]}")
                return ""
    except Exception as exc:
        logger.warning(f"L68: AI response failed: {exc}")
        return ""


async def _ai_general_chat(user_msg: str, client_ip: str = "") -> str:
    """L68c: Handle general conversation, greetings, follow-ups, and complex queries."""
    if not AI_CHAT_ENABLED:
        return ""
    try:
        history = _CONV_MEMORY.get(client_ip, [])[-6:]
        history_block = ""
        if history:
            history_block = "\n".join(
                f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content'][:150]}"
                for h in history
            ) + "\n\n"

        # Build service catalog summary for Claude
        svc_summary = ", ".join(
            f"{r['service']} ({' '.join(r['patterns'][:2])})"
            for r in _CURATED_ROUTES[:15]
        )

        system = (
            "You are the AI assistant for JobTrackerPro, a Swiss job search platform with 219 microservices. "
            "You help users find jobs, manage applications, prepare for interviews, track analytics, and more. "
            "Be conversational, warm, and helpful. If the user greets you, greet them back and explain what you can do. "
            "If they ask a follow-up, use conversation history for context. "
            "If they ask something you can help with, guide them to ask more specifically. "
            f"Available services include: {svc_summary}. "
            "Keep responses under 120 words. Use emoji sparingly."
        )
        messages = []
        for h in history:
            messages.append({"role": h["role"], "content": h["content"][:200]})
        messages.append({"role": "user", "content": user_msg})

        async with _sync_httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": AI_MODEL,
                    "max_tokens": 250,
                    "messages": messages,
                    "system": system,
                },
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
            else:
                logger.warning(f"L68c: Claude API error {resp.status_code}")
                return "I'd be happy to help! Try asking about jobs, interviews, analytics, or system status."
    except Exception as exc:
        logger.warning(f"L68c: AI general chat failed: {exc}")
        return "I'd be happy to help! Try asking about jobs, interviews, analytics, or system status."


# ── L67: Chat interaction log (in-memory ring buffer) ────────────────────────

_CHAT_LOG: deque = deque(maxlen=1000)  # last 1000 interactions
_CHAT_STATS: dict = {"total": 0, "routed": 0, "unrouted": 0, "errors": 0, "by_service": {}}
# L68: Conversation memory — last 5 turns per "session" (identified by IP for now)
_CONV_MEMORY: dict = {}  # ip → [{"role": "user/assistant", "content": str}]


def _log_chat(msg: str, routed: bool, service: str = None, error: str = None, latency_ms: float = 0):
    """Record a chat interaction for analytics."""
    # L67: Structured log to stdout (captured by kubectl logs across all pods)
    logger.info(f"CHAT|routed={routed}|service={service or 'none'}|latency={latency_ms:.0f}ms|error={error or ''}|msg={msg[:100]}")
    _CHAT_STATS["total"] += 1
    if routed:
        _CHAT_STATS["routed"] += 1
        if service:
            _CHAT_STATS["by_service"][service] = _CHAT_STATS["by_service"].get(service, 0) + 1
    else:
        _CHAT_STATS["unrouted"] += 1
    if error:
        _CHAT_STATS["errors"] += 1
    _CHAT_LOG.append({
        "ts": _dt.utcnow().isoformat() + "Z",
        "message": msg[:200],  # truncate for storage
        "routed": routed,
        "service": service,
        "error": error,
        "latency_ms": round(latency_ms, 1),
    })


@app.get("/chat/analytics")
async def chat_analytics():
    """L67: Chat interaction analytics — review recent interactions."""
    recent = list(_CHAT_LOG)[-50:]  # last 50
    top_services = sorted(_CHAT_STATS["by_service"].items(), key=lambda x: -x[1])[:10]
    unrouted_msgs = [e["message"] for e in _CHAT_LOG if not e["routed"]][-20:]
    return {
        "stats": _CHAT_STATS,
        "top_services": top_services,
        "unrouted_messages": unrouted_msgs,
        "recent_interactions": recent,
    }


@app.post("/chat/route")
async def chat_route(request: Request):
    """Server-side intent router for the AI-First home page (L56)."""
    import time as _t
    t0 = _t.time()
    try:
        body = await request.json()
    except Exception:
        body = {}
    msg = body.get("message", "")
    client_ip = request.client.host if request.client else ""
    route = _find_chat_route(msg)

    # L68c: If no keyword match, use Claude for intent routing + general conversation
    if not route and AI_CHAT_ENABLED:
        ai_fallback = await _ai_general_chat(msg, client_ip)
        _log_chat(msg, routed=False, latency_ms=(_t.time() - t0) * 1000)
        # Save conversation memory
        if client_ip:
            if client_ip not in _CONV_MEMORY:
                _CONV_MEMORY[client_ip] = []
            _CONV_MEMORY[client_ip].append({"role": "user", "content": msg})
            if ai_fallback:
                _CONV_MEMORY[client_ip].append({"role": "assistant", "content": ai_fallback[:200]})
            _CONV_MEMORY[client_ip] = _CONV_MEMORY[client_ip][-10:]
        return {
            "routed": True,
            "service": "ai-assistant",
            "path": "/chat",
            "data": None,
            "ai_response": ai_fallback,
        }
    if not route:
        _log_chat(msg, routed=False, latency_ms=(_t.time() - t0) * 1000)
        return {
            "routed": False,
            "suggestions": ["jobs", "status", "notifications", "analytics"],
        }
    svc_dns = service_to_dns(route["service"])
    # L69: For career/job services, try live job scraping first
    if route.get("service") in ("job-search-service", "job-discovery-service") and "/jobs" in route.get("path", ""):
        try:
            from job_scraper import JobScraper
            scraper = JobScraper()
            live_jobs = await scraper.search(msg, limit=10)
            if live_jobs:
                service_data = {
                    "service": route["service"], "domain": "career",
                    "endpoint": route["path"], "method": "GET",
                    "status": "ok",
                    "data": {"jobs": live_jobs, "total": len(live_jobs),
                             "query": msg, "source": "live"},
                    "timestamp": __import__("time").time(),
                }
                client_ip = request.client.host if request.client else ""
                ai_response = await _ai_respond(msg, service_data, route["service"], client_ip)
                if client_ip:
                    if client_ip not in _CONV_MEMORY:
                        _CONV_MEMORY[client_ip] = []
                    _CONV_MEMORY[client_ip].append({"role": "user", "content": msg})
                    if ai_response:
                        _CONV_MEMORY[client_ip].append({"role": "assistant", "content": ai_response[:200]})
                    _CONV_MEMORY[client_ip] = _CONV_MEMORY[client_ip][-10:]
                latency = (_t.time() - t0) * 1000
                _log_chat(msg, routed=True, service=route["service"], latency_ms=latency)
                result = {"routed": True, "service": route["service"], "path": route["path"], "data": service_data}
                if ai_response:
                    result["ai_response"] = ai_response
                return result
        except Exception as exc:
            logger.warning(f"L69: Job scraper failed, falling back to service: {exc}")

    # L68: Pass user message as query param so service can filter results
    _query_params = {"q": msg} if msg else {}
    url = f"http://{svc_dns}:8000{route['path']}"
    try:
        method = route["method"]
        if method == "GET":
            resp = await _http_client.get(url, params=_query_params, timeout=PROXY_TIMEOUT)
        else:
            resp = await _http_client.post(url, json={"message": msg}, timeout=PROXY_TIMEOUT)
        service_data = resp.json()
        # L68: Generate AI conversational response with conversation memory
        client_ip = request.client.host if request.client else ""
        ai_response = await _ai_respond(msg, service_data, route["service"], client_ip)
        # Save to conversation memory
        if client_ip:
            if client_ip not in _CONV_MEMORY:
                _CONV_MEMORY[client_ip] = []
            _CONV_MEMORY[client_ip].append({"role": "user", "content": msg})
            if ai_response:
                _CONV_MEMORY[client_ip].append({"role": "assistant", "content": ai_response[:200]})
            # Keep last 10 turns
            _CONV_MEMORY[client_ip] = _CONV_MEMORY[client_ip][-10:]
        latency = (_t.time() - t0) * 1000
        _log_chat(msg, routed=True, service=route["service"], latency_ms=latency)
        result = {
            "routed": True,
            "service": route["service"],
            "path": route["path"],
            "data": service_data,
        }
        if ai_response:
            result["ai_response"] = ai_response
        return result
    except Exception as exc:
        latency = (_t.time() - t0) * 1000
        _log_chat(msg, routed=True, service=route["service"], error=str(exc), latency_ms=latency)
        logger.warning(f"chat/route error for {route['service']}: {exc}")
        return {
            "routed": True,
            "service": route["service"],
            "path": route["path"],
            "data": None,
            "error": "service_unavailable",
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
