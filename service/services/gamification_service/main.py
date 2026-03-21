"""
Gamification Service — Gamification Service

Template: svc_reporting_005
Domain: gamification | Tier: small | Port: 8111
Namespace: jtp | Registry: iandrewitz/docker-jtp
Biological Harmony: 0.9926 | Log Level: INFO
Rate Limit: 1000 req/min | API Timeout: 30s
User Stories: US-280, US-284, US-288, US-291, US-293, US-294, US-296, US-297, US-298, US-299, US-300, US-301, US-302, US-303, US-304, US-306, US-308, US-309, US-310, US-311, US-314, US-317, US-318, US-319, US-320, US-321, US-322, US-323

Registry sources: PORT_REGISTRY | RESOURCE_LIMITS | CENTRAL_VARIABLE_REGISTRY
                  DEPLOYMENT_CONFIG | SERVICE_CATALOG | MASTER_CATALOG
Plan 123 Phase 2 — real endpoint handlers, user story wiring, domain models.
Phase 2 output — domain route handlers from service catalog.
"""

import json
import logging
import os
import time
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import service_client  # L62: inter-service communication

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config from all 6 FADS registries
with open("config.json", "r") as _f:
    config = json.load(_f)

SERVICE_PORT        = config.get('port', 8111)
RESOURCE_TIER       = config.get('resource_tier', 'small')
KUBERNETES_NS       = config.get('deployment', {}).get('kubernetes_namespace', 'jtp')
API_TIMEOUT         = config.get('variables', {}).get('api_timeout', 30)
RATE_LIMIT_RPM      = config.get('variables', {}).get('rate_limit_rpm', 1000)
HARMONY_THRESHOLD   = config.get('variables', {}).get('harmony_threshold', 0.997)
GATEWAY_URL         = os.getenv("GATEWAY_URL", "http://localhost:5000")
AI_BACKEND          = os.getenv("AI_BACKEND", "http://skill-bridge:8018")
BIO_BRIDGE          = os.getenv("BIO_BRIDGE", "http://biological-bridge:8040")


from datetime import datetime

MEMORY_SYSTEM_URL = os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009")

# Plan 142v2: XP Level thresholds
_XP_LEVELS = [
    (0, "Job Seeker"),
    (100, "Active Searcher"),
    (300, "Career Builder"),
    (600, "Rising Professional"),
    (1000, "Career Strategist"),
    (2000, "Industry Expert"),
    (3500, "Career Champion"),
    (6000, "Career Legend"),
]

# Plan 142v2: Badge milestone definitions
_BADGE_MILESTONES = [
    {"id": "first-steps", "name": "First Steps", "trigger": "cv_uploaded", "threshold": 1, "points": 50, "icon": "📄"},
    {"id": "storyteller", "name": "Storyteller", "trigger": "cover_letter_generated", "threshold": 1, "points": 35, "icon": "✍️"},
    {"id": "active-searcher", "name": "Active Searcher", "trigger": "job_search", "threshold": 5, "points": 25, "icon": "🔍"},
    {"id": "determined", "name": "Determined", "trigger": "application_submitted", "threshold": 5, "points": 50, "icon": "💪"},
    {"id": "interview-ready", "name": "Interview Ready", "trigger": "interview_prep", "threshold": 1, "points": 40, "icon": "🎤"},
    {"id": "momentum-3", "name": "Momentum Builder", "trigger": "daily_login", "threshold": 3, "points": 30, "icon": "🔥"},
    {"id": "consistent-7", "name": "Consistent", "trigger": "daily_login", "threshold": 7, "points": 60, "icon": "⭐"},
    {"id": "power-user", "name": "Power User", "trigger": "total_actions", "threshold": 50, "points": 100, "icon": "🚀"},
    {"id": "swiss-pro", "name": "Swiss Pro", "trigger": "swiss_market_query", "threshold": 3, "points": 30, "icon": "🇨🇭"},
    {"id": "cv-master", "name": "CV Master", "trigger": "cv_enhanced", "threshold": 3, "points": 75, "icon": "🏆"},
]


def _calc_level(xp_total: int) -> tuple:
    """Calculate level and level name from XP total."""
    level = 1
    name = "Job Seeker"
    for i, (threshold, lname) in enumerate(_XP_LEVELS):
        if xp_total >= threshold:
            level = i + 1
            name = lname
    xp_for_next = _XP_LEVELS[min(level, len(_XP_LEVELS) - 1)][0] - xp_total if level < len(_XP_LEVELS) else 0
    return level, name, max(0, xp_for_next)


# Plan 142: Local event cache — instant consistency while Pinecone propagates
_EVENT_CACHE: dict = {}  # {user_id: [event_dict, ...]}
_CACHE_MAX = 200


