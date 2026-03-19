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

app = FastAPI(
    title="Gamification Service API",
    description="Gamification service | Port 8111 | Tier: small | NS: jtp",
    version="1.0.0", docs_url="/docs", redoc_url="/redoc",
)


@app.get("/", summary="Service information")
async def root():
    return {
        "service": "gamification_service", "type": "backend",
        "domain": "gamification", "status": "running", "endpoint": "/",
        "template": config.get("generated_from_template", "unknown"),
        "port": SERVICE_PORT, "resource_tier": RESOURCE_TIER,
        "kubernetes_namespace": KUBERNETES_NS,
        "biological_harmony": config.get("biological_harmony", 0.997),
        "consciousness_level": config.get("consciousness_level", "GODHOOD"),
        "biological_system": config.get("biological_system", "General"),
        "endpoints": config.get("endpoints", []),
        "registry_sources": config.get("registry_sources", {}),
        "variables_loaded": list(config.get("variables", {}).keys()),
        "version": config.get("version", "1.0.0"),
    }


@app.get("/health", summary="Health check")
async def health():
    # L69c: Try live biological harmony from bridge
    _bio_harmony = 0.9926
    try:
        async with httpx.AsyncClient(timeout=2.0) as _bc:
            _br = await _bc.get(f"{BIO_BRIDGE}/harmony")
            if _br.status_code == 200:
                _bio_harmony = _br.json().get("harmony", _bio_harmony)
    except Exception:
        pass  # Fallback to static harmony
    return {
        "status": "healthy", "service": "gamification_service",
        "port": SERVICE_PORT, "resource_tier": RESOURCE_TIER,
        "kubernetes_namespace": KUBERNETES_NS,
        "timestamp": time.time(),
        "biological_harmony": _bio_harmony,
        "harmony_threshold": HARMONY_THRESHOLD,
    }


@app.get("/metrics", summary="Prometheus metrics")
async def metrics():
    return {
        "service": "gamification_service", "port": SERVICE_PORT,
        "resource_tier": RESOURCE_TIER,
        "uptime_seconds": time.time(), "requests_total": 0, "errors_total": 0,
        "biological_harmony_gauge": 0.9926,
        "api_timeout_seconds": API_TIMEOUT,
        "rate_limit_rpm": RATE_LIMIT_RPM,
    }


@app.get("/leaderboard", summary="Global leaderboard")
async def leaderboard(request: Request):
    """Global leaderboard"""
    q = dict(request.query_params)
    # L69: AI-First — try backend for intelligent response
    _search = q.get('q', '') if q else ''
    if _search:
        try:
            async with httpx.AsyncClient(timeout=8.0) as _aic:
                _air = await _aic.post(
                    f"{AI_BACKEND}/analyze",
                    json={"user_id": "anon", "data": _search,
                           "context": ["gamification", "/leaderboard"]},
                )
                if _air.status_code == 200:
                    _aid = _air.json()
                    return {"service": "gamification_service",
                            "domain": "gamification",
                            "endpoint": "/leaderboard",
                            "method": "GET", "status": "ok", "source": "ai",
                            "data": {"analysis": _aid.get("analysis", ""),
                                     "insights": _aid.get("insights", []),
                                     "recommendations": _aid.get("recommendations", []),
                                     "query": _search},
                            "biological_harmony": config.get("biological_harmony", 0.9926),
                            "timestamp": time.time()}
        except Exception as _exc:
            logger.warning('L69: AI backend unavailable: %s', _exc)
    _pool = {'leaderboard': [{'rank': 1, 'user_id': 'user-042', 'username': 'topuser', 'points': 9850}, {'rank': 2, 'user_id': 'user-007', 'username': 'runner_up', 'points': 9200}], 'total_participants': 1247}
    if q:
        _words = set(w for v in q.values() for w in v.lower().split() if len(w) > 2)
        _stop = {'the','and','for','job','jobs','show','find','get','all','has','are','was'}
        _words -= _stop
        if _words:
            for _k, _items in list(_pool.items()):
                if isinstance(_items, list) and _items and isinstance(_items[0], dict):
                    _items = [i for i in _items if any(w in json.dumps(i, default=str).lower() for w in _words)]
                    _pool[_k] = _items
                    if 'total' in _pool: _pool['total'] = len(_items)
        _pool['query'] = q
    return {"service": "gamification_service", "domain": "gamification",
            "endpoint": "/leaderboard", "method": "GET",
            "status": "ok", "mode": "demo", "data": _pool,
            "template": config.get("generated_from_template"),
            "biological_harmony": config.get("biological_harmony", 0.9926),
            "timestamp": time.time()}

