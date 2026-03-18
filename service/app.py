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
from datetime import datetime as _dt, timezone as _tz

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_CHAT_ENABLED = bool(ANTHROPIC_API_KEY)
AI_MODEL = "claude-haiku-4-5-20251001"

# ── L72: Job search query extraction ─────────────────────────────────────────
_JOB_STOP_WORDS = {
    "find", "show", "search", "get", "list", "me", "my", "i", "want", "need",
    "looking", "for", "the", "a", "an", "in", "at", "on", "to", "of", "and",
    "or", "with", "some", "any", "available", "open", "please", "can", "you",
    "jobs", "job", "positions", "position", "roles", "role", "opportunities",
    "vacancies", "openings", "work", "career", "careers",
}
_SWISS_LOCATIONS = {
    "zurich", "zürich", "geneva", "genève", "geneve", "basel", "bern", "berne",
    "lausanne", "winterthur", "lucerne", "luzern", "st gallen", "lugano",
    "biel", "thun", "aarau", "zug", "fribourg", "schaffhausen", "chur",
    "switzerland", "swiss",
}


def _extract_job_search_terms(msg: str) -> str:
    """Extract meaningful job search terms from a natural language message.

    "zurich ba jobs in banking" → "business analyst banking" with location=zurich
    "find python developer jobs in Basel" → "python developer" with location=basel
    """
    words = msg.lower().split()
    location_parts = []
    search_parts = []

    for word in words:
        cleaned = word.strip(".,!?;:")
        if cleaned in _SWISS_LOCATIONS:
            location_parts.append(cleaned)
        elif cleaned not in _JOB_STOP_WORDS and len(cleaned) > 1:
            search_parts.append(cleaned)

    # Expand common abbreviations
    expanded = []
    for part in search_parts:
        if part == "ba":
            expanded.append("business analyst")
        elif part == "pm":
            expanded.append("project manager")
        elif part == "qa":
            expanded.append("quality assurance")
        elif part == "hr":
            expanded.append("human resources")
        elif part == "it":
            expanded.append("IT")
        elif part == "ml":
            expanded.append("machine learning")
        elif part == "ai":
            expanded.append("artificial intelligence")
        elif part == "devops":
            expanded.append("devops")
        elif part == "sre":
            expanded.append("site reliability engineer")
        else:
            expanded.append(part)

    query = " ".join(expanded)
    if location_parts:
        # jobs.ch handles location separately, but including it helps relevance
        query = query + " " + " ".join(location_parts) if query else " ".join(location_parts)

    return query.strip()

if AI_CHAT_ENABLED:
    logger.info("L68: AI chat enabled (Claude Haiku)")
else:
    logger.warning("L68: AI chat DISABLED — no ANTHROPIC_API_KEY found. Set via K8s secret.")


def _is_demo_data(service_data: dict) -> bool:
    """L72: Detect if service returned fallback/demo data instead of real AI results."""
    # Top-level mode flag from L72 generator
    if service_data.get("mode") == "demo":
        return True
    # Check source — "ai" or "live" means real data
    if service_data.get("source") in ("ai", "live"):
        return False
    data = service_data.get("data", {})
    if isinstance(data, dict):
        # Telltale mock data markers from _DOMAIN_ENDPOINT_DATA
        data_str = json.dumps(data, default=str)[:3000]
        _mock_markers = ["job-001", "badge-001", "TechCorp AG", "item-001", "sample data"]
        if sum(1 for m in _mock_markers if m in data_str) >= 2:
            return True
    return False