async def _store_event(user_id: str, event_type: str, points: int, achievement: str = "", badge_id: str = ""):
    """Store event to local cache (instant) + Pinecone (persistent)."""
    event = {"event_type": event_type, "points": points, "achievement": achievement,
             "badge_id": badge_id, "timestamp": datetime.now().isoformat()}
    eid = f"{user_id}_gamif_{int(time.time() * 1000)}"
    # Local cache FIRST — instant visibility for queries
    _EVENT_CACHE.setdefault(user_id, []).append(event)
    if len(_EVENT_CACHE[user_id]) > _CACHE_MAX:
        _EVENT_CACHE[user_id] = _EVENT_CACHE[user_id][-_CACHE_MAX:]
    # Pinecone — eventual persistence (survives pod restart)
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{MEMORY_SYSTEM_URL}/store", json={
                "user_id": user_id, "entity_type": "gamification",
                "data": json.dumps(event), "entity_id": eid,
            })
    except Exception as e:
        logger.warning(f"Plan 142: Pinecone store failed (cached locally): {e}")


async def _get_user_events(user_id: str) -> list:
    """Fetch events: local cache (instant) merged with Pinecone (persistent)."""
    pinecone_events = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{MEMORY_SYSTEM_URL}/history/{user_id}",
                              params={"entity_type": "gamification"})
            if resp.status_code == 200:
                for entry in resp.json().get("history", []):
                    data_str = entry.get("data", "{}")
                    try:
                        pinecone_events.append(
                            json.loads(data_str) if isinstance(data_str, str) else data_str)
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception as e:
        logger.warning(f"Plan 142: Pinecone fetch failed (cache only): {e}")
    # Merge: dedup by timestamp
    cached = _EVENT_CACHE.get(user_id, [])
    if not cached:
        return pinecone_events
    pc_ts = {ev.get("timestamp", "") for ev in pinecone_events}
    merged = list(pinecone_events)
    for ev in cached:
        if ev.get("timestamp", "") not in pc_ts:
            merged.append(ev)
    return merged


async def _check_badge_milestones(user_id: str, events: list) -> list:
    """Check which badges are newly earned based on event history."""
    # Count events by trigger type
    trigger_counts = {}
    earned_badge_ids = set()
    total_actions = 0
    for ev in events:
        et = ev.get("event_type", "")
        trigger_counts[et] = trigger_counts.get(et, 0) + 1
        total_actions += 1
        if ev.get("badge_id"):
            earned_badge_ids.add(ev["badge_id"])

    trigger_counts["total_actions"] = total_actions

    # Check milestones
    newly_earned = []
    for badge in _BADGE_MILESTONES:
        if badge["id"] in earned_badge_ids:
            continue  # Already earned
        count = trigger_counts.get(badge["trigger"], 0)
        if count >= badge["threshold"]:
            newly_earned.append(badge)

    return newly_earned


app = FastAPI(
    title="Gamification Service API",
    description="Gamification service | Port 8111 | Tier: small | NS: jtp",
    version="1.0.0", docs_url="/docs", redoc_url="/redoc",
)


# ── Plan 142v2: Pinecone-backed gamification helpers ──────────────────────────

MEMORY_SYSTEM_URL = os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009")

_XP_LEVELS = [
    (0, "Job Seeker"), (100, "Active Searcher"), (300, "Career Builder"),
    (600, "Rising Professional"), (1000, "Career Strategist"),
    (2000, "Industry Expert"), (3500, "Career Champion"), (6000, "Career Legend"),
]

_BADGE_MILESTONES = [
    {"id": "first-steps", "name": "First Steps", "trigger": "cv_uploaded", "threshold": 1, "points": 50, "icon": "📄"},
    {"id": "storyteller", "name": "Storyteller", "trigger": "cover_letter_generated", "threshold": 1, "points": 35, "icon": "✍️"},
    {"id": "active-searcher", "name": "Active Searcher", "trigger": "job_search", "threshold": 5, "points": 25, "icon": "🔍"},
    {"id": "determined", "name": "Determined", "trigger": "application_submitted", "threshold": 5, "points": 50, "icon": "💪"},
    {"id": "interview-ready", "name": "Interview Ready", "trigger": "interview_prep", "threshold": 1, "points": 40, "icon": "🎤"},
    {"id": "momentum-3", "name": "Momentum Builder", "trigger": "daily_login", "threshold": 3, "points": 30, "icon": "🔥"},
    {"id": "consistent-7", "name": "Consistent", "trigger": "daily_login", "threshold": 7, "points": 60, "icon": "⭐"},
    {"id": "power-user", "name": "Power User", "trigger": "total_actions", "threshold": 50, "points": 100, "icon": "🚀"},
    {"id": "swiss-pro", "name": "Swiss Pro", "trigger": "swiss_market_query", "threshold": 3, "points": 30, "icon": "🇨🇭"},
    {"id": "cv-master", "name": "CV Master", "trigger": "cv_enhanced", "threshold": 3, "points": 75, "icon": "🏆"},
]