@app.post("/achievements/unlock", summary="Unlock achievement", status_code=201)
async def achievements_unlock(request: dict = None):
    """Unlock achievement"""
    _base = {'achievement_id': 'ach-001', 'status': 'unlocked', 'points_awarded': 100, 'badge_awarded': 'First Application'}
    _req = request or {}
    if _req:
        _base['request_received'] = _req
        if 'id' in _base:
            import hashlib as _hl
            _base['id'] = _hl.md5(json.dumps(_req, default=str).encode()).hexdigest()[:12]
    return {"service": "gamification_service", "domain": "gamification",
            "endpoint": "/achievements/unlock", "method": "POST",
            "status": "success", "mode": "demo", "data": _base,
            "template": config.get("generated_from_template"),
            "biological_harmony": config.get("biological_harmony", 0.9926),
            "timestamp": time.time()}

@app.get("/xp", summary="Get experience points")
async def xp(request: Request):
    """Get experience points"""
    q = dict(request.query_params)
    # L69: AI-First — try backend for intelligent response
    _search = q.get('q', '') if q else ''
    if _search:
        try:
            async with httpx.AsyncClient(timeout=8.0) as _aic:
                _air = await _aic.post(
                    f"{AI_BACKEND}/analyze",
                    json={"user_id": "anon", "data": _search,
                           "context": ["gamification", "/xp"]},
                )
                if _air.status_code == 200:
                    _aid = _air.json()
                    return {"service": "gamification_service",
                            "domain": "gamification",
                            "endpoint": "/xp",
                            "method": "GET", "status": "ok", "source": "ai",
                            "data": {"analysis": _aid.get("analysis", ""),
                                     "insights": _aid.get("insights", []),
                                     "recommendations": _aid.get("recommendations", []),
                                     "query": _search},
                            "biological_harmony": config.get("biological_harmony", 0.9926),
                            "timestamp": time.time()}
        except Exception as _exc:
            logger.warning('L69: AI backend unavailable: %s', _exc)
    _pool = {'xp_total': 4200, 'level': 7, 'xp_to_next_level': 800, 'level_name': 'Career Strategist'}
    if q:
        _words = set(w for v in q.values() for w in v.lower().split() if len(w) > 2)
        _stop = {'the','and','for','job','jobs','show','find','get','all','has','are','was'}
        _words -= _stop
        if _words:
            for _k, _items in list(_pool.items()):
                if isinstance(_items, list) and _items and isinstance(_items[0], dict):
                    _items = [i for i in _items if any(w in json.dumps(i, default=str).lower() for w in _words)]
                    _pool[_k] = _items
                    if 'total' in _pool: _pool['total'] = len(_items)
        _pool['query'] = q
    return {"service": "gamification_service", "domain": "gamification",
            "endpoint": "/xp", "method": "GET",
            "status": "ok", "mode": "demo", "data": _pool,
            "template": config.get("generated_from_template"),
            "biological_harmony": config.get("biological_harmony", 0.9926),
            "timestamp": time.time()}