# L72: Intent-specific system prompts for domain expertise
_INTENT_PROMPTS = {
    "career": (
        "You are a Swiss career expert. Provide specific, actionable advice about "
        "job searching in Switzerland: platforms (jobs.ch, LinkedIn, Jobup), Swiss CV format, "
        "salary expectations by role, work permit requirements, and regional market differences."
    ),
    "document": (
        "You are a Swiss CV/resume specialist. Advise on the Swiss CV format: include photo, "
        "personal details, Europass compatibility, cover letter conventions, and how Swiss employers "
        "evaluate applications differently from US/UK markets."
    ),
    "gamification": (
        "You are a motivational career coach. Help users stay motivated in their job search "
        "through goal-setting, progress tracking, celebrating milestones, and building positive habits."
    ),
    "biological": (
        "You are a wellness-aware career advisor. Help users manage the emotional and physical "
        "aspects of job searching: stress management, interview anxiety, rejection resilience, "
        "and maintaining work-life balance during the search."
    ),
    "analytics": (
        "You are a career analytics advisor. Help users understand their job search metrics, "
        "application-to-interview ratios, response rates, and how to optimize their strategy."
    ),
    "compliance": (
        "You are a Swiss employment law expert. Advise on RAV requirements, unemployment benefits, "
        "work permits (B/C/L), notice periods, and Swiss labour regulations."
    ),
}


async def _fetch_user_context(request: Request) -> str:
    """Plan 131 Phase 3: Fetch user context from backend services for personalization."""
    user_id = _get_user_id(request)
    if not user_id:
        return ""

    context_parts = []
    try:
        async with _sync_httpx.AsyncClient(timeout=3.0) as c:
            # Fetch CV history (most recent analysis)
            try:
                r = await c.get(f"http://cv-processor:8020/history/{user_id}")
                if r.status_code == 200:
                    data = r.json()
                    history = data.get("history", [])
                    if history:
                        latest = history[-1] if isinstance(history, list) else history
                        analysis = latest.get("analysis", "")[:300] if isinstance(latest, dict) else str(latest)[:300]
                        if analysis:
                            context_parts.append(f"CV analysis: {analysis}")
            except Exception:
                pass

            # Fetch profile
            try:
                r = await c.get(f"http://user-profile-service:8000/users/{user_id}")
                if r.status_code == 200:
                    data = r.json()
                    profile = data.get("data", data)
                    if isinstance(profile, dict):
                        name = profile.get("name", profile.get("username", ""))
                        role = profile.get("target_role", "")
                        loc = profile.get("location", "")
                        skills = profile.get("skills", [])
                        if name or role or loc:
                            parts = []
                            if name:
                                parts.append(f"Name: {name}")
                            if role:
                                parts.append(f"Target: {role}")
                            if loc:
                                parts.append(f"Location: {loc}")
                            if skills:
                                parts.append(f"Skills: {', '.join(skills[:5])}")
                            context_parts.append("Profile: " + ", ".join(parts))
            except Exception:
                pass

            # Fetch applications
            try:
                r = await c.get("http://application-service:8000/data", params={"q": user_id})
                if r.status_code == 200:
                    data = r.json()
                    apps = data.get("data", {})
                    if isinstance(apps, dict) and apps.get("applications"):
                        app_list = apps["applications"]
                        context_parts.append(
                            f"Applications: {len(app_list)} tracked "
                            f"({', '.join(a.get('company','?') + ':' + a.get('status','?') for a in app_list[:3])})"
                        )
            except Exception:
                pass
    except Exception:
        pass

    return "\n".join(context_parts)