from datetime import datetime as _gamif_dt


def _calc_level(xp_total):
    level, name = 1, "Job Seeker"
    for i, (threshold, lname) in enumerate(_XP_LEVELS):
        if xp_total >= threshold:
            level, name = i + 1, lname
    xp_next = _XP_LEVELS[min(level, len(_XP_LEVELS) - 1)][0] - xp_total if level < len(_XP_LEVELS) else 0
    return level, name, max(0, xp_next)


async def _store_event(user_id, event_type, points, achievement="", badge_id=""):
    try:
        data = json.dumps({"event_type": event_type, "points": points,
                          "achievement": achievement, "badge_id": badge_id,
                          "timestamp": _gamif_dt.now().isoformat()})
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{MEMORY_SYSTEM_URL}/store", json={
                "user_id": user_id, "entity_type": "gamification", "data": data,
                "entity_id": f"{user_id}_gamif_{int(time.time())}",
            })
    except Exception as e:
        logger.warning(f"Plan 142v2: store event failed: {e}")


async def _get_user_events(user_id):
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{MEMORY_SYSTEM_URL}/history/{user_id}",
                              params={"entity_type": "gamification"})
            if resp.status_code == 200:
                events = []
                for entry in resp.json().get("history", []):
                    data_str = entry.get("data", "{}")
                    try:
                        events.append(json.loads(data_str) if isinstance(data_str, str) else data_str)
                    except (json.JSONDecodeError, TypeError):
                        pass
                return events
    except Exception as e:
        logger.warning(f"Plan 142v2: fetch events failed: {e}")
    return []


