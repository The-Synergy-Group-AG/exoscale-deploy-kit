#!/usr/bin/env python3
"""
_patch_emotional_wiring.py — Plan 145: Wire emotional_intelligence_system to Pinecone

Tracks emotional state across sessions:
- Per-user emotional state (current emotion, intensity, trend)
- Session history (what emotions were discussed, coping strategies given)
- Emotional progress over time (improving/stable/declining)
"""
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

_ENDPOINTS_CODE = '''

# ── Plan 145: Emotional State Persistence with Pinecone ─────────────────────

import os as _em_os
from datetime import datetime as _em_dt

MEMORY_SYSTEM_URL = _em_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009")

_EMOTIONAL_CACHE: dict = {}

EMOTION_CATEGORIES = ["motivated", "anxious", "discouraged", "confident", "frustrated",
                      "hopeful", "overwhelmed", "resilient", "stressed", "neutral"]


async def _store_emotional_event(user_id, event_type, data_dict):
    try:
        event = {**data_dict, "event_type": event_type, "timestamp": _em_dt.now().isoformat()}
        _EMOTIONAL_CACHE.setdefault(user_id, []).append(event)
        if len(_EMOTIONAL_CACHE.get(user_id, [])) > 100:
            _EMOTIONAL_CACHE[user_id] = _EMOTIONAL_CACHE[user_id][-100:]
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{MEMORY_SYSTEM_URL}/store", json={
                "user_id": user_id, "entity_type": "emotional_state",
                "data": json.dumps(event),
                "entity_id": f"{user_id}_emotion_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 145: emotional store failed: {e}")


async def _get_emotional_history(user_id):
    cached = _EMOTIONAL_CACHE.get(user_id, [])
    pinecone_events = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{MEMORY_SYSTEM_URL}/history/{user_id}", params={"entity_type": "emotional_state"})
            if resp.status_code == 200:
                for entry in resp.json().get("history", []):
                    try:
                        pinecone_events.append(json.loads(entry.get("data", "{}")) if isinstance(entry.get("data"), str) else entry.get("data", {}))
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception:
        pass
    pc_ts = {ev.get("timestamp", "") for ev in pinecone_events}
    return pinecone_events + [ev for ev in cached if ev.get("timestamp", "") not in pc_ts]


def _analyze_trend(events):
    if len(events) < 2:
        return "insufficient_data"
    positive = ["motivated", "confident", "hopeful", "resilient"]
    recent = events[-5:]
    pos_count = sum(1 for e in recent if e.get("emotion", "") in positive)
    if pos_count >= 3:
        return "improving"
    elif pos_count >= 2:
        return "stable"
    return "needs_support"


@app.get("/", summary="Service information")
async def root():
    return {"service": "emotional_intelligence_system", "type": "backend", "domain": "wellness",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan145",
            "capabilities": ["state_tracking", "trend_analysis", "session_history", "coping_strategies"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "emotional_intelligence_system", "port": SERVICE_PORT,
            "version": "2.0.0-plan145", "persistence": "pinecone", "timestamp": time.time()}

@app.get("/metrics", summary="Prometheus metrics")
async def metrics():
    return {"service": "emotional_intelligence_system", "port": SERVICE_PORT, "uptime_seconds": time.time()}

@app.post("/state/record", summary="Record emotional state")
async def record_state(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    emotion = body.get("emotion", "neutral")
    intensity = float(body.get("intensity", 0.5))
    context = body.get("context", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    await _store_emotional_event(user_id, "state_recorded", {
        "emotion": emotion, "intensity": min(1.0, max(0.0, intensity)), "context": context[:200]})
    return {"service": "emotional_intelligence_system", "endpoint": "/state/record",
            "status": "success", "source": "pinecone",
            "data": {"emotion": emotion, "intensity": intensity, "recorded": True},
            "timestamp": time.time()}

@app.get("/state/current", summary="Get current emotional state")
async def current_state(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_emotional_history(user_id) if user_id else []
    if events:
        latest = events[-1]
        trend = _analyze_trend(events)
        return {"service": "emotional_intelligence_system", "endpoint": "/state/current",
                "status": "ok", "source": "pinecone",
                "data": {"current_emotion": latest.get("emotion", "neutral"),
                         "intensity": latest.get("intensity", 0.5),
                         "trend": trend, "sessions": len(events),
                         "last_updated": latest.get("timestamp", "")},
                "timestamp": time.time()}
    return {"service": "emotional_intelligence_system", "endpoint": "/state/current",
            "status": "ok", "data": {"current_emotion": "neutral", "trend": "new_user", "sessions": 0},
            "timestamp": time.time()}

@app.get("/history", summary="Emotional history")
async def emotional_history(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_emotional_history(user_id) if user_id else []
    trend = _analyze_trend(events) if events else "no_data"
    return {"service": "emotional_intelligence_system", "endpoint": "/history",
            "status": "ok", "source": "pinecone",
            "data": {"trend": trend, "total_sessions": len(events),
                     "recent": events[-10:], "available_emotions": EMOTION_CATEGORIES},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "emotional_intelligence_system", "error": exc.detail})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
'''


def patch_service(service_dir: Path) -> bool:
    for candidate in [service_dir / "src" / "main.py", service_dir / "main.py"]:
        if candidate.exists():
            main_py = candidate
            break
    else:
        return False
    content = main_py.read_text()
    if "Plan 145" in content and "_store_emotional_event" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "emotional_intelligence_system"
    if svc.exists():
        patch_service(svc)