async def _ai_respond(user_msg: str, service_data: dict, service_name: str, client_ip: str = "",
                      user_context: str = "") -> str:
    """L72: Call Claude to generate a genuinely helpful response.

    If service data is real (from AI backends), Claude incorporates it.
    If service data is demo/fallback, Claude uses its own Swiss career expertise.
    """
    if not AI_CHAT_ENABLED:
        return ""
    try:
        demo_mode = _is_demo_data(service_data)
        domain = service_data.get("domain", "general")

        # Build system prompt: domain expertise + context awareness
        base_prompt = (
            "You are the AI career assistant for JobTrackerPro, a Swiss job search platform. "
            "You have deep knowledge of the Swiss job market, career development, and professional networking. "
            "Be helpful, specific, and actionable. Format key information clearly with markdown. "
            "Keep responses under 200 words. Never mention internal service names or technical details. "
            "NEVER say you don't have access to jobs — the platform searches jobs.ch for specific queries.\n\n"
            "PLATFORM CAPABILITIES:\n"
            "- LIVE job search from jobs.ch (user specifies role + location)\n"
            "- CV upload (PDF/DOCX) with AI analysis and Swiss format review\n"
            "- User profiles with saved preferences\n"
            "- Application tracking pipeline (applied/interview/offer/rejected)\n"
            "- Direct apply from search results\n"
            "- Interview preparation coaching\n"
            "- Swiss market expertise (RAV, permits, salary ranges)\n"
        )
        if user_context:
            base_prompt += f"\n\nUSER CONTEXT (personalize your response):\n{user_context}\n"
        domain_prompt = _INTENT_PROMPTS.get(domain, "")
        if domain_prompt:
            base_prompt += f"\n\nDomain expertise: {domain_prompt}"

        # Build user message with context
        history = _CONV_MEMORY.get(client_ip, [])[-4:]
        history_text = ""
        if history:
            history_text = "Recent conversation:\n" + "\n".join(
                f"{'User' if h['role']=='user' else 'Assistant'}: {h['content'][:150]}" for h in history
            ) + "\n\n"

        if demo_mode:
            user_prompt = (
                f"{history_text}"
                f"User asked: \"{user_msg}\"\n\n"
                "The platform has live job search capabilities but the query was too broad "
                "to return specific results. Help the user refine their search — suggest "
                "they specify a role, location, or skill. Also provide helpful Swiss job "
                "market advice based on your knowledge. NEVER say you don't have access "
                "to jobs — the platform DOES search jobs.ch for specific queries."
            )
        else:
            data_json = json.dumps(service_data.get("data", {}), indent=2, default=str)[:2000]
            user_prompt = (
                f"{history_text}"
                f"User asked: \"{user_msg}\"\n\n"
                f"Live service data from {service_name}:\n{data_json}\n\n"
                "Incorporate this data into a helpful, conversational response."
            )

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
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "system": base_prompt,
                },
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
            else:
                logger.warning(f"L72: Claude API error {resp.status_code}: {resp.text[:200]}")
                return ""
    except Exception as exc:
        logger.warning(f"L72: AI response failed: {exc}")
        return ""


async def _ai_general_chat(user_msg: str, client_ip: str = "", user_context: str = "") -> str:
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
            "You are the AI assistant for JobTrackerPro, a Swiss job search platform. "
            "Be conversational, warm, and helpful. Keep responses under 120 words.\n\n"
            "PLATFORM CAPABILITIES:\n"
            "- Search real Swiss jobs from jobs.ch (specify role + location)\n"
            "- Upload CV (PDF/DOCX) for AI analysis and Swiss format review\n"
            "- User profiles with saved preferences\n"
            "- Application tracking (applied/interview/offer/rejected)\n"
            "- Direct apply from job search results\n"
            "- Interview prep coaching\n"
            "- Swiss market expertise (RAV, permits, salaries)\n"
        )
        if user_context:
            system += f"\n\nUSER CONTEXT:\n{user_context}\n"
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


# ── L72: Persistent chat interaction log ─────────────────────────────────────
# Chat logs are written to a JSONL file for deep persistence across restarts.
# On startup, existing logs are loaded to rebuild stats and memory.
# /chat/logs/export returns raw JSONL for backup/analysis.
# /chat/logs/import accepts JSONL upload for restore after redeploy.

_CHAT_LOG_DIR = Path(os.getenv("CHAT_LOG_DIR", "/app/logs"))
_CHAT_LOG_FILE = _CHAT_LOG_DIR / "chat_interactions.jsonl"
_CHAT_LOG: deque = deque(maxlen=10000)  # last 10k interactions (in-memory cache)
_CHAT_STATS: dict = {"total": 0, "routed": 0, "unrouted": 0, "errors": 0, "by_service": {}}
_CONV_MEMORY: dict = {}  # ip → [{"role": "user/assistant", "content": str}]


