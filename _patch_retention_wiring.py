#!/usr/bin/env python3
"""
_patch_retention_wiring.py -- Plan 148: Winback & Retention Campaigns

Retention tiers:
- 7-day inactive: 100 bonus credits
- 14-day inactive: 250 credits + 50% off next month
- 30-day inactive: 500 credits + AI-generated personalized video
- Subscription pause: up to 3 months (handled by subscription service)

Wires into notification_service for delivery.
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _ret_os
from datetime import datetime as _ret_dt, timezone as _ret_tz, timedelta as _ret_td

PERSISTENCE_SERVICE_URL = _ret_os.getenv("PERSISTENCE_SERVICE_URL",
    _ret_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
CREDIT_SYSTEM_URL = _ret_os.getenv("CREDIT_SYSTEM_URL", "http://credit-system-service:8000")
EMAIL_SERVICE_URL = _ret_os.getenv("EMAIL_SERVICE_URL", "http://email-integration-service:8000")
PERSISTENCE_PROVIDER = _ret_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

# Winback campaign tiers
WINBACK_TIERS = [
    {"days_inactive": 7, "credits": 100, "discount_pct": 0,
     "message": "We miss you! Here are 100 bonus credits to get back on track.",
     "campaign": "7_day_nudge"},
    {"days_inactive": 14, "credits": 250, "discount_pct": 50,
     "message": "Welcome back! 250 credits + 50% off Premium this month.",
     "campaign": "14_day_winback"},
    {"days_inactive": 30, "credits": 500, "discount_pct": 0,
     "message": "We've prepared a personalized career update for you. 500 credits to explore!",
     "campaign": "30_day_reactivation", "ai_video": True},
]

# Track last activity and campaigns sent
_ACTIVITY_CACHE: dict = {}  # {user_id: {"last_active": iso, "campaigns_sent": [...]}}


async def _store_retention_event(user_id, event_type, data_dict):
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": "retention",
                "data": json.dumps({**data_dict, "event_type": event_type,
                                    "timestamp": _ret_dt.now(_ret_tz.utc).isoformat()}),
                "entity_id": f"{user_id}_ret_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 148 retention: store failed: {e}")


async def _award_winback_credits(user_id, credits, reason):
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{CREDIT_SYSTEM_URL}/earn", json={
                "user_id": user_id, "credits": credits, "reason": reason})
    except Exception:
        pass


def _get_activity(user_id):
    if user_id not in _ACTIVITY_CACHE:
        _ACTIVITY_CACHE[user_id] = {
            "last_active": _ret_dt.now(_ret_tz.utc).isoformat(),
            "campaigns_sent": []}
    return _ACTIVITY_CACHE[user_id]


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/", summary="Service information")
async def root():
    return {"service": "retention_service", "type": "backend", "domain": "engagement",
            "status": "running", "port": SERVICE_PORT, "version": "1.0.0-plan148",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["activity_tracking", "winback_campaigns", "reactivation"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "retention_service", "port": SERVICE_PORT,
            "version": "1.0.0-plan148", "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "retention_service", "port": SERVICE_PORT,
            "uptime_seconds": time.time()}

@app.post("/activity/ping", summary="Record user activity")
async def activity_ping(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    activity = _get_activity(user_id)
    activity["last_active"] = _ret_dt.now(_ret_tz.utc).isoformat()
    return {"status": "ok", "user_id": user_id}

@app.get("/activity/status", summary="Get user activity status")
async def activity_status(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"data": {"status": "unknown"}}

    activity = _get_activity(user_id)
    last_active = _ret_dt.fromisoformat(activity["last_active"].replace("Z", "+00:00"))
    now = _ret_dt.now(_ret_tz.utc)
    days_inactive = (now - last_active).days

    status = "active" if days_inactive < 3 else "inactive"
    eligible_campaigns = [t for t in WINBACK_TIERS
                          if days_inactive >= t["days_inactive"]
                          and t["campaign"] not in activity.get("campaigns_sent", [])]

    return {"service": "retention_service", "endpoint": "/activity/status",
            "data": {"user_id": user_id, "last_active": activity["last_active"],
                     "days_inactive": days_inactive, "status": status,
                     "eligible_campaigns": len(eligible_campaigns)},
            "timestamp": time.time()}

@app.post("/winback/trigger", summary="Trigger winback campaign for user")
async def winback_trigger(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    activity = _get_activity(user_id)
    last_active = _ret_dt.fromisoformat(activity["last_active"].replace("Z", "+00:00"))
    days_inactive = (_ret_dt.now(_ret_tz.utc) - last_active).days

    campaigns_triggered = []
    for tier in WINBACK_TIERS:
        if (days_inactive >= tier["days_inactive"]
                and tier["campaign"] not in activity.get("campaigns_sent", [])):
            # Award credits
            await _award_winback_credits(user_id, tier["credits"],
                                          f"winback_{tier['campaign']}")
            # Record campaign
            activity.setdefault("campaigns_sent", []).append(tier["campaign"])
            await _store_retention_event(user_id, "winback_sent", {
                "campaign": tier["campaign"], "credits": tier["credits"],
                "discount_pct": tier["discount_pct"],
                "days_inactive": days_inactive})

            campaigns_triggered.append({
                "campaign": tier["campaign"], "credits_awarded": tier["credits"],
                "discount_pct": tier["discount_pct"],
                "message": tier["message"],
                "ai_video": tier.get("ai_video", False)})

    if not campaigns_triggered:
        return {"service": "retention_service", "endpoint": "/winback/trigger",
                "status": "no_eligible_campaigns",
                "data": {"days_inactive": days_inactive,
                         "message": "No new campaigns to trigger"},
                "timestamp": time.time()}

    return {"service": "retention_service", "endpoint": "/winback/trigger",
            "status": "success",
            "data": {"campaigns_triggered": campaigns_triggered,
                     "total_credits_awarded": sum(c["credits_awarded"] for c in campaigns_triggered),
                     "days_inactive": days_inactive},
            "timestamp": time.time()}

@app.get("/winback/tiers", summary="Winback campaign tiers")
async def winback_tiers(request: Request):
    return {"service": "retention_service", "endpoint": "/winback/tiers",
            "data": {"tiers": WINBACK_TIERS},
            "timestamp": time.time()}

@app.post("/winback/check-all", summary="Check all users for winback eligibility")
async def winback_check_all(request: Request):
    """Batch check — would be called by a cron job."""
    triggered = 0
    for uid, activity in list(_ACTIVITY_CACHE.items()):
        last_active = _ret_dt.fromisoformat(activity["last_active"].replace("Z", "+00:00"))
        days = (_ret_dt.now(_ret_tz.utc) - last_active).days
        if days >= 7:
            for tier in WINBACK_TIERS:
                if (days >= tier["days_inactive"]
                        and tier["campaign"] not in activity.get("campaigns_sent", [])):
                    await _award_winback_credits(uid, tier["credits"],
                                                  f"winback_{tier['campaign']}")
                    activity.setdefault("campaigns_sent", []).append(tier["campaign"])
                    triggered += 1
    return {"status": "ok", "campaigns_triggered": triggered}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "retention_service", "error": exc.detail})

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
    if "Plan 148" in content and "winback" in content:
        print(f"  SKIP: {main_py} already patched")
        return False
    app_match = re.search(r"app = FastAPI\([^)]+\)", content, re.DOTALL)
    if not app_match:
        return False
    main_py.write_text(content[:app_match.end()] + "\n" + _ENDPOINTS_CODE)
    print(f"  PATCHED: {main_py}")
    return True


if __name__ == "__main__":
    # Wire into notification_service since there's no dedicated retention service
    gen = (Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / "CURRENT").read_text().strip()
    # Try real-time-data-refresher as it handles periodic tasks
    for svc_name in ["retention_winback_service", "notification_service"]:
        svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / svc_name
        if svc.exists():
            patch_service(svc)
            break