@app.get("/badges", summary="List earned badges")
async def badges(request: Request):
    """List earned badges"""
    q = dict(request.query_params)
    # L69: AI-First — try backend for intelligent response
    _search = q.get('q', '') if q else ''
    if _search:
        try:
            async with httpx.AsyncClient(timeout=8.0) as _aic:
                _air = await _aic.post(
                    f"{AI_BACKEND}/analyze",
                    json={"user_id": "anon", "data": _search,
                           "context": ["gamification", "/badges"]},
                )
                if _air.status_code == 200:
                    _aid = _air.json()
                    return {"service": "gamification_service",
                            "domain": "gamification",
                            "endpoint": "/badges",
                            "method": "GET", "status": "ok", "source": "ai",
                            "data": {"analysis": _aid.get("analysis", ""),
                                     "insights": _aid.get("insights", []),
                                     "recommendations": _aid.get("recommendations", []),
                                     "query": _search},
                            "biological_harmony": config.get("biological_harmony", 0.9926),
                            "timestamp": time.time()}
        except Exception as _exc:
            logger.warning('L69: AI backend unavailable: %s', _exc)
    _pool = {'badges': [{'id': 'badge-001', 'name': 'First Application', 'earned': True, 'earned_at': '2026-01-20'}, {'id': 'badge-002', 'name': 'Interview Master', 'earned': False}], 'total': 2, 'earned': 1}
    if q:
        _words = set(w for v in q.values() for w in v.lower().split() if len(w) > 2)
        _stop = {'the','and','for','job','jobs','show','find','get','all','has','are','was'}
        _words -= _stop
        if _words:
            for _k, _items in list(_pool.items()):
                if isinstance(_items, list) and _items and isinstance(_items[0], dict):
                    _items = [i for i in _items if any(w in json.dumps(i, default=str).lower() for w in _words)]
                    _pool[_k] = _items
                    if 'total' in _pool: _pool['total'] = len(_items)
        _pool['query'] = q
    return {"service": "gamification_service", "domain": "gamification",
            "endpoint": "/badges", "method": "GET",
            "status": "ok", "mode": "demo", "data": _pool,
            "template": config.get("generated_from_template"),
            "biological_harmony": config.get("biological_harmony", 0.9926),
            "timestamp": time.time()}

@app.get("/points", summary="Get points balance")
async def points(request: Request):
    """Get points balance"""
    q = dict(request.query_params)
    # L69: AI-First — try backend for intelligent response
    _search = q.get('q', '') if q else ''
    if _search:
        try:
            async with httpx.AsyncClient(timeout=8.0) as _aic:
                _air = await _aic.post(
                    f"{AI_BACKEND}/analyze",
                    json={"user_id": "anon", "data": _search,
                           "context": ["gamification", "/points"]},
                )
                if _air.status_code == 200:
                    _aid = _air.json()
                    return {"service": "gamification_service",
                            "domain": "gamification",
                            "endpoint": "/points",
                            "method": "GET", "status": "ok", "source": "ai",
                            "data": {"analysis": _aid.get("analysis", ""),
                                     "insights": _aid.get("insights", []),
                                     "recommendations": _aid.get("recommendations", []),
                                     "query": _search},
                            "biological_harmony": config.get("biological_harmony", 0.9926),
                            "timestamp": time.time()}
        except Exception as _exc:
            logger.warning('L69: AI backend unavailable: %s', _exc)
    _pool = {'points_balance': 1250, 'points_earned_today': 50, 'points_earned_total': 3890, 'next_milestone': 1500}
    if q:
        _words = set(w for v in q.values() for w in v.lower().split() if len(w) > 2)
        _stop = {'the','and','for','job','jobs','show','find','get','all','has','are','was'}
        _words -= _stop
        if _words:
            for _k, _items in list(_pool.items()):
                if isinstance(_items, list) and _items and isinstance(_items[0], dict):
                    _items = [i for i in _items if any(w in json.dumps(i, default=str).lower() for w in _words)]
                    _pool[_k] = _items
                    if 'total' in _pool: _pool['total'] = len(_items)
        _pool['query'] = q
    return {"service": "gamification_service", "domain": "gamification",
            "endpoint": "/points", "method": "GET",
            "status": "ok", "mode": "demo", "data": _pool,
            "template": config.get("generated_from_template"),
            "biological_harmony": config.get("biological_harmony", 0.9926),
            "timestamp": time.time()}

@app.post("/challenges/join", summary="Join a challenge", status_code=201)
async def challenges_join(request: dict = None):
    """Join a challenge"""
    _base = {'challenge_id': 'chal-001', 'status': 'joined', 'name': 'Apply to 5 Jobs This Week', 'deadline': '2026-03-21'}
    _req = request or {}
    if _req:
        _base['request_received'] = _req
        if 'id' in _base:
            import hashlib as _hl
            _base['id'] = _hl.md5(json.dumps(_req, default=str).encode()).hexdigest()[:12]
    return {"service": "gamification_service", "domain": "gamification",
            "endpoint": "/challenges/join", "method": "POST",
            "status": "success", "mode": "demo", "data": _base,
            "template": config.get("generated_from_template"),
            "biological_harmony": config.get("biological_harmony", 0.9926),
            "timestamp": time.time()}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "gamification_service", "error": exc.detail, "status_code": exc.status_code})


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting gamification_service port=%d tier=%s ns=%s", SERVICE_PORT, RESOURCE_TIER, KUBERNETES_NS)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