def _init_chat_log():
    """Load existing chat log from persistent file on startup."""
    _CHAT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not _CHAT_LOG_FILE.exists():
        logger.info("L72: No existing chat log — starting fresh")
        return
    loaded = 0
    try:
        with open(_CHAT_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    _CHAT_LOG.append(entry)
                    # Rebuild stats
                    _CHAT_STATS["total"] += 1
                    if entry.get("routed"):
                        _CHAT_STATS["routed"] += 1
                        svc = entry.get("service")
                        if svc:
                            _CHAT_STATS["by_service"][svc] = _CHAT_STATS["by_service"].get(svc, 0) + 1
                    else:
                        _CHAT_STATS["unrouted"] += 1
                    if entry.get("error"):
                        _CHAT_STATS["errors"] += 1
                    loaded += 1
                except json.JSONDecodeError:
                    continue
        logger.info(f"L72: Loaded {loaded} chat interactions from persistent log")
    except Exception as exc:
        logger.warning(f"L72: Failed to load chat log: {exc}")


# Load on module init
_init_chat_log()


def _log_chat(msg: str, routed: bool, service: str = None, error: str = None,
              latency_ms: float = 0, ai_response: str = None, client_ip: str = ""):
    """Record a chat interaction — persisted to JSONL file + in-memory cache."""
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

    entry = {
        "ts": _dt.now(_tz.utc).isoformat() + "Z",
        "pod": os.getenv("HOSTNAME", "unknown"),
        "client_ip": client_ip[:20] if client_ip else "",
        "message": msg[:500],
        "routed": routed,
        "service": service,
        "error": error,
        "latency_ms": round(latency_ms, 1),
        "ai_response": (ai_response[:1000] if ai_response else None),
    }
    _CHAT_LOG.append(entry)

    # Append to persistent JSONL file
    try:
        with open(_CHAT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        logger.warning(f"L72: Failed to persist chat log: {exc}")


@app.get("/chat/analytics")
async def chat_analytics():
    """L72: Chat interaction analytics with persistent history."""
    recent = list(_CHAT_LOG)[-50:]
    top_services = sorted(_CHAT_STATS["by_service"].items(), key=lambda x: -x[1])[:10]
    unrouted_msgs = [e["message"] for e in _CHAT_LOG if not e["routed"]][-20:]
    return {
        "stats": _CHAT_STATS,
        "top_services": top_services,
        "unrouted_messages": unrouted_msgs,
        "recent_interactions": recent,
        "log_file": str(_CHAT_LOG_FILE),
        "log_entries": len(_CHAT_LOG),
    }


@app.get("/chat/logs/export")
async def chat_logs_export():
    """L72: Export full chat interaction log as JSONL for backup/analysis."""
    from fastapi.responses import FileResponse
    if _CHAT_LOG_FILE.exists():
        return FileResponse(
            _CHAT_LOG_FILE,
            media_type="application/jsonl",
            filename=f"chat_interactions_{_dt.now(_tz.utc).strftime('%Y%m%d_%H%M%S')}.jsonl",
        )
    return {"error": "No chat log file found", "path": str(_CHAT_LOG_FILE)}


@app.post("/chat/logs/import")
async def chat_logs_import(request: Request):
    """L72: Import chat log JSONL (for restoring across deployments)."""
    try:
        body = await request.body()
        lines = body.decode("utf-8").strip().split("\n")
        imported = 0
        _CHAT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CHAT_LOG_FILE, "a", encoding="utf-8") as f:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    _CHAT_LOG.append(entry)
                    _CHAT_STATS["total"] += 1
                    if entry.get("routed"):
                        _CHAT_STATS["routed"] += 1
                        svc = entry.get("service")
                        if svc:
                            _CHAT_STATS["by_service"][svc] = _CHAT_STATS["by_service"].get(svc, 0) + 1
                    else:
                        _CHAT_STATS["unrouted"] += 1
                    if entry.get("error"):
                        _CHAT_STATS["errors"] += 1
                    f.write(line + "\n")
                    imported += 1
                except json.JSONDecodeError:
                    continue
        return {"imported": imported, "total_entries": len(_CHAT_LOG)}
    except Exception as exc:
        return {"error": str(exc)}


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

    # Plan 131 Phase 3: Fetch user context for personalized AI responses
    user_context = await _fetch_user_context(request)

    # Plan 131 Phase 4: "Match my CV" intent — semantic job-CV matching
    _cv_match_keywords = {"match my cv", "jobs matching my cv", "match cv", "jobs for my cv",
                          "jobs for my profile", "match my profile", "matching jobs"}
    if any(kw in msg.lower() for kw in _cv_match_keywords):
        user_id = _get_user_id(request)
        cv_skills = ""
        if user_id:
            try:
                async with _sync_httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.get(f"http://cv-processor:8020/history/{user_id}")
                    if r.status_code == 200:
                        hist = r.json().get("history", [])
                        if hist and isinstance(hist, list) and hist:
                            latest = hist[-1] if isinstance(hist[-1], dict) else {}
                            cv_skills = latest.get("data", "")[:500]
            except Exception:
                pass
        if not cv_skills and user_context:
            # Extract skills from user context as fallback
            for line in user_context.split("\n"):
                if "Skills:" in line or "Target:" in line:
                    cv_skills += line + " "
        if cv_skills:
            # Use CV skills as job search query
            search_terms = _extract_job_search_terms(cv_skills)
            route = {"service": "job-search-service", "path": "/jobs", "method": "GET",
                     "patterns": ["match"]}
            msg = f"Find jobs matching: {search_terms}"

    # L68c: If no keyword match, use Claude for intent routing + general conversation
    if not route and AI_CHAT_ENABLED:
        ai_fallback = await _ai_general_chat(msg, client_ip, user_context=user_context)
        _log_chat(msg, routed=False, latency_ms=(_t.time() - t0) * 1000,
                  ai_response=ai_fallback, client_ip=client_ip)
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
        _log_chat(msg, routed=False, latency_ms=(_t.time() - t0) * 1000, client_ip=client_ip)
        return {
            "routed": False,
            "suggestions": ["jobs", "status", "notifications", "analytics"],
        }
    svc_dns = service_to_dns(route["service"])
    # L72: Extract meaningful search terms for job queries instead of raw message
    _search_query = msg
    if route.get("service") in ("job-search-service", "career-search-core-service", "job-discovery-service"):
        _search_query = _extract_job_search_terms(msg)
    _query_params = {"q": _search_query} if _search_query else {}
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
        ai_response = await _ai_respond(msg, service_data, route["service"], client_ip,
                                         user_context=user_context)
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
        _log_chat(msg, routed=True, service=route["service"], latency_ms=latency,
                  ai_response=ai_response, client_ip=client_ip)
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
        _log_chat(msg, routed=True, service=route["service"], error=str(exc),
                  latency_ms=latency, client_ip=client_ip)
        logger.warning(f"chat/route error for {route['service']}: {exc}")
        # L72: AI fallback when service is unreachable — user still gets a helpful response
        ai_fallback = await _ai_general_chat(msg, client_ip, user_context=user_context)
        if client_ip:
            if client_ip not in _CONV_MEMORY:
                _CONV_MEMORY[client_ip] = []
            _CONV_MEMORY[client_ip].append({"role": "user", "content": msg})
            if ai_fallback:
                _CONV_MEMORY[client_ip].append({"role": "assistant", "content": ai_fallback[:200]})
            _CONV_MEMORY[client_ip] = _CONV_MEMORY[client_ip][-10:]
        return {
            "routed": True,
            "service": route["service"],
            "path": route["path"],
            "data": None,
            "ai_response": ai_fallback,
        }


# ── Plan 131: Core Product Features — JWT + Upload + Profile + Applications ────

import hashlib as _hashlib
import hmac as _hmac
import base64 as _b64
import uuid as _uuid

_JWT_SECRET = os.getenv(
    "JWT_SECRET", "ffc86ecae403d31816cfed50b92dd0815b61de5fd2807e93154d3b2ce6d58d0a"
)


def _jwt_encode(payload: dict) -> str:
    """Minimal JWT encoder (HS256) — no external dependency."""
    header = _b64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=")
    body = _b64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).rstrip(b"=")
    msg = header + b"." + body
    sig = _hmac.new(_JWT_SECRET.encode(), msg, _hashlib.sha256).digest()
    sig_b64 = _b64.urlsafe_b64encode(sig).rstrip(b"=")
    return (msg + b"." + sig_b64).decode()


