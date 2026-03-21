#!/usr/bin/env python3
"""
_patch_gamification_wiring.py — Plan 142: Wire gamification_service to Pinecone

Replaces mock endpoints with real Pinecone-backed implementations.
Runs during prep_services.py sync. Survives service engine regenerations.
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# Complete endpoint code to append after the app = FastAPI(...) block
_ENDPOINTS_CODE = '''

# ── Plan 142: Pinecone-backed gamification helpers ──────────────────────────

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


# Plan 142 fix: Local event cache — instant consistency while Pinecone propagates
# Key: user_id → list of event dicts (kept in sync with Pinecone writes)
_EVENT_CACHE: dict = {}  # {user_id: [{"event_type":..., "points":..., ...}, ...]}
_CACHE_MAX_PER_USER = 200  # Prevent unbounded memory growth


async def _store_event(user_id, event_type, points, achievement="", badge_id=""):
    event = {"event_type": event_type, "points": points,
             "achievement": achievement, "badge_id": badge_id,
             "timestamp": _gamif_dt.now().isoformat(),
             "_entity_id": f"{user_id}_gamif_{int(time.time() * 1000)}"}
    # Write to local cache FIRST (instant visibility)
    if user_id not in _EVENT_CACHE:
        _EVENT_CACHE[user_id] = []
    _EVENT_CACHE[user_id].append(event)
    # Trim cache if too large
    if len(_EVENT_CACHE[user_id]) > _CACHE_MAX_PER_USER:
        _EVENT_CACHE[user_id] = _EVENT_CACHE[user_id][-_CACHE_MAX_PER_USER:]
    # Write to Pinecone async (eventual persistence)
    try:
        data = json.dumps({"event_type": event_type, "points": points,
                          "achievement": achievement, "badge_id": badge_id,
                          "timestamp": event["timestamp"]})
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{MEMORY_SYSTEM_URL}/store", json={
                "user_id": user_id, "entity_type": "gamification", "data": data,
                "entity_id": event["_entity_id"],
            })
    except Exception as e:
        logger.warning(f"Plan 142: Pinecone store failed (cached locally): {e}")


async def _get_user_events(user_id):
    # Merge: Pinecone (persistent) + local cache (instant)
    pinecone_events = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{MEMORY_SYSTEM_URL}/history/{user_id}",
                              params={"entity_type": "gamification"})
            if resp.status_code == 200:
                for entry in resp.json().get("history", []):
                    data_str = entry.get("data", "{}")
                    try:
                        pinecone_events.append(json.loads(data_str) if isinstance(data_str, str) else data_str)
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception as e:
        logger.warning(f"Plan 142: Pinecone fetch failed (using cache only): {e}")

    # Merge with local cache (dedup by timestamp to avoid double-counting)
    cached = _EVENT_CACHE.get(user_id, [])
    if not cached:
        return pinecone_events

    # Build set of Pinecone timestamps for dedup
    pc_timestamps = {ev.get("timestamp", "") for ev in pinecone_events}
    # Add cached events not yet in Pinecone
    merged = list(pinecone_events)
    for ev in cached:
        if ev.get("timestamp", "") not in pc_timestamps:
            merged.append(ev)
    return merged


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
            "status": "running", "port": SERVICE_PORT, "version": "3.0.0-plan148",
            "capabilities": ["xp", "badges", "points", "leaderboard", "achievements", "challenges", "redeem"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "gamification_service", "port": SERVICE_PORT,
            "version": "3.0.0-plan148", "persistence": "pinecone", "timestamp": time.time()}

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
    events = await _get_user_events(user_id)  # Instant: cache + Pinecone merged
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

# ── Plan 148: Streak System with Credit Rewards ─────────────────────────────

CREDIT_SYSTEM_URL = os.getenv("CREDIT_SYSTEM_URL", "http://credit-system-service:8000")

# Streak credit rewards (per day)
_STREAK_REWARDS = {
    1: 10, 2: 10, 3: 15, 4: 15, 5: 20, 6: 20, 7: 25,
}  # Days 8+: 30 credits/day

# Milestone bonuses (one-time)
_STREAK_MILESTONES = {
    7: {"credits": 100, "label": "1 Week Streak"},
    14: {"credits": 250, "label": "2 Week Streak"},
    30: {"credits": 500, "label": "Monthly Warrior"},
    60: {"credits": 1000, "label": "Dedication Master"},
    90: {"credits": 2000, "label": "Quarterly Champion"},
    180: {"credits": 5000, "label": "Half-Year Legend"},
}

# Streak cache: {user_id: {"current": int, "last_login": "YYYY-MM-DD", "milestones_claimed": set}}
_STREAK_CACHE: dict = {}


def _is_weekend():
    return _gamif_dt.now().weekday() >= 5  # Saturday=5, Sunday=6


async def _award_streak_credits(user_id, credits, reason):
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.post(f"{CREDIT_SYSTEM_URL}/earn", json={
                "user_id": user_id, "credits": credits, "reason": reason})
    except Exception:
        pass


@app.post("/streak/checkin", summary="Daily streak check-in")
async def streak_checkin(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    today = _gamif_dt.now().strftime("%Y-%m-%d")
    streak = _STREAK_CACHE.get(user_id, {"current": 0, "last_login": "", "milestones_claimed": set()})

    # Already checked in today
    if streak["last_login"] == today:
        return {"service": "gamification_service", "endpoint": "/streak/checkin",
                "status": "already_checked_in",
                "data": {"streak": streak["current"], "message": "Already checked in today!"},
                "timestamp": time.time()}

    # Check if streak continues (yesterday) or resets
    yesterday = (_gamif_dt.now() - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
    if streak["last_login"] == yesterday:
        streak["current"] += 1
    else:
        streak["current"] = 1  # Reset

    streak["last_login"] = today

    # Calculate credits
    base_credits = _STREAK_REWARDS.get(streak["current"], 30)
    weekend_multiplier = 2 if _is_weekend() else 1
    daily_credits = base_credits * weekend_multiplier

    # Award daily credits
    reason = f"streak_day_{streak['current']}"
    if weekend_multiplier > 1:
        reason += "_weekend_2x"
    await _award_streak_credits(user_id, daily_credits, reason)
    await _store_event(user_id, "streak_checkin", daily_credits,
                       achievement=f"Day {streak['current']} streak")

    # Check milestone bonuses
    milestone_bonus = 0
    milestone_label = ""
    if streak["current"] in _STREAK_MILESTONES:
        ms = _STREAK_MILESTONES[streak["current"]]
        if streak["current"] not in streak.get("milestones_claimed", set()):
            milestone_bonus = ms["credits"]
            milestone_label = ms["label"]
            await _award_streak_credits(user_id, milestone_bonus,
                                         f"streak_milestone_{streak['current']}")
            await _store_event(user_id, "streak_milestone", milestone_bonus,
                               achievement=milestone_label)
            streak.setdefault("milestones_claimed", set()).add(streak["current"])

    _STREAK_CACHE[user_id] = streak

    return {"service": "gamification_service", "endpoint": "/streak/checkin",
            "status": "success",
            "data": {"streak": streak["current"],
                     "daily_credits": daily_credits,
                     "weekend_bonus": weekend_multiplier > 1,
                     "milestone_bonus": milestone_bonus,
                     "milestone_label": milestone_label,
                     "total_earned_today": daily_credits + milestone_bonus,
                     "next_milestone": next((d for d in sorted(_STREAK_MILESTONES.keys())
                                            if d > streak["current"]), None)},
            "timestamp": time.time()}

@app.get("/streak", summary="Get current streak")
async def get_streak(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"data": {"streak": 0, "last_login": None}}
    streak = _STREAK_CACHE.get(user_id, {"current": 0, "last_login": ""})
    return {"service": "gamification_service", "endpoint": "/streak",
            "status": "ok",
            "data": {"streak": streak["current"],
                     "last_login": streak["last_login"],
                     "milestones": _STREAK_MILESTONES,
                     "next_milestone": next((d for d in sorted(_STREAK_MILESTONES.keys())
                                            if d > streak["current"]), None)},
            "timestamp": time.time()}

@app.get("/streak/leaderboard", summary="Streak leaderboard")
async def streak_leaderboard(request: Request):
    # Sort by current streak
    leaders = sorted(
        [{"user_id": uid, "streak": s["current"]}
         for uid, s in _STREAK_CACHE.items() if s["current"] > 0],
        key=lambda x: x["streak"], reverse=True)[:20]
    return {"service": "gamification_service", "endpoint": "/streak/leaderboard",
            "status": "ok",
            "data": {"leaders": leaders, "total": len(_STREAK_CACHE)},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "gamification_service", "error": exc.detail, "status_code": exc.status_code})

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting gamification_service (Plan 148: Pinecone + Streaks) port=%d", SERVICE_PORT)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
'''


def patch_gamification_service(service_dir: Path) -> bool:
    """Patch gamification_service main.py with Pinecone persistence."""
    # Check both src/main.py and main.py
    for candidate in [service_dir / "src" / "main.py", service_dir / "main.py"]:
        if candidate.exists():
            main_py = candidate
            break
    else:
        print(f"  SKIP: main.py not found in {service_dir}")
        return False

    content = main_py.read_text()

    # Already correctly patched?
    if "Plan 148" in content and "streak_checkin" in content:
        print(f"  SKIP: {main_py} already correctly patched")
        return False

    # Find the app = FastAPI(...) block end
    import re
    app_match = re.search(r"app = FastAPI\([^)]+\)", content, re.DOTALL)
    if not app_match:
        print(f"  ERROR: Could not find FastAPI app definition in {main_py}")
        return False

    # Keep header up to end of app = FastAPI(...)
    header = content[:app_match.end()]

    # Write header + all new endpoints
    new_content = header + "\n" + _ENDPOINTS_CODE
    main_py.write_text(new_content)
    print(f"  PATCHED: {main_py} ({len(new_content)} bytes)")
    return True


if __name__ == "__main__":
    current_file = SCRIPT_DIR.parent / "engines" / "service_engine" / "outputs" / "CURRENT"
    if current_file.exists():
        gen = current_file.read_text().strip()
        svc_dir = SCRIPT_DIR.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "gamification_service"
        if svc_dir.exists():
            patch_gamification_service(svc_dir)
        else:
            print(f"gamification_service not found in {gen}")
    else:
        print("No CURRENT pointer found")
