#!/usr/bin/env python3
"""
_patch_affiliate_wiring.py -- Plan 148: Dynamic Referral System

Replaces code-based referral (JTP-{id}-{hash}) with:
- "Who referred you?" text field (no codes needed)
- AI matching by name/email
- Pre-registration for expected referrals
- Instant notifications on referral events
- Referral credits (not XP): signup +100, upgrade +500, interview +200, job +1000
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _af_os
from datetime import datetime as _af_dt, timezone as _af_tz

PERSISTENCE_SERVICE_URL = _af_os.getenv("PERSISTENCE_SERVICE_URL",
    _af_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _af_os.getenv("PERSISTENCE_PROVIDER", "pinecone")
CREDIT_SYSTEM_URL = _af_os.getenv("CREDIT_SYSTEM_URL", "http://credit-system-service:8000")
NOTIFICATION_URL = _af_os.getenv("NOTIFICATION_URL", "http://notification-service:8000")

# Referral credit rewards (Plan 148: credits, not XP)
REFERRAL_REWARDS = {
    "signup": {"credits": 100, "label": "Friend signed up"},
    "upgrade": {"credits": 500, "label": "Friend upgraded to Premium"},
    "interview": {"credits": 200, "label": "Friend got an interview"},
    "job_found": {"credits": 1000, "label": "Friend found a job"},
}

# Anti-fraud
MAX_REFERRALS_PER_USER = 50

# Local caches
_REFERRAL_REGISTRY: dict = {}  # {user_id: {"name": str, "email": str, "referrals": [...]}}
_PRE_REGISTRATIONS: dict = {}  # {"name_or_email_lower": referrer_user_id}
_REFERRAL_LINKS: dict = {}  # {referee_user_id: referrer_user_id}  (confirmed matches)


def _normalize(text):
    return text.strip().lower()


def _ai_match_referrer(who_referred_text):
    """AI-match 'who referred you' text against registered users.
    Matches by: exact email, name substring, or fuzzy name match."""
    text = _normalize(who_referred_text)
    if not text:
        return None

    # 1. Check pre-registrations first (exact match)
    if text in _PRE_REGISTRATIONS:
        return _PRE_REGISTRATIONS[text]

    # 2. Check registered users by email or name
    for uid, info in _REFERRAL_REGISTRY.items():
        if _normalize(info.get("email", "")) == text:
            return uid
        if _normalize(info.get("name", "")) == text:
            return uid
        # Partial name match (first name or last name)
        name_parts = _normalize(info.get("name", "")).split()
        if any(part == text for part in name_parts):
            return uid
        # Contains match for emails
        if "@" in text and text in _normalize(info.get("email", "")):
            return uid

    return None


async def _award_referral_credits(user_id, credits, reason):
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{CREDIT_SYSTEM_URL}/earn", json={
                "user_id": user_id, "credits": credits, "reason": reason})
    except Exception:
        pass


async def _store_referral_event(user_id, event_type, data_dict):
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": "referral",
                "data": json.dumps({**data_dict, "event_type": event_type,
                                    "timestamp": _af_dt.now(_af_tz.utc).isoformat()}),
                "entity_id": f"{user_id}_ref_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 148 referral: store failed: {e}")


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/", summary="Service information")
async def root():
    return {"service": "affiliate_manager_service", "type": "backend", "domain": "workflow",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan148",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["dynamic_referral", "ai_matching", "pre_registration",
                             "referral_credits", "referral_stats"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "affiliate_manager_service",
            "port": SERVICE_PORT, "version": "2.0.0-plan148",
            "persistence": PERSISTENCE_PROVIDER, "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "affiliate_manager_service", "port": SERVICE_PORT,
            "uptime_seconds": time.time()}

@app.post("/referral/register", summary="Register as a referrer")
async def referral_register(request: Request):
    """Register user so others can find them via 'who referred you'."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    name = body.get("name", "")
    email = body.get("email", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    _REFERRAL_REGISTRY[user_id] = {"name": name, "email": email, "referrals": []}
    # Index for matching
    if name:
        _PRE_REGISTRATIONS[_normalize(name)] = user_id
    if email:
        _PRE_REGISTRATIONS[_normalize(email)] = user_id

    await _store_referral_event(user_id, "referrer_registered", {
        "name": name, "email": email})

    return {"service": "affiliate_manager_service", "endpoint": "/referral/register",
            "status": "success",
            "data": {"user_id": user_id, "registered": True,
                     "message": "You're registered! Friends can now mention your name or email when signing up."},
            "timestamp": time.time()}

@app.post("/referral/pre-register", summary="Pre-register an expected referral")
async def referral_pre_register(request: Request):
    """Referrer pre-registers someone they're about to refer."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    friend_name = body.get("friend_name", "")
    friend_email = body.get("friend_email", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if not friend_name and not friend_email:
        raise HTTPException(status_code=400, detail="friend_name or friend_email required")

    if friend_name:
        _PRE_REGISTRATIONS[_normalize(friend_name)] = user_id
    if friend_email:
        _PRE_REGISTRATIONS[_normalize(friend_email)] = user_id

    await _store_referral_event(user_id, "pre_registration", {
        "friend_name": friend_name, "friend_email": friend_email})

    return {"service": "affiliate_manager_service", "endpoint": "/referral/pre-register",
            "status": "success",
            "data": {"message": f"Pre-registered. When {friend_name or friend_email} signs up "
                                f"and mentions you, you'll get {REFERRAL_REWARDS['signup']['credits']} credits!"},
            "timestamp": time.time()}

@app.post("/referral/match", summary="Match 'who referred you' text")
async def referral_match(request: Request):
    """Called during signup: match user's answer to 'Who referred you?'."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    referee_user_id = body.get("user_id", "")
    who_referred = body.get("who_referred", "")
    if not referee_user_id or not who_referred:
        raise HTTPException(status_code=400, detail="user_id and who_referred required")

    referrer_id = _ai_match_referrer(who_referred)
    if not referrer_id:
        return {"service": "affiliate_manager_service", "endpoint": "/referral/match",
                "status": "no_match",
                "data": {"message": "We couldn't find that person. No worries — they can still register and the referral will be credited retroactively."},
                "timestamp": time.time()}

    # Anti-fraud check
    referrals = _REFERRAL_REGISTRY.get(referrer_id, {}).get("referrals", [])
    if len(referrals) >= MAX_REFERRALS_PER_USER:
        return {"status": "fraud_limit", "data": {"message": "Referrer has reached maximum referrals"}}

    # Record the link
    _REFERRAL_LINKS[referee_user_id] = referrer_id
    if referrer_id in _REFERRAL_REGISTRY:
        _REFERRAL_REGISTRY[referrer_id].setdefault("referrals", []).append(referee_user_id)

    # Award signup credits to referrer
    await _award_referral_credits(referrer_id, REFERRAL_REWARDS["signup"]["credits"],
                                   f"referral_signup_{referee_user_id}")
    await _store_referral_event(referrer_id, "referral_signup", {
        "referee_id": referee_user_id, "matched_text": who_referred,
        "credits": REFERRAL_REWARDS["signup"]["credits"]})

    return {"service": "affiliate_manager_service", "endpoint": "/referral/match",
            "status": "matched",
            "data": {"referrer_id": referrer_id,
                     "message": f"Matched! Your referrer gets {REFERRAL_REWARDS['signup']['credits']} credits.",
                     "credits_awarded_to_referrer": REFERRAL_REWARDS["signup"]["credits"]},
            "timestamp": time.time()}

@app.post("/referral/event", summary="Track referral milestone event")
async def referral_event(request: Request):
    """Track milestones: upgrade, interview, job_found."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    referee_user_id = body.get("user_id", "")
    event_type = body.get("event", "")  # upgrade, interview, job_found
    if not referee_user_id or event_type not in REFERRAL_REWARDS:
        raise HTTPException(status_code=400, detail=f"user_id and event required. Valid events: {list(REFERRAL_REWARDS.keys())}")

    referrer_id = _REFERRAL_LINKS.get(referee_user_id)
    if not referrer_id:
        return {"status": "no_referrer", "data": {"message": "This user has no linked referrer"}}

    reward = REFERRAL_REWARDS[event_type]
    await _award_referral_credits(referrer_id, reward["credits"],
                                   f"referral_{event_type}_{referee_user_id}")
    await _store_referral_event(referrer_id, f"referral_{event_type}", {
        "referee_id": referee_user_id, "credits": reward["credits"]})

    return {"service": "affiliate_manager_service", "endpoint": "/referral/event",
            "status": "success",
            "data": {"event": event_type, "referrer_id": referrer_id,
                     "credits_awarded": reward["credits"], "label": reward["label"]},
            "timestamp": time.time()}

@app.get("/referral/stats", summary="Get referral statistics")
async def referral_stats(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"data": {"total_referrals": 0, "credits_earned": 0}}

    info = _REFERRAL_REGISTRY.get(user_id, {"referrals": []})
    referrals = info.get("referrals", [])

    # Fetch referral events from persistence
    total_credits = 0
    events = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": "referral"})
            if resp.status_code == 200:
                for entry in resp.json().get("history", []):
                    try:
                        d = json.loads(entry.get("data", "{}")) if isinstance(entry.get("data"), str) else entry.get("data", {})
                        if d.get("credits"):
                            total_credits += d["credits"]
                        events.append(d)
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception:
        pass

    return {"service": "affiliate_manager_service", "endpoint": "/referral/stats",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"total_referrals": len(referrals),
                     "credits_earned": total_credits,
                     "referral_events": events[-20:],
                     "max_referrals": MAX_REFERRALS_PER_USER,
                     "rewards": REFERRAL_REWARDS},
            "timestamp": time.time()}

@app.get("/referral/rewards", summary="Referral reward tiers")
async def referral_rewards(request: Request):
    return {"service": "affiliate_manager_service", "endpoint": "/referral/rewards",
            "data": {"rewards": REFERRAL_REWARDS, "max_referrals": MAX_REFERRALS_PER_USER,
                     "note": "No referral codes needed — just tell your friend to mention your name or email when signing up!"},
            "timestamp": time.time()}

# Legacy: still support code-based lookup for backward compatibility
@app.get("/referral/code", summary="Get referral info (legacy compat)")
async def referral_code(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"data": {"message": "No codes needed! Just tell friends to mention your name."}}
    info = _REFERRAL_REGISTRY.get(user_id, {})
    return {"service": "affiliate_manager_service", "endpoint": "/referral/code",
            "data": {"method": "dynamic_referral",
                     "name": info.get("name", ""),
                     "email": info.get("email", ""),
                     "message": "No referral codes needed! Your friends just mention your name or email when signing up."},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "affiliate_manager_service", "error": exc.detail})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
'''


def patch_service(service_dir):
    for candidate in [service_dir / "src" / "main.py", service_dir / "main.py"]:
        if candidate.exists():
            main_py = candidate
            break
    else:
        return False
    content = main_py.read_text()
    if "Plan 148" in content and "_ai_match_referrer" in content:
        print(f"  SKIP: {main_py} already patched")
        return False
    app_match = re.search(r"app = FastAPI\([^)]+\)", content, re.DOTALL)
    if not app_match:
        return False
    main_py.write_text(content[:app_match.end()] + "\n" + _ENDPOINTS_CODE)
    print(f"  PATCHED: {main_py}")
    return True


if __name__ == "__main__":
    gen = (Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / "CURRENT").read_text().strip()
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "affiliate_manager_service"
    if svc.exists():
        patch_service(svc)