def _jwt_decode(token: str) -> dict | None:
    """Minimal JWT decoder — returns payload or None if invalid."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        msg = (parts[0] + "." + parts[1]).encode()
        sig = _b64.urlsafe_b64decode(parts[2] + "==")
        expected = _hmac.new(_JWT_SECRET.encode(), msg, _hashlib.sha256).digest()
        if not _hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64.urlsafe_b64decode(parts[1] + "=="))
        return payload
    except Exception:
        return None


def _get_user_id(request: Request) -> str:
    """Extract user_id from JWT Bearer token, or generate new one."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        payload = _jwt_decode(auth[7:])
        if payload and "user_id" in payload:
            return payload["user_id"]
    return ""


@app.post("/api/auth/token")
async def create_token():
    """Plan 131: Generate a JWT token for a new user (frictionless — no registration)."""
    user_id = f"user-{_uuid.uuid4().hex[:12]}"
    token = _jwt_encode({"user_id": user_id, "iat": _dt.now(_tz.utc).isoformat()})
    return {"token": token, "user_id": user_id}


@app.post("/api/cv/upload")
async def upload_cv(request: Request):
    """Plan 131: Upload CV file, extract text, analyze via cv_processor:8020."""
    user_id = _get_user_id(request) or "anon"

    # Read raw body (multipart or plain text)
    content_type = request.headers.get("content-type", "")
    body = await request.body()

    cv_text = ""
    filename = "uploaded_cv"

    if "multipart" in content_type:
        # Parse multipart form data
        from fastapi import UploadFile  # noqa: F811
        import io

        # Simple multipart extraction — find the file content
        # For proper multipart, python-multipart handles this via FastAPI
        try:
            form = await request.form()
            file_field = form.get("file") or form.get("cv")
            if file_field and hasattr(file_field, "read"):
                file_bytes = await file_field.read()
                filename = getattr(file_field, "filename", "cv") or "cv"

                if filename.lower().endswith(".pdf"):
                    try:
                        import PyPDF2  # type: ignore[import-untyped]

                        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                        cv_text = "\n".join(page.extract_text() or "" for page in reader.pages)
                    except ImportError:
                        cv_text = file_bytes.decode("utf-8", errors="replace")
                elif filename.lower().endswith(".docx"):
                    try:
                        import docx  # type: ignore[import-untyped]

                        doc = docx.Document(io.BytesIO(file_bytes))
                        cv_text = "\n".join(p.text for p in doc.paragraphs)
                    except ImportError:
                        cv_text = file_bytes.decode("utf-8", errors="replace")
                else:
                    cv_text = file_bytes.decode("utf-8", errors="replace")
            else:
                return JSONResponse({"error": "No file field found. Use 'file' or 'cv'."}, 400)
        except Exception as exc:
            logger.warning(f"Plan 131: Form parse error: {exc}")
            cv_text = body.decode("utf-8", errors="replace")
    elif "text" in content_type or "json" in content_type:
        # Accept plain text or JSON with cv_text field
        try:
            data = json.loads(body)
            cv_text = data.get("cv_text", data.get("text", ""))
        except json.JSONDecodeError:
            cv_text = body.decode("utf-8", errors="replace")
    else:
        cv_text = body.decode("utf-8", errors="replace")

    if not cv_text or len(cv_text.strip()) < 20:
        return JSONResponse({"error": "CV text too short or empty. Upload a PDF/DOCX or paste text."}, 400)

    # Call cv_processor:8020 for AI analysis
    try:
        async with _sync_httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "http://cv-processor:8020/analyze",
                json={"user_id": user_id, "data": cv_text[:5000], "context": ["cv_upload", filename]},
            )
            if resp.status_code == 200:
                analysis = resp.json()
            else:
                analysis = {"analysis": "CV received but AI analysis unavailable.", "source": "fallback"}
    except Exception as exc:
        logger.warning(f"Plan 131: cv_processor call failed: {exc}")
        analysis = {"analysis": "CV received but AI backend unavailable.", "source": "fallback"}

    # Also get Claude to provide Swiss CV advice
    ai_advice = ""
    if AI_CHAT_ENABLED:
        try:
            ai_advice = await _ai_respond(
                f"Review this CV for Swiss job market:\n{cv_text[:2000]}",
                {"data": analysis, "domain": "document"},
                "cv-processor",
                request.client.host if request.client else "",
            )
        except Exception:
            pass

    return {
        "status": "uploaded",
        "user_id": user_id,
        "filename": filename,
        "text_length": len(cv_text),
        "analysis": analysis,
        "ai_advice": ai_advice,
    }