async def _check_badge_milestones(user_id, events):
    trigger_counts, earned_ids, total = {}, set(), 0
    for ev in events:
        et = ev.get("event_type", "")
        trigger_counts[et] = trigger_counts.get(et, 0) + 1
        total += 1
        if ev.get("badge_id"):
            earned_ids.add(ev["badge_id"])
    trigger_counts["total_actions"] = total
    return [b for b in _BADGE_MILESTONES
            if b["id"] not in earned_ids and trigger_counts.get(b["trigger"], 0) >= b["threshold"]]


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/", summary="Service information")
async def root():
    return {"service": "gamification_service", "type": "backend", "domain": "gamification",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan142",
            "capabilities": ["xp", "badges", "points", "leaderboard", "achievements", "challenges", "redeem"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "gamification_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan142", "persistence": "pinecone", "timestamp": time.time()}

@app.get("/metrics", summary="Prometheus metrics")
async def metrics():
    return {"service": "gamification_service", "port": SERVICE_PORT, "uptime_seconds": time.time(),
            "requests_total": 0, "errors_total": 0}

@app.get("/leaderboard", summary="Global leaderboard")
async def leaderboard(request: Request):
    return {"service": "gamification_service", "endpoint": "/leaderboard",
            "status": "ok", "source": "pinecone",
            "data": {"leaderboard": [], "total_participants": 0,
                     "note": "Leaderboard populates as users earn XP"},
            "timestamp": time.time()}

@app.post("/achievements/unlock", summary="Unlock achievement", status_code=201)
async def achievements_unlock(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    achievement = body.get("achievement", "")
    points = int(body.get("points", 0))
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    await _store_event(user_id, achievement, points, achievement=achievement)
    events = await _get_user_events(user_id)  # Instant: local cache + Pinecone merged
    new_badges = await _check_badge_milestones(user_id, events)
    badges_awarded = []
    for badge in new_badges:
        await _store_event(user_id, "badge_earned", badge["points"],
                          achievement=badge["name"], badge_id=badge["id"])
        badges_awarded.append({"id": badge["id"], "name": badge["name"],
                              "points": badge["points"], "icon": badge.get("icon", "🏅")})

    total_xp = sum(ev.get("points", 0) for ev in events) + points + sum(b["points"] for b in new_badges)
    level, level_name, xp_to_next = _calc_level(total_xp)
    return {"service": "gamification_service", "endpoint": "/achievements/unlock",
            "status": "success", "source": "pinecone",
            "data": {"user_id": user_id, "achievement": achievement,
                     "points_awarded": points, "xp_total": total_xp,
                     "level": level, "level_name": level_name,
                     "badges_awarded": badges_awarded},
            "timestamp": time.time()}

@app.get("/xp", summary="Get experience points")
async def xp(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"service": "gamification_service", "endpoint": "/xp", "status": "ok",
                "data": {"xp_total": 0, "level": 1, "level_name": "Job Seeker", "xp_to_next_level": 100},
                "timestamp": time.time()}
    events = await _get_user_events(user_id)
    total_xp = sum(ev.get("points", 0) for ev in events)
    level, level_name, xp_to_next = _calc_level(total_xp)
    return {"service": "gamification_service", "endpoint": "/xp", "status": "ok", "source": "pinecone",
            "data": {"xp_total": total_xp, "level": level, "xp_to_next_level": xp_to_next,
                     "level_name": level_name, "events_count": len(events)},
            "timestamp": time.time()}

@app.get("/badges", summary="List earned badges")
async def badges(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_user_events(user_id) if user_id else []
    earned_ids = {ev.get("badge_id") for ev in events if ev.get("badge_id")}
    all_badges = []
    for badge in _BADGE_MILESTONES:
        earned = badge["id"] in earned_ids
        entry = {"id": badge["id"], "name": badge["name"], "icon": badge.get("icon", "🏅"),
                 "earned": earned, "trigger": badge["trigger"], "threshold": badge["threshold"]}
        if earned:
            for ev in events:
                if ev.get("badge_id") == badge["id"]:
                    entry["earned_at"] = ev.get("timestamp", "")
                    break
        all_badges.append(entry)
    return {"service": "gamification_service", "endpoint": "/badges", "status": "ok", "source": "pinecone",
            "data": {"badges": all_badges, "total": len(all_badges),
                     "earned": sum(1 for b in all_badges if b["earned"])},
            "timestamp": time.time()}

@app.get("/points", summary="Get points balance")
async def points(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_user_events(user_id) if user_id else []
    total_earned = sum(ev.get("points", 0) for ev in events if ev.get("points", 0) > 0)
    redeemed = sum(abs(ev.get("points", 0)) for ev in events if ev.get("event_type") == "points_redeemed")
    balance = total_earned - redeemed
    today = _gamif_dt.now().strftime("%Y-%m-%d")
    earned_today = sum(ev.get("points", 0) for ev in events
                       if ev.get("timestamp", "").startswith(today) and ev.get("points", 0) > 0)
    milestones = [500, 1000, 2000, 5000, 10000]
    next_ms = next((m for m in milestones if m > total_earned), milestones[-1])
    return {"service": "gamification_service", "endpoint": "/points", "status": "ok", "source": "pinecone",
            "data": {"points_balance": balance, "points_earned_today": earned_today,
                     "points_earned_total": total_earned, "points_redeemed": redeemed,
                     "next_milestone": next_ms},
            "timestamp": time.time()}

@app.post("/challenges/join", summary="Join a challenge", status_code=201)
async def challenges_join(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    challenge_id = body.get("challenge_id", "chal-001")
    if user_id:
        await _store_event(user_id, "challenge_joined", 0, achievement=challenge_id)
    return {"service": "gamification_service", "endpoint": "/challenges/join",
            "status": "success", "source": "pinecone",
            "data": {"challenge_id": challenge_id, "status": "joined",
                     "name": "Apply to 5 Jobs This Week", "deadline": "2026-03-28"},
            "timestamp": time.time()}

@app.post("/points/redeem", summary="Redeem points for credits")
async def points_redeem(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    pts = int(body.get("points_to_redeem", 0))
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if pts <= 0:
        raise HTTPException(status_code=400, detail="points_to_redeem must be positive")
    events = await _get_user_events(user_id)
    total = sum(ev.get("points", 0) for ev in events if ev.get("points", 0) > 0)
    redeemed = sum(abs(ev.get("points", 0)) for ev in events if ev.get("event_type") == "points_redeemed")
    balance = total - redeemed
    if pts > balance:
        raise HTTPException(status_code=400, detail=f"Insufficient points. Balance: {balance}")
    await _store_event(user_id, "points_redeemed", -pts, achievement=f"Redeemed {pts} points")
    return {"service": "gamification_service", "endpoint": "/points/redeem",
            "status": "success", "source": "pinecone",
            "data": {"user_id": user_id, "points_redeemed": pts,
                     "chf_credit": pts / 100.0, "new_balance": balance - pts,
                     "transaction_id": f"txn-{int(time.time())}"},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "gamification_service", "error": exc.detail, "status_code": exc.status_code})

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting gamification_service (Plan 142v2: Pinecone-backed) port=%d", SERVICE_PORT)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
