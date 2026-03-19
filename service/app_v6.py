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

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
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

# L72: AI backend services use native ports (not 8000). Map service DNS → port.
# These 12 services were deployed with their own K8s Service objects on native ports.
_AI_BACKEND_PORTS: dict[str, int] = {
    "memory-system": 8009,
    "learning-system": 8010,
    "pattern-recognition": 8011,
    "decision-making": 8012,
    "career-navigator": 8017,
    "skill-bridge": 8018,
    "job-matcher": 8019,
    "cv-processor": 8020,
    "gpt4-orchestrator": 8032,
    "claude-integration": 8033,
    "embeddings-engine": 8034,
    "vector-store": 8035,
}


def _get_service_port(service_dns: str) -> int:
    """Return the correct port for a service. AI backends use native ports, all others use 8000."""
    return _AI_BACKEND_PORTS.get(service_dns, 8000)


# Persistent HTTP client — shared across all requests (connection pooling + DNS cache)
_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create persistent HTTP client on startup, close on shutdown."""
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=PROXY_TIMEOUT,
        limits=httpx.Limits(
            max_connections=50,  # L3 fix: reduced from 500 (prevents pool exhaustion)
            max_keepalive_connections=10,  # Keep-alive slots (was 200)
            keepalive_expiry=5.0,  # Expire idle connections quickly (was 30s)
        ),
    )
    logger.info(
        f"Gateway v7 started — PROXY_TIMEOUT={PROXY_TIMEOUT}s, pool=50, persistent client ready"
    )
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
        "domains": sorted(
            {v.get("domain", "general") for v in _SERVICE_CATALOG.values()}
        ),
        "services": _SERVICE_CATALOG,
    }


# ── Server-side intent routing (L56 + L64 catalog-driven) ────────────────────
# Curated routes have priority — hand-tuned patterns for core user-facing services
_CURATED_ROUTES = [
    # ── Core job-seeker journey (7 routes) ────────────────────────────────────
    {
        "patterns": ["job", "jobs", "vacancy", "position", "hire", "hiring"],
        "service": "job-search-service",
        "path": "/jobs",
        "method": "GET",
    },
    {
        "patterns": ["cv", "resume", "curriculum", "generate cv"],
        "service": "cv-generation-service",
        "path": "/cv/generate",
        "method": "POST",
    },
    {
        "patterns": ["interview", "interviews", "prep", "interview schedule"],
        "service": "interview-prep-service",
        "path": "/interviews",
        "method": "GET",
    },
    {
        "patterns": ["application", "applications", "track", "tracking", "applied"],
        "service": "application-service",
        "path": "/data",
        "method": "GET",
    },
    {
        "patterns": ["career", "advice", "growth", "path", "guidance"],
        "service": "career-search-core-service",
        "path": "/career/advice",
        "method": "GET",
    },
    {
        "patterns": ["skill", "skills", "learn", "training", "development", "course"],
        "service": "skill-development-infrastructure",
        "path": "/jobs",
        "method": "GET",
    },
    {
        "patterns": ["network", "networking", "connections", "connect", "contacts"],
        "service": "networking-service",
        "path": "/data",
        "method": "GET",
    },
    # ── User account & platform (5 routes) ────────────────────────────────────
    {
        "patterns": ["profile", "my profile", "preferences", "my account"],
        "service": "user-profile-service",
        "path": "/users",
        "method": "GET",
    },
    {
        "patterns": ["user", "users", "admin", "manage users"],
        "service": "admin-service",
        "path": "/users",
        "method": "GET",
    },
    {
        "patterns": ["notification", "notifications", "alert", "message", "inbox"],
        "service": "notification-service",
        "path": "/notifications",
        "method": "GET",
    },
    {
        "patterns": ["onboarding", "welcome", "setup", "getting started"],
        "service": "onboarding-service",
        "path": "/users",
        "method": "GET",
    },
    {
        "patterns": ["email", "smtp", "mail", "recruiter"],
        "service": "email-integration-service",
        "path": "/notifications",
        "method": "GET",
    },
    # ── Monetization & billing (3 routes) ─────────────────────────────────────
    {
        "patterns": ["payment", "billing", "invoice", "pay"],
        "service": "payment-processor-service",
        "path": "/auth/status",
        "method": "GET",
    },
    {
        "patterns": ["subscription", "subscriptions", "plan", "upgrade", "downgrade"],
        "service": "subscription-management-service",
        "path": "/subscriptions",
        "method": "GET",
    },
    {
        "patterns": ["credit", "credits", "balance", "redeem", "points"],
        "service": "credits-service",
        "path": "/payments",
        "method": "GET",
    },
    # ── Intelligence & analytics (4 routes) ───────────────────────────────────
    {
        "patterns": [
            "analytic",
            "analytics",
            "metric",
            "dashboard",
            "report",
            "insight",
        ],
        "service": "advanced-analytics-bi-service",
        "path": "/analytics/dashboard",
        "method": "GET",
    },
    {
        "patterns": ["ai", "ml", "model", "predict", "pipeline"],
        "service": "advanced-ai-ml-service",
        "path": "/ai/process",
        "method": "POST",
    },
    {
        "patterns": ["recommend", "recommendation", "personaliz", "suggest"],
        "service": "personalization-ai-adaptor",
        "path": "/models",
        "method": "GET",
    },
    {
        "patterns": ["predictive", "forecast", "prediction"],
        "service": "predictive-analytics-engine",
        "path": "/analytics/dashboard",
        "method": "GET",
    },
    # ── Operations & infrastructure (7 routes) ────────────────────────────────
    {
        "patterns": ["status", "health", "system", "monitor", "uptime"],
        "service": "monitoring-system-bulk",
        "path": "/status",
        "method": "GET",
    },
    {
        "patterns": ["security", "threat", "scan", "firewall", "vulnerability"],
        "service": "access-control-service",
        "path": "/security/status",
        "method": "GET",
    },
    {
        "patterns": ["compliance", "regulation", "regulations", "rav", "gdpr"],
        "service": "swiss-compliance-service",
        "path": "/regulations",
        "method": "GET",
    },
    {
        "patterns": ["log", "logs", "audit log", "audit trail"],
        "service": "audit-logging-service",
        "path": "/compliance/status",
        "method": "GET",
    },
    {
        "patterns": ["document", "documents", "file", "export"],
        "service": "document-management-service",
        "path": "/documents",
        "method": "GET",
    },
    {
        "patterns": ["workflow", "automation", "process", "pipeline"],
        "service": "workflow-engines-service",
        "path": "/workflows",
        "method": "GET",
    },
    {
        "patterns": ["webhook", "integration", "linkedin", "indeed", "sync"],
        "service": "webhook-integrations-service",
        "path": "/workflows",
        "method": "GET",
    },
    # ── System & config (4 routes) ────────────────────────────────────────────
    {
        "patterns": ["config", "configuration", "settings", "feature flag"],
        "service": "configuration-management",
        "path": "/config",
        "method": "GET",
    },
    {
        "patterns": ["backup", "restore", "recovery"],
        "service": "backup-recovery-system",
        "path": "/backup/status",
        "method": "GET",
    },
    {
        "patterns": ["biological", "harmony", "consciousness"],
        "service": "biological-analytics-performance-test",
        "path": "/status",
        "method": "GET",
    },
    {
        "patterns": [
            "gamification",
            "achievement",
            "badge",
            "leaderboard",
            "xp",
            "progress",
            "level",
            "points",
            "reward",
        ],
        "service": "gamification-service",
        "path": "/leaderboard",
        "method": "GET",
    },
]

# Noise words excluded from service name pattern extraction
_NOISE = {
    "service",
    "system",
    "engine",
    "api",
    "the",
    "for",
    "and",
    "test",
    "bulk",
    "category",
}


def _build_dynamic_routes() -> list:
    """L64: Build chat routes from catalog.json for ALL 219 services."""
    curated_services = {r["service"] for r in _CURATED_ROUTES}
    routes = []
    for svc_name, spec in _SERVICE_CATALOG.items():
        dns_name = svc_name.replace("_", "-")
        if dns_name in curated_services:
            continue  # already covered by curated route
        # Extract keywords from service name
        patterns = [
            w
            for w in svc_name.replace("-", "_").split("_")
            if len(w) > 2 and w.lower() not in _NOISE
        ]
        domain = spec.get("domain", "")
        if domain and domain not in patterns:
            patterns.append(domain)
        if not patterns:
            continue  # skip services with no usable keywords
        # Find first GET endpoint as default path
        endpoints = spec.get("endpoints", [])
        get_eps = [e for e in endpoints if e.get("method") == "GET"]
        path = get_eps[0]["path"] if get_eps else "/health"
        routes.append(
            {
                "patterns": patterns,
                "service": dns_name,
                "path": path,
                "method": "GET",
            }
        )
    return routes


# L64: Curated routes first (better patterns), then dynamic for remaining 199 services
_CHAT_ROUTES = _CURATED_ROUTES + _build_dynamic_routes()
logger.info(
    "L64: %d chat routes (%d curated + %d dynamic from catalog)",
    len(_CHAT_ROUTES),
    len(_CURATED_ROUTES),
    len(_CHAT_ROUTES) - len(_CURATED_ROUTES),
)


def _find_chat_route(msg: str):
    lower = msg.lower()
    for route in _CHAT_ROUTES:
        if any(p in lower for p in route["patterns"]):
            return route
    return None


from collections import deque
from datetime import datetime as _dt
from datetime import timezone as _tz

# ── L68: AI-powered conversational chat ──────────────────────────────────────
import httpx as _sync_httpx

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_CHAT_ENABLED = bool(ANTHROPIC_API_KEY)
AI_MODEL = "claude-haiku-4-5-20251001"

# ── L72: Job search query extraction ─────────────────────────────────────────
_JOB_STOP_WORDS = {
    "find",
    "show",
    "search",
    "get",
    "list",
    "me",
    "my",
    "i",
    "want",
    "need",
    "looking",
    "for",
    "the",
    "a",
    "an",
    "in",
    "at",
    "on",
    "to",
    "of",
    "and",
    "or",
    "with",
    "some",
    "any",
    "available",
    "open",
    "please",
    "can",
    "you",
    "jobs",
    "job",
    "positions",
    "position",
    "roles",
    "role",
    "opportunities",
    "vacancies",
    "openings",
    "work",
    "career",
    "careers",
}
_SWISS_LOCATIONS = {
    "zurich",
    "zürich",
    "geneva",
    "genève",
    "geneve",
    "basel",
    "bern",
    "berne",
    "lausanne",
    "winterthur",
    "lucerne",
    "luzern",
    "st gallen",
    "lugano",
    "biel",
    "thun",
    "aarau",
    "zug",
    "fribourg",
    "schaffhausen",
    "chur",
    "switzerland",
    "swiss",
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
        query = (
            query + " " + " ".join(location_parts)
            if query
            else " ".join(location_parts)
        )

    return query.strip()


if AI_CHAT_ENABLED:
    logger.info("L68: AI chat enabled (Claude Haiku)")
else:
    logger.warning(
        "L68: AI chat DISABLED — no ANTHROPIC_API_KEY found. Set via K8s secret."
    )

# ── Plan 133: AI-First Intent Classification (multilingual, replaces keywords) ──
_INTENT_CACHE: dict = (
    {}
)  # msg_lower → {"intent": ..., "language": ..., "confidence": ...}
_AI_CALL_STATS = {
    "anthropic_ok": 0,
    "anthropic_fail": 0,
    "openai_ok": 0,
    "openai_fail": 0,
    "last_error": "",
    "last_success": "",
}

_INTENT_CLASSIFIER_PROMPT = (
    "You are an intent classifier for JobTrackerPro, a Swiss job search platform.\n"
    "Classify the user's message into exactly ONE intent and detect the language.\n"
    "Return ONLY valid JSON on a single line: "
    '{"intent": "...", "language": "...", "confidence": 0.0-1.0}\n\n'
    "CRITICAL RULES:\n"
    "1. If the user NEGATES an action (don't, not, stop, cancel, keine, pas, non), classify as general-chat.\n"
    "2. Questions ABOUT a feature (should I enhance?) are general-chat, not the feature itself.\n"
    "3. cover-letter and cv-enhance are DIFFERENT intents — motivation letter / Bewerbungsschreiben / lettre de motivation = cover-letter.\n"
    "4. Job searching in ANY language = job-search (cercare lavoro, Stellen suchen, chercher emploi).\n\n"
    "Intents (choose exactly one):\n"
    "- job-search: User wants to find/search/browse jobs or vacancies\n"
    "- cv-enhance: User wants to improve/enhance/rewrite/optimize/view their CV versions\n"
    "- cover-letter: User wants to write/generate/draft a cover letter, motivation letter, Bewerbungsschreiben, lettre de motivation\n"
    "- cv-match: User wants to match their CV/profile to job listings\n"
    "- interview-prep: User wants interview preparation, coaching, or practice\n"
    "- career-advice: User wants career guidance, salary info, market advice\n"
    "- applications: User wants to track/view/manage their job applications\n"
    "- profile: User wants to view/edit their profile or account settings\n"
    "- general-chat: Greetings, follow-ups, questions about features, negations, or anything else\n\n"
    "Languages: en (English), de (German), fr (French), it (Italian)\n\n"
    "Examples:\n"
    '- "enhance my cv" → {"intent":"cv-enhance","language":"en","confidence":0.95}\n'
    '- "Lebenslauf verbessern" → {"intent":"cv-enhance","language":"de","confidence":0.95}\n'
    '- "améliorer mon CV" → {"intent":"cv-enhance","language":"fr","confidence":0.95}\n'
    '- "migliorare il mio CV" → {"intent":"cv-enhance","language":"it","confidence":0.95}\n'
    '- "show me the enhanced versions" → {"intent":"cv-enhance","language":"en","confidence":0.9}\n'
    '- "lettre de motivation pour UBS" → {"intent":"cover-letter","language":"fr","confidence":0.95}\n'
    '- "lettre de motivation" → {"intent":"cover-letter","language":"fr","confidence":0.95}\n'
    '- "Bewerbungsschreiben schreiben" → {"intent":"cover-letter","language":"de","confidence":0.95}\n'
    '- "Motivationsschreiben" → {"intent":"cover-letter","language":"de","confidence":0.95}\n'
    '- "write a cover letter for Google" → {"intent":"cover-letter","language":"en","confidence":0.95}\n'
    '- "Stellen in Zürich" → {"intent":"job-search","language":"de","confidence":0.9}\n'
    '- "cercare lavoro a Zurigo" → {"intent":"job-search","language":"it","confidence":0.9}\n'
    '- "chercher emploi à Genève" → {"intent":"job-search","language":"fr","confidence":0.9}\n'
    '- "find Python jobs in Basel" → {"intent":"job-search","language":"en","confidence":0.95}\n'
    '- "Business Analyst jobs in Zurich banking" → {"intent":"job-search","language":"en","confidence":0.95}\n'
    '- "match my cv to jobs" → {"intent":"cv-match","language":"en","confidence":0.9}\n'
    '- "prepare me for interviews" → {"intent":"interview-prep","language":"en","confidence":0.9}\n'
    '- "Swiss salary for engineers" → {"intent":"career-advice","language":"en","confidence":0.85}\n'
    '- "my applications" → {"intent":"applications","language":"en","confidence":0.9}\n'
    '- "hello" → {"intent":"general-chat","language":"en","confidence":0.95}\n'
    '- "yes find them" → {"intent":"general-chat","language":"en","confidence":0.7}\n'
    '- "don\'t enhance my cv" → {"intent":"general-chat","language":"en","confidence":0.9}\n'
    '- "should I enhance my cv?" → {"intent":"general-chat","language":"en","confidence":0.8}\n'
    '- "I don\'t want to change my CV" → {"intent":"general-chat","language":"en","confidence":0.85}\n'
    '- "stop" → {"intent":"general-chat","language":"en","confidence":0.95}\n'
)


async def _classify_intent(msg: str) -> dict:
    """Plan 133: AI-First multilingual intent classification.

    Uses Claude Haiku for fast (~200ms) intent classification.
    Supports EN, DE, FR, IT. Caches results for repeat phrases.
    Falls back to general-chat on any failure.
    """
    _default = {"intent": "general-chat", "language": "en", "confidence": 0.0}
    if not AI_CHAT_ENABLED:
        return _default

    # Fast-path cache (grows organically from classified results)
    _cache_key = msg.lower().strip()
    if _cache_key in _INTENT_CACHE:
        return _INTENT_CACHE[_cache_key]

    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": AI_MODEL,
                    "max_tokens": 60,
                    "messages": [{"role": "user", "content": msg}],
                    "system": _INTENT_CLASSIFIER_PROMPT,
                },
            )
            if resp.status_code == 200:
                raw = resp.json()["content"][0]["text"].strip()
                # Parse JSON — handle cases where model wraps in markdown
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                if raw.startswith("{"):
                    parsed = json.loads(raw)
                    result = {
                        "intent": parsed.get("intent", "general-chat"),
                        "language": parsed.get("language", "en"),
                        "confidence": float(parsed.get("confidence", 0.5)),
                    }
                    # Cache for future fast-path
                    _INTENT_CACHE[_cache_key] = result
                    _AI_CALL_STATS["anthropic_ok"] += 1
                    _AI_CALL_STATS["last_success"] = _dt.now(_tz.utc).isoformat()
                    return result
                else:
                    logger.warning(
                        f"Plan 133: Intent classifier returned non-JSON: {raw[:100]}"
                    )
            else:
                _AI_CALL_STATS["anthropic_fail"] += 1
                _AI_CALL_STATS["last_error"] = (
                    f"HTTP {resp.status_code}: {resp.text[:100]}"
                )
                logger.warning(
                    f"Plan 133: Intent classifier API error: {resp.status_code}"
                )
    except Exception as exc:
        _AI_CALL_STATS["anthropic_fail"] += 1
        _AI_CALL_STATS["last_error"] = str(exc)[:100]
        logger.warning(f"Plan 133: Intent classification failed: {exc}")

    return _default


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
        _mock_markers = [
            "job-001",
            "badge-001",
            "TechCorp AG",
            "item-001",
            "sample data",
        ]
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
        "You are a Swiss CV/resume specialist with 744 features of Swiss CV blueprint knowledge. "
        "You know the 30-component CV model, 7 Swiss layout templates, 4 color palettes, "
        "the AIDA cover letter framework, and the Bridge Model (Qualification + Motivation + Personality). "
        "Advise on Swiss CV format: professional photo, formal tone, Europass compatibility, "
        "ATS optimization, and how Swiss employers evaluate applications differently. "
        "When asked to enhance a CV, explain the 3 available versions: "
        "Conservative Swiss (2-page Europass), Modern Professional (ATS-optimized), Executive Summary (1-page impact). "
        "Guide users to upload their CV first, then request enhancement."
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
                        analysis = (
                            latest.get("analysis", "")[:300]
                            if isinstance(latest, dict)
                            else str(latest)[:300]
                        )
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
                r = await c.get(
                    "http://application-service:8000/data", params={"q": user_id}
                )
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


async def _ai_respond(
    user_msg: str,
    service_data: dict,
    service_name: str,
    client_ip: str = "",
    user_context: str = "",
) -> str:
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
            "- CV ENHANCEMENT: Generate 3 CV versions (Conservative Swiss, Modern Professional, Executive Summary)\n"
            "- COVER LETTER: AIDA framework cover letter generation customized per job\n"
            "- User profiles with saved preferences\n"
            "- Application tracking pipeline (applied/interview/offer/rejected)\n"
            "- Direct apply from search results\n"
            "- Interview preparation coaching\n"
            "- Swiss market expertise (RAV, permits, salary ranges)\n"
        )
        if user_context:
            base_prompt += (
                f"\n\nUSER CONTEXT (personalize your response):\n{user_context}\n"
            )
        domain_prompt = _INTENT_PROMPTS.get(domain, "")
        if domain_prompt:
            base_prompt += f"\n\nDomain expertise: {domain_prompt}"

        # Build user message with context
        history = _CONV_MEMORY.get(client_ip, [])[-4:]
        history_text = ""
        if history:
            history_text = (
                "Recent conversation:\n"
                + "\n".join(
                    f"{'User' if h['role']=='user' else 'Assistant'}: {h['content'][:150]}"
                    for h in history
                )
                + "\n\n"
            )

        if demo_mode:
            user_prompt = (
                f"{history_text}"
                f'User asked: "{user_msg}"\n\n'
                "The platform has live job search capabilities but the query was too broad "
                "to return specific results. Help the user refine their search — suggest "
                "they specify a role, location, or skill. Also provide helpful Swiss job "
                "market advice based on your knowledge. NEVER say you don't have access "
                "to jobs — the platform DOES search jobs.ch for specific queries."
            )
        else:
            data_json = json.dumps(service_data.get("data", {}), indent=2, default=str)[
                :2000
            ]
            user_prompt = (
                f"{history_text}"
                f'User asked: "{user_msg}"\n\n'
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
                logger.warning(
                    f"L72: Claude API error {resp.status_code}: {resp.text[:200]}"
                )
                return ""
    except Exception as exc:
        logger.warning(f"L72: AI response failed: {exc}")
        return ""


async def _ai_general_chat(
    user_msg: str, client_ip: str = "", user_context: str = ""
) -> str:
    """L68c: Handle general conversation, greetings, follow-ups, and complex queries."""
    if not AI_CHAT_ENABLED:
        return ""
    try:
        history = _CONV_MEMORY.get(client_ip, [])[-6:]
        history_block = ""
        if history:
            history_block = (
                "\n".join(
                    f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content'][:150]}"
                    for h in history
                )
                + "\n\n"
            )

        # Build service catalog summary for Claude
        svc_summary = ", ".join(
            f"{r['service']} ({' '.join(r['patterns'][:2])})"
            for r in _CURATED_ROUTES[:15]
        )

        system = (
            "You are the AI assistant for JobTrackerPro, a Swiss job search platform. "
            "Be conversational, warm, and helpful. Keep responses under 150 words.\n\n"
            "PLATFORM DELIVERS 12 CAREER BENEFITS:\n"
            "1. Smart Job Discovery — live Swiss jobs from jobs.ch (specify role + location)\n"
            "2. CV & Document Mastery — upload CV, generate 3 enhanced versions, Swiss format review\n"
            "3. Application Command — track applications (applied/interview/offer/rejected)\n"
            "4. Interview Excellence — prep coaching, practice questions, salary negotiation\n"
            "5. Career Intelligence — market insights, salary data, career path guidance\n"
            "6. Swiss Market Mastery — RAV requirements, work permits, employment law\n"
            "7. AI Career Assistant — conversational coaching in EN/DE/FR/IT\n"
            "8. Emotional Resilience — motivation, stress management during job search\n"
            "9. Professional Network — networking strategies, LinkedIn optimization\n"
            "10. Progress Analytics — application metrics, response rates, optimization\n"
            "11. Gamification & Growth — achievements, badges, XP points for progress tracking\n"
            "12. Trust & Security — Swiss privacy compliance, data protection\n\n"
            "QUICK ACTIONS: Upload CV, Enhance CV (3 versions), Cover Letter (AIDA), Interview Prep\n"
            "When relevant, mention which benefit category helps the user's need.\n"
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
_CHAT_STATS: dict = {
    "total": 0,
    "routed": 0,
    "unrouted": 0,
    "errors": 0,
    "by_service": {},
}
_CONV_MEMORY: dict = {}  # user_id_or_ip → [{"role": "user/assistant", "content": str}]
# Plan 131: Per-user context from CV uploads and profile data
_USER_CV_CONTEXT: dict = {}  # user_id → "CV summary text"


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
                            _CHAT_STATS["by_service"][svc] = (
                                _CHAT_STATS["by_service"].get(svc, 0) + 1
                            )
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


def _log_chat(
    msg: str,
    routed: bool,
    service: str = None,
    error: str = None,
    latency_ms: float = 0,
    ai_response: str = None,
    client_ip: str = "",
):
    """Record a chat interaction — persisted to JSONL file + in-memory cache."""
    logger.info(
        f"CHAT|routed={routed}|service={service or 'none'}|latency={latency_ms:.0f}ms|error={error or ''}|msg={msg[:100]}"
    )
    _CHAT_STATS["total"] += 1
    if routed:
        _CHAT_STATS["routed"] += 1
        if service:
            _CHAT_STATS["by_service"][service] = (
                _CHAT_STATS["by_service"].get(service, 0) + 1
            )
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
                            _CHAT_STATS["by_service"][svc] = (
                                _CHAT_STATS["by_service"].get(svc, 0) + 1
                            )
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
    # Use JWT user_id for conversation memory
    user_id = _get_user_id(request)
    mem_key = user_id or client_ip
    # Frontend sends conversation history — always use it (avoids multi-pod memory loss)
    frontend_history = body.get("history", [])
    if frontend_history and isinstance(frontend_history, list):
        _CONV_MEMORY[mem_key] = frontend_history[-10:]
    # Plan 133: AI-First intent classification (multilingual, replaces keyword matching)
    intent_result = await _classify_intent(msg)
    intent = intent_result.get("intent", "general-chat")
    detected_lang = intent_result.get("language", "en")
    logger.info(
        f"Plan 133: Intent={intent} lang={detected_lang} conf={intent_result.get('confidence', 0):.2f} msg={msg[:60]}"
    )

    # Legacy keyword fallback ONLY for service proxy (job-search routed via proxy if jobs.ch direct fails)
    # Do NOT run keyword matcher for general-chat — it catches false positives like "don't enhance my cv" → "cv"
    route = _find_chat_route(msg) if intent == "job-search" else None

    # Plan 131 Phase 3: Fetch user context for personalized AI responses
    user_context = await _fetch_user_context(request)
    # Add CV context if available
    if user_id and user_id in _USER_CV_CONTEXT:
        cv_summary = _USER_CV_CONTEXT[user_id][:500]
        user_context = (
            f"Uploaded CV: {cv_summary}\n{user_context}"
            if user_context
            else f"Uploaded CV: {cv_summary}"
        )

    # ── Helper: fetch CV text from Pinecone if not in this pod's memory ──
    async def _ensure_cv_context() -> str:
        """Strategic multi-pod CV context resolution — local cache → Pinecone → empty."""
        cv = _USER_CV_CONTEXT.get(user_id, "") if user_id else ""
        if not cv and user_id:
            try:
                async with _sync_httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.get(f"http://cv-processor:8020/history/{user_id}")
                    if r.status_code == 200:
                        hist = r.json().get("history", [])
                        if hist and isinstance(hist, list):
                            latest = hist[-1] if isinstance(hist[-1], dict) else {}
                            cv = latest.get("data", "")
                            if cv:
                                _USER_CV_CONTEXT[user_id] = cv
                                logger.info(
                                    f"Plan 133: Restored CV from Pinecone for {user_id} ({len(cv)} chars)"
                                )
            except Exception as e:
                logger.warning(f"Plan 133: Pinecone CV fetch failed for {user_id}: {e}")
        return cv

    # ── Intent: job-search — real jobs.ch listings, ALL 4 Swiss languages ──
    if intent == "job-search":
        search_terms = _extract_job_search_terms(msg)
        if search_terms:
            try:
                from job_scraper.scraper import JobScraper

                _scraper = JobScraper()
                # Extract location separately for jobs.ch location param
                _loc = ""
                _query_parts = search_terms.split()
                for _sw in (
                    "zurich",
                    "zürich",
                    "bern",
                    "basel",
                    "geneva",
                    "genève",
                    "lausanne",
                    "lucerne",
                    "luzern",
                    "lugano",
                    "winterthur",
                    "zug",
                    "thun",
                    "fribourg",
                    "schaffhausen",
                    "chur",
                    "st gallen",
                ):
                    if _sw in [p.lower() for p in _query_parts]:
                        _loc = _sw
                        _query_parts = [p for p in _query_parts if p.lower() != _sw]
                        break
                _core_query = " ".join(
                    w
                    for w in _query_parts
                    if w.lower()
                    not in ("sector", "industry", "field", "area", "bereich")
                ).strip()

                # ── Strategic 4-language Swiss job search ──
                # Switzerland has 4 official languages. Job titles are posted in
                # the local language of the canton. A search MUST cover all 4.
                _ROLE_TRANSLATIONS = {
                    "project manager": {
                        "de": "Projektleiter",
                        "fr": "Chef de projet",
                        "it": "Responsabile di progetto",
                    },
                    "project management": {
                        "de": "Projektleitung",
                        "fr": "Gestion de projet",
                        "it": "Gestione progetti",
                    },
                    "business analyst": {
                        "de": "Business Analyst",
                        "fr": "Analyste d'affaires",
                        "it": "Analista aziendale",
                    },
                    "software engineer": {
                        "de": "Software Entwickler",
                        "fr": "Ingénieur logiciel",
                        "it": "Ingegnere software",
                    },
                    "product manager": {
                        "de": "Produktmanager",
                        "fr": "Chef de produit",
                        "it": "Product Manager",
                    },
                    "data analyst": {
                        "de": "Datenanalyst",
                        "fr": "Analyste de données",
                        "it": "Analista dati",
                    },
                    "it manager": {
                        "de": "IT-Leiter",
                        "fr": "Responsable IT",
                        "it": "Responsabile IT",
                    },
                    "program manager": {
                        "de": "Programmleiter",
                        "fr": "Directeur de programme",
                        "it": "Responsabile programma",
                    },
                    "consultant": {
                        "de": "Berater",
                        "fr": "Consultant",
                        "it": "Consulente",
                    },
                    "team lead": {
                        "de": "Teamleiter",
                        "fr": "Chef d'équipe",
                        "it": "Capo squadra",
                    },
                }

                # Build list of queries: original + all language variants
                _queries = [_core_query]
                _core_lower = _core_query.lower()
                for _en_role, _translations in _ROLE_TRANSLATIONS.items():
                    if _en_role in _core_lower:
                        for _lang, _translated in _translations.items():
                            _q = _core_lower.replace(_en_role, _translated)
                            if _q not in [q.lower() for q in _queries]:
                                _queries.append(_q)
                        break  # Only match first role found

                # Execute all queries concurrently
                import asyncio as _aio

                _search_tasks = [
                    _scraper.search(q, location=_loc, limit=15) for q in _queries
                ]
                _all_results = await _aio.gather(*_search_tasks, return_exceptions=True)

                # Merge and deduplicate
                jobs = []
                _seen = set()
                for _result in _all_results:
                    if isinstance(_result, Exception):
                        continue
                    for j in _result:
                        _k = (j.get("title", "").lower(), j.get("company", "").lower())
                        if _k not in _seen:
                            jobs.append(j)
                            _seen.add(_k)

                _lang_count = sum(
                    1 for r in _all_results if not isinstance(r, Exception) and r
                )
                logger.info(
                    f"Plan 134: 4-lang search '{_core_query}' → {len(jobs)} jobs from {_lang_count}/{len(_queries)} queries"
                )
                if jobs:
                    jobs_data = {
                        "jobs": jobs,
                        "total": len(jobs),
                        "query": search_terms,
                        "source": "jobs.ch",
                    }
                    ai_resp = await _ai_respond(
                        msg,
                        {"data": jobs_data, "source": "live"},
                        "job-search-service",
                        mem_key,
                        user_context=user_context,
                    )
                    _log_chat(
                        msg,
                        routed=True,
                        service="job-search-service",
                        latency_ms=(_t.time() - t0) * 1000,
                        ai_response=ai_resp,
                        client_ip=client_ip,
                    )
                    if mem_key:
                        if mem_key not in _CONV_MEMORY:
                            _CONV_MEMORY[mem_key] = []
                        _CONV_MEMORY[mem_key].append({"role": "user", "content": msg})
                        if ai_resp:
                            _CONV_MEMORY[mem_key].append(
                                {"role": "assistant", "content": ai_resp[:200]}
                            )
                        _CONV_MEMORY[mem_key] = _CONV_MEMORY[mem_key][-10:]
                    return {
                        "routed": True,
                        "service": "job-search-service",
                        "path": "/jobs",
                        "intent": intent,
                        "language": detected_lang,
                        "data": jobs_data,
                        "ai_response": ai_resp,
                    }
            except ImportError:
                logger.warning(
                    "Plan 134: job_scraper module not available, falling back to proxy"
                )
            except Exception as exc:
                logger.warning(f"Plan 134: jobs.ch search failed: {exc}")
        # Fall through to proxy route if jobs.ch failed

    # ── Intent: cv-match ──
    if intent == "cv-match":
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
            except Exception as e:
                logger.warning(f"Plan 133: CV match fetch failed: {e}")
        if not cv_skills and user_context:
            for line in user_context.split("\n"):
                if "Skills:" in line or "Target:" in line:
                    cv_skills += line + " "
        if cv_skills:
            search_terms = _extract_job_search_terms(cv_skills)
            route = {
                "service": "job-search-service",
                "path": "/jobs",
                "method": "GET",
                "patterns": ["match"],
            }
            msg = f"Find jobs matching: {search_terms}"

    # ── Intent: cv-enhance ──
    if intent == "cv-enhance":
        cv_text = await _ensure_cv_context()
        if not cv_text:
            # No CV uploaded — guide user
            ai_resp = (
                "I'd love to enhance your CV! To generate 3 optimized versions "
                "(Conservative Swiss, Modern Professional, Executive Summary), "
                "please **upload your CV first** using the 📄 button above. "
                "Once uploaded, just say 'enhance my CV' and I'll create all 3 versions."
            )
            if mem_key:
                if mem_key not in _CONV_MEMORY:
                    _CONV_MEMORY[mem_key] = []
                _CONV_MEMORY[mem_key].append({"role": "user", "content": msg})
                _CONV_MEMORY[mem_key].append({"role": "assistant", "content": ai_resp})
                _CONV_MEMORY[mem_key] = _CONV_MEMORY[mem_key][-10:]
            return {
                "routed": True,
                "service": "cv-enhancement",
                "path": "/enhance",
                "data": None,
                "ai_response": ai_resp,
            }

        # CV exists — call cv_processor:8020/enhance
        try:
            # Extract target info from message or context
            target_role = ""
            target_company = ""
            for line in user_context.split("\n"):
                if "Target:" in line:
                    target_role = line.split("Target:")[-1].strip()
            async with _sync_httpx.AsyncClient(timeout=90.0) as c:
                resp = await c.post(
                    "http://cv-processor:8020/enhance",
                    json={
                        "user_id": user_id,
                        "cv_text": cv_text[:5000],
                        "target_role": target_role,
                    },
                )
                if resp.status_code == 200:
                    enhance_data = resp.json()
                    versions = enhance_data.get("versions", {})
                    # Build response with all 3 versions — show full content
                    parts = ["Here are **3 enhanced versions** of your CV:\n"]
                    for i, (key, ver) in enumerate(versions.items(), 1):
                        letter = chr(64 + i)  # A, B, C
                        parts.append(
                            f"---\n### Option {letter}: {ver.get('name', key)}"
                        )
                        parts.append(f"*{ver.get('description', '')}*\n")
                        cv_text_full = ver.get("cv_text", "")
                        parts.append(f"{cv_text_full}\n")
                    parts.append(
                        "---\n**Next steps:** Tell me which version you prefer, or ask me to "
                        "**write a cover letter** for a specific job application."
                    )
                    ai_resp = "\n".join(parts)
                else:
                    ai_resp = "CV enhancement is processing but took longer than expected. Please try again in a moment."
        except Exception as exc:
            logger.warning(f"Plan 132: CV enhance failed: {exc}")
            ai_resp = "CV enhancement service is temporarily unavailable. Please try again shortly."

        if mem_key:
            if mem_key not in _CONV_MEMORY:
                _CONV_MEMORY[mem_key] = []
            _CONV_MEMORY[mem_key].append({"role": "user", "content": msg})
            _CONV_MEMORY[mem_key].append(
                {"role": "assistant", "content": ai_resp[:500]}
            )
            _CONV_MEMORY[mem_key] = _CONV_MEMORY[mem_key][-10:]
        return {
            "routed": True,
            "service": "cv-enhancement",
            "path": "/enhance",
            "data": None,
            "ai_response": ai_resp,
        }

    # ── Intent: cover-letter ──
    if intent == "cover-letter":
        cv_text = await _ensure_cv_context()
        if not cv_text:
            ai_resp = (
                "I can generate a professional AIDA cover letter for you! "
                "Please **upload your CV first** using the 📄 button, then say "
                "'Write a cover letter for [Company Name] - [Job Title]'."
            )
        else:
            # Extract company and job from message
            _msg_lower = msg.lower()
            company = ""
            job_title = ""
            # Try to parse "cover letter for [Company] - [Role]"
            for sep in [" for ", " at ", " to "]:
                if sep in _msg_lower:
                    after = msg[_msg_lower.index(sep) + len(sep) :]
                    if " - " in after:
                        company, job_title = after.split(" - ", 1)
                    elif " as " in after.lower():
                        parts = after.lower().split(" as ", 1)
                        company = parts[0]
                        job_title = parts[1] if len(parts) > 1 else ""
                    else:
                        company = after.strip()
                    break
            company = company.strip() or "the target company"
            job_title = job_title.strip() or "the advertised position"

            try:
                async with _sync_httpx.AsyncClient(timeout=60.0) as c:
                    resp = await c.post(
                        "http://cv-processor:8020/cover-letter",
                        json={
                            "user_id": user_id,
                            "cv_text": cv_text[:3000],
                            "job_title": job_title,
                            "company_name": company,
                        },
                    )
                    if resp.status_code == 200:
                        cl_data = resp.json()
                        ai_resp = (
                            f"Here's your **AIDA cover letter** for {company}:\n\n"
                            f"{cl_data.get('cover_letter', 'Generation in progress...')}\n\n"
                            "---\n*Generated using the AIDA framework (Attention → Interest → Desire → Action). "
                            "Feel free to ask me to adjust the tone or emphasis.*"
                        )
                    else:
                        ai_resp = "Cover letter generation is processing. Please try again in a moment."
            except Exception as exc:
                logger.warning(f"Plan 132: Cover letter failed: {exc}")
                ai_resp = "Cover letter service is temporarily unavailable. Please try again shortly."

        if mem_key:
            if mem_key not in _CONV_MEMORY:
                _CONV_MEMORY[mem_key] = []
            _CONV_MEMORY[mem_key].append({"role": "user", "content": msg})
            _CONV_MEMORY[mem_key].append(
                {"role": "assistant", "content": ai_resp[:500]}
            )
            _CONV_MEMORY[mem_key] = _CONV_MEMORY[mem_key][-10:]
        return {
            "routed": True,
            "service": "cv-enhancement",
            "path": "/cover-letter",
            "data": None,
            "ai_response": ai_resp,
        }

    # Plan 133: AI-classified intents that don't have a dedicated handler → general chat
    # Also handles: interview-prep, career-advice, applications, profile, general-chat
    if not route:
        # For classified intents without dedicated service proxy, use AI general chat
        ai_fallback = await _ai_general_chat(msg, mem_key, user_context=user_context)
        _log_chat(
            msg,
            routed=False,
            latency_ms=(_t.time() - t0) * 1000,
            ai_response=ai_fallback,
            client_ip=client_ip,
        )
        if mem_key:
            if mem_key not in _CONV_MEMORY:
                _CONV_MEMORY[mem_key] = []
            _CONV_MEMORY[mem_key].append({"role": "user", "content": msg})
            if ai_fallback:
                _CONV_MEMORY[mem_key].append(
                    {"role": "assistant", "content": ai_fallback[:200]}
                )
            _CONV_MEMORY[mem_key] = _CONV_MEMORY[mem_key][-10:]
        return {
            "routed": True,
            "service": "ai-assistant",
            "path": "/chat",
            "intent": intent,
            "language": detected_lang,
            "data": None,
            "ai_response": ai_fallback,
        }
    svc_dns = service_to_dns(route["service"])
    # L72: Extract meaningful search terms for job queries instead of raw message
    _search_query = msg
    # If message is short/vague, augment with conversation context
    _short_msg = len(msg.split()) < 6
    _has_pronoun = any(
        w in msg.lower()
        for w in ("them", "those", "it", "that", "these", "yes", "please")
    )
    if (_short_msg or _has_pronoun) and mem_key in _CONV_MEMORY:
        # Pull context from recent conversation
        recent = _CONV_MEMORY.get(mem_key, [])[-6:]
        context_msgs = [
            h["content"]
            for h in recent
            if h["role"] == "user" and len(h["content"]) > 10
        ]
        if context_msgs:
            _search_query = " ".join(context_msgs[-3:]) + " " + msg
    if route.get("service") in (
        "job-search-service",
        "career-search-core-service",
        "job-discovery-service",
    ):
        _search_query = _extract_job_search_terms(_search_query)
    _query_params = {"q": _search_query} if _search_query else {}
    url = f"http://{svc_dns}:{_get_service_port(svc_dns)}{route['path']}"
    try:
        method = route["method"]
        if method == "GET":
            resp = await _http_client.get(
                url, params=_query_params, timeout=PROXY_TIMEOUT
            )
        else:
            resp = await _http_client.post(
                url, json={"message": msg}, timeout=PROXY_TIMEOUT
            )
        service_data = resp.json()
        # L68: Generate AI conversational response with conversation memory
        client_ip = request.client.host if request.client else ""
        ai_response = await _ai_respond(
            msg, service_data, route["service"], mem_key, user_context=user_context
        )
        # Save to conversation memory
        if mem_key:
            if mem_key not in _CONV_MEMORY:
                _CONV_MEMORY[mem_key] = []
            _CONV_MEMORY[mem_key].append({"role": "user", "content": msg})
            if ai_response:
                _CONV_MEMORY[mem_key].append(
                    {"role": "assistant", "content": ai_response[:200]}
                )
            # Keep last 10 turns
            _CONV_MEMORY[mem_key] = _CONV_MEMORY[mem_key][-10:]
        latency = (_t.time() - t0) * 1000
        _log_chat(
            msg,
            routed=True,
            service=route["service"],
            latency_ms=latency,
            ai_response=ai_response,
            client_ip=client_ip,
        )
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
        _log_chat(
            msg,
            routed=True,
            service=route["service"],
            error=str(exc),
            latency_ms=latency,
            client_ip=client_ip,
        )
        logger.warning(f"chat/route error for {route['service']}: {exc}")
        # L72: AI fallback when service is unreachable — user still gets a helpful response
        ai_fallback = await _ai_general_chat(msg, mem_key, user_context=user_context)
        if mem_key:
            if mem_key not in _CONV_MEMORY:
                _CONV_MEMORY[mem_key] = []
            _CONV_MEMORY[mem_key].append({"role": "user", "content": msg})
            if ai_fallback:
                _CONV_MEMORY[mem_key].append(
                    {"role": "assistant", "content": ai_fallback[:200]}
                )
            _CONV_MEMORY[mem_key] = _CONV_MEMORY[mem_key][-10:]
        return {
            "routed": True,
            "service": route["service"],
            "path": route["path"],
            "data": None,
            "ai_response": ai_fallback,
        }


# ── Plan 131: Core Product Features — JWT + Upload + Profile + Applications ────

import base64 as _b64
import hashlib as _hashlib
import hmac as _hmac
import uuid as _uuid

_JWT_SECRET = os.getenv(
    "JWT_SECRET", "ffc86ecae403d31816cfed50b92dd0815b61de5fd2807e93154d3b2ce6d58d0a"
)


def _jwt_encode(payload: dict) -> str:
    """Minimal JWT encoder (HS256) — no external dependency."""
    header = _b64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=")
    body = _b64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).rstrip(
        b"="
    )
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
        import io

        try:
            form = await request.form()
            file_field = form.get("file") or form.get("cv")
            if not file_field or not hasattr(file_field, "read"):
                return JSONResponse(
                    {"error": "No file field found. Use field name 'file' or 'cv'."},
                    400,
                )

            file_bytes = await file_field.read()
            filename = getattr(file_field, "filename", "cv") or "cv"
            logger.info(
                f"Plan 131: Upload received: {filename} ({len(file_bytes)} bytes)"
            )

            if not file_bytes or len(file_bytes) < 10:
                return JSONResponse(
                    {"error": f"File '{filename}' is empty or too small."}, 400
                )

            if filename.lower().endswith(".pdf"):
                try:
                    import PyPDF2  # type: ignore[import-untyped]

                    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    cv_text = "\n".join(
                        page.extract_text() or "" for page in reader.pages
                    )
                    logger.info(
                        f"Plan 131: PDF parsed — {len(cv_text)} chars from {len(reader.pages)} pages"
                    )
                except Exception as pdf_err:
                    logger.warning(f"Plan 131: PDF parse failed: {pdf_err}")
                    cv_text = file_bytes.decode("utf-8", errors="replace")

            elif filename.lower().endswith(".docx") or filename.lower().endswith(
                ".doc"
            ):
                try:
                    import docx  # type: ignore[import-untyped]

                    doc = docx.Document(io.BytesIO(file_bytes))
                    # Extract from paragraphs
                    parts = [p.text for p in doc.paragraphs if p.text.strip()]
                    # Extract from tables (CVs commonly use table layouts)
                    for table in doc.tables:
                        for row in table.rows:
                            for cell in row.cells:
                                txt = cell.text.strip()
                                if txt and txt not in parts:
                                    parts.append(txt)
                    cv_text = "\n".join(parts)
                    logger.info(
                        f"Plan 131: DOCX parsed — {len(cv_text)} chars, "
                        f"{len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables"
                    )
                except Exception as docx_err:
                    logger.warning(f"Plan 131: DOCX parse failed: {docx_err}")
                    # Fallback: extract text from DOCX XML via zipfile
                    try:
                        import re
                        import zipfile

                        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                            xml_content = ""
                            for name in zf.namelist():
                                if name.endswith(".xml"):
                                    xml_content += zf.read(name).decode(
                                        "utf-8", errors="replace"
                                    )
                        # Extract text between XML tags
                        cv_text = " ".join(re.findall(r">([^<]{2,})<", xml_content))
                        cv_text = re.sub(r"\s+", " ", cv_text).strip()
                        logger.info(
                            f"Plan 131: DOCX XML fallback — {len(cv_text)} chars"
                        )
                    except Exception:
                        cv_text = ""
            else:
                cv_text = file_bytes.decode("utf-8", errors="replace")

        except Exception as exc:
            logger.warning(f"Plan 131: Form parse error: {exc}")
            return JSONResponse({"error": f"File upload failed: {exc}"}, 400)
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
        # Last resort: try extracting ANY text from the raw bytes
        import re as _re

        raw_text = body.decode("utf-8", errors="replace") if body else ""
        # For DOCX/PDF binary: try to find text runs in the raw data
        if filename.lower().endswith((".docx", ".doc")):
            try:
                import io as _io
                import zipfile

                with zipfile.ZipFile(_io.BytesIO(file_bytes)) as zf:
                    for name in sorted(zf.namelist()):
                        if "document" in name.lower() and name.endswith(".xml"):
                            xml = zf.read(name).decode("utf-8", errors="replace")
                            # Extract all text content between w:t tags
                            texts = _re.findall(r"<w:t[^>]*>([^<]+)</w:t>", xml)
                            if texts:
                                cv_text = " ".join(texts)
                                logger.info(
                                    f"Plan 131: DOCX w:t extraction — {len(cv_text)} chars from {name}"
                                )
            except Exception as last_err:
                logger.warning(f"Plan 131: DOCX last-resort failed: {last_err}")

        if not cv_text or len(cv_text.strip()) < 20:
            return JSONResponse(
                {
                    "error": f"Could not extract text from '{filename}'. "
                    f"Got {len(cv_text.strip()) if cv_text else 0} chars. "
                    "Try a different format (PDF, DOCX, or paste text as JSON).",
                    "filename": filename,
                    "content_type": content_type,
                },
                400,
            )

    # Call cv_processor:8020 for AI analysis (GPT-4 + Pinecone)
    try:
        async with _sync_httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "http://cv-processor:8020/analyze",
                json={
                    "user_id": user_id,
                    "data": cv_text[:5000],
                    "context": ["cv_upload", filename],
                },
            )
            if resp.status_code == 200:
                analysis = resp.json()
            else:
                analysis = {
                    "analysis": "CV received but AI analysis unavailable.",
                    "source": "fallback",
                }
    except Exception as exc:
        logger.warning(f"Plan 131: cv_processor call failed: {exc}")
        analysis = {
            "analysis": "CV received but AI backend unavailable.",
            "source": "fallback",
        }

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

    # Store CV context for conversation personalization
    if user_id and cv_text:
        _USER_CV_CONTEXT[user_id] = cv_text[:8000]
        # Also store in conversation memory so Claude remembers
        mem_key = user_id
        if mem_key not in _CONV_MEMORY:
            _CONV_MEMORY[mem_key] = []
        _CONV_MEMORY[mem_key].append(
            {
                "role": "user",
                "content": f"[CV UPLOADED: {filename}] {cv_text[:500]}",
            }
        )
        if ai_advice:
            _CONV_MEMORY[mem_key].append(
                {
                    "role": "assistant",
                    "content": ai_advice[:500],
                }
            )

    return {
        "status": "uploaded",
        "user_id": user_id,
        "filename": filename,
        "text_length": len(cv_text),
        "analysis": analysis,
        "ai_advice": ai_advice,
    }


@app.post("/api/cv/enhance")
async def enhance_cv_api(request: Request):
    """Plan 132: Generate 3 enhanced CV versions from uploaded CV."""
    user_id = _get_user_id(request) or "anon"
    cv_text = _USER_CV_CONTEXT.get(user_id, "")

    # Strategic: fetch from Pinecone if not in this pod's memory
    if not cv_text and user_id != "anon":
        try:
            async with _sync_httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"http://cv-processor:8020/history/{user_id}")
                if r.status_code == 200:
                    hist = r.json().get("history", [])
                    if hist and isinstance(hist, list):
                        latest = hist[-1] if isinstance(hist[-1], dict) else {}
                        cv_text = latest.get("data", "")
                        if cv_text:
                            _USER_CV_CONTEXT[user_id] = cv_text
        except Exception:
            pass

    # Also accept cv_text in request body
    try:
        body = await request.json()
        if body.get("cv_text"):
            cv_text = body["cv_text"]
        target_role = body.get("target_role", "")
        target_company = body.get("target_company", "")
        target_industry = body.get("target_industry", "")
    except Exception:
        target_role = target_company = target_industry = ""

    if not cv_text or len(cv_text.strip()) < 20:
        return JSONResponse(
            {"error": "No CV found. Upload your CV first via /api/cv/upload."}, 400
        )

    try:
        async with _sync_httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                "http://cv-processor:8020/enhance",
                json={
                    "user_id": user_id,
                    "cv_text": cv_text[:5000],
                    "target_role": target_role,
                    "target_company": target_company,
                    "target_industry": target_industry,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            return JSONResponse(
                {"error": "CV enhancement failed", "detail": resp.text[:200]},
                resp.status_code,
            )
    except Exception as exc:
        logger.warning(f"Plan 132: CV enhance API failed: {exc}")
        return JSONResponse({"error": f"Enhancement service unavailable: {exc}"}, 503)


@app.post("/api/cv/cover-letter")
async def cover_letter_api(request: Request):
    """Plan 132: Generate AIDA cover letter from CV + job details."""
    user_id = _get_user_id(request) or "anon"
    cv_text = _USER_CV_CONTEXT.get(user_id, "")

    # Strategic: fetch from Pinecone if not in this pod's memory
    if not cv_text and user_id != "anon":
        try:
            async with _sync_httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"http://cv-processor:8020/history/{user_id}")
                if r.status_code == 200:
                    hist = r.json().get("history", [])
                    if hist and isinstance(hist, list):
                        latest = hist[-1] if isinstance(hist[-1], dict) else {}
                        cv_text = latest.get("data", "")
                        if cv_text:
                            _USER_CV_CONTEXT[user_id] = cv_text
        except Exception:
            pass

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "JSON body required with job_title and company_name"}, 400
        )

    if body.get("cv_text"):
        cv_text = body["cv_text"]
    if not cv_text or len(cv_text.strip()) < 20:
        return JSONResponse(
            {"error": "No CV found. Upload your CV first via /api/cv/upload."}, 400
        )

    job_title = body.get("job_title", "")
    company_name = body.get("company_name", "")
    if not job_title or not company_name:
        return JSONResponse({"error": "job_title and company_name are required"}, 400)

    try:
        async with _sync_httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "http://cv-processor:8020/cover-letter",
                json={
                    "user_id": user_id,
                    "cv_text": cv_text[:3000],
                    "job_title": job_title,
                    "company_name": company_name,
                    "job_description": body.get("job_description", ""),
                    "company_values": body.get("company_values", ""),
                },
            )
            if resp.status_code == 200:
                return resp.json()
            return JSONResponse(
                {"error": "Cover letter generation failed", "detail": resp.text[:200]},
                resp.status_code,
            )
    except Exception as exc:
        logger.warning(f"Plan 132: Cover letter API failed: {exc}")
        return JSONResponse({"error": f"Cover letter service unavailable: {exc}"}, 503)


@app.get("/api/profile")
async def get_profile(request: Request):
    """Plan 131: Get user profile from user-profile-service."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse(
            {"error": "No auth token. Call POST /api/auth/token first."}, 401
        )

    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://user-profile-service:8000/users/{user_id}")
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"Plan 131: profile fetch failed: {exc}")

    return {
        "user_id": user_id,
        "profile": None,
        "message": "No profile yet. Use PUT /api/profile to create one.",
    }