@app.get("/api/profile")
async def get_profile(request: Request):
    """Plan 131: Get user profile from user-profile-service."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse({"error": "No auth token. Call POST /api/auth/token first."}, 401)

    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://user-profile-service:8000/users/{user_id}")
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"Plan 131: profile fetch failed: {exc}")

    return {"user_id": user_id, "profile": None, "message": "No profile yet. Use PUT /api/profile to create one."}


@app.put("/api/profile")
async def update_profile(request: Request):
    """Plan 131: Create/update user profile."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse({"error": "No auth token. Call POST /api/auth/token first."}, 401)

    body = await request.json()
    body["user_id"] = user_id

    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(f"http://user-profile-service:8000/users/{user_id}", json=body)
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"Plan 131: profile update failed: {exc}")

    # Store in memory system as fallback
    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                "http://memory-system:8009/analyze",
                json={"user_id": user_id, "data": json.dumps(body), "context": ["profile"]},
            )
    except Exception:
        pass

    return {"status": "updated", "user_id": user_id, "profile": body}


@app.get("/api/applications")
async def get_applications(request: Request):
    """Plan 131: List user's job applications."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse({"error": "No auth token."}, 401)

    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://application-service:8000/data", params={"q": user_id})
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"Plan 131: applications fetch failed: {exc}")

    return {"user_id": user_id, "applications": [], "message": "No applications tracked yet."}


@app.post("/api/applications")
async def create_application(request: Request):
    """Plan 131: Track a new job application."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse({"error": "No auth token."}, 401)

    body = await request.json()
    body["user_id"] = user_id
    body["status"] = body.get("status", "applied")
    body["applied_at"] = _dt.now(_tz.utc).isoformat()
    body["id"] = f"app-{_uuid.uuid4().hex[:8]}"

    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://application-service:8000/process", json=body)
            if resp.status_code in (200, 201):
                return {"status": "tracked", "application": body}
    except Exception as exc:
        logger.warning(f"Plan 131: application create failed: {exc}")

    # Store via memory system as fallback
    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                "http://memory-system:8009/analyze",
                json={"user_id": user_id, "data": json.dumps(body), "context": ["application"]},
            )
    except Exception:
        pass

    return {"status": "tracked", "application": body}