@app.put("/api/profile")
async def update_profile(request: Request):
    """Plan 131: Create/update user profile."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse(
            {"error": "No auth token. Call POST /api/auth/token first."}, 401
        )

    body = await request.json()
    body["user_id"] = user_id

    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(
                f"http://user-profile-service:8000/users/{user_id}", json=body
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"Plan 131: profile update failed: {exc}")

    # Store in memory system as fallback
    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                "http://memory-system:8009/analyze",
                json={
                    "user_id": user_id,
                    "data": json.dumps(body),
                    "context": ["profile"],
                },
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
            resp = await client.get(
                f"http://application-service:8000/data", params={"q": user_id}
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"Plan 131: applications fetch failed: {exc}")

    return {
        "user_id": user_id,
        "applications": [],
        "message": "No applications tracked yet.",
    }


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
            resp = await client.post(
                "http://application-service:8000/process", json=body
            )
            if resp.status_code in (200, 201):
                return {"status": "tracked", "application": body}
    except Exception as exc:
        logger.warning(f"Plan 131: application create failed: {exc}")

    # Store via memory system as fallback
    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                "http://memory-system:8009/analyze",
                json={
                    "user_id": user_id,
                    "data": json.dumps(body),
                    "context": ["application"],
                },
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
            resp = await client.put(
                f"http://application-service:8000/data/{app_id}", json=body
            )
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
            await client.post(
                "http://application-service:8000/process", json=application
            )
    except Exception:
        pass

    # Also store in memory for AI context
    try:
        async with _sync_httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                "http://memory-system:8009/analyze",
                json={
                    "user_id": user_id,
                    "data": json.dumps(application),
                    "context": ["applied"],
                },
            )
    except Exception:
        pass

    return {
        "status": "applied",
        "application": application,
        "message": f"Application tracked for {application['role']} at {application['company']}",
    }


@app.get("/health")
async def health():
    """Gateway health check — includes AI engine status (Plan 133)."""
    _ai_ok = _AI_CALL_STATS["anthropic_ok"]
    _ai_fail = _AI_CALL_STATS["anthropic_fail"]
    _ai_status = (
        "operational"
        if _ai_ok > 0 and _ai_fail < _ai_ok
        else ("degraded" if _ai_fail > 0 else "unknown")
    )
    return {
        "status": "healthy",
        "version": 7,
        "architecture": "1-pod-per-service",
        "proxy_timeout": PROXY_TIMEOUT,
        "ai_chat": AI_CHAT_ENABLED,
        "ai_status": _ai_status,
        "ai_stats": {
            "anthropic_ok": _ai_ok,
            "anthropic_fail": _ai_fail,
            "last_error": (
                _AI_CALL_STATS["last_error"][:200]
                if _AI_CALL_STATS["last_error"]
                else ""
            ),
        },
        "intent_cache_size": len(_INTENT_CACHE),
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
    url = f"http://{svc_dns}:{_get_service_port(svc_dns)}/{path}"
    if request.query_params:
        url += "?" + str(request.query_params)

    logger.info(f"PROXY {request.method} {service_name}/{path} → {url}")

    try:
        resp = await _http_client.request(
            method=request.method,
            url=url,
            headers={
                k: v
                for k, v in request.headers.items()
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