@app.put("/api/applications/{app_id}")
async def update_application(app_id: str, request: Request):
    """Plan 131: Update application status."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse({"error": "No auth token."}, 401)

    body = await request.json()
    body["user_id"] = user_id
    body["updated_at"] = _dt.now(_tz.utc).isoformat()

    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(f"http://application-service:8000/data/{app_id}", json=body)
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"Plan 131: application update failed: {exc}")

    return {"status": "updated", "id": app_id, "updates": body}


@app.post("/api/apply")
async def direct_apply(request: Request):
    """Plan 131: Direct apply to a job — creates tracked application."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse({"error": "No auth token."}, 401)

    body = await request.json()
    application = {
        "id": f"app-{_uuid.uuid4().hex[:8]}",
        "user_id": user_id,
        "company": body.get("company", "Unknown"),
        "role": body.get("title", body.get("role", "Unknown")),
        "url": body.get("url", ""),
        "source": body.get("source", "jobs.ch"),
        "status": "applied",
        "applied_at": _dt.now(_tz.utc).isoformat(),
    }

    # Track in application service
    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            await client.post("http://application-service:8000/process", json=application)
    except Exception:
        pass

    # Also store in memory for AI context
    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                "http://memory-system:8009/analyze",
                json={"user_id": user_id, "data": json.dumps(application), "context": ["applied"]},
            )
    except Exception:
        pass

    return {"status": "applied", "application": application, "message": f"Application tracked for {application['role']} at {application['company']}"}


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
