#!/usr/bin/env python3
"""
_patch_wheel_of_life.py — Plan 149: Wire wheel_of_life_service

Wheel of Life balance assessment tool:
- Rate 8 life dimensions (1-10)
- AI analysis of scores + recommendations
- Goal setting per dimension
- Historical trend tracking
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _wol_os
from datetime import datetime as _wol_dt

PERSISTENCE_SERVICE_URL = _wol_os.getenv("PERSISTENCE_SERVICE_URL",
    _wol_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _wol_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

_ASSESSMENT_CACHE: dict = {}
_GOALS_CACHE: dict = {}

DIMENSIONS = ["Career", "Finance", "Health", "Family_Relationships",
              "Social_Life", "Personal_Growth", "Fun_Recreation", "Physical_Environment"]


async def _store_wol_event(user_id, entity_type, data_dict):
    event = {**data_dict, "entity_type": entity_type, "timestamp": _wol_dt.now().isoformat()}
    _ASSESSMENT_CACHE.setdefault(user_id, []).append(event)
    if len(_ASSESSMENT_CACHE.get(user_id, [])) > 200:
        _ASSESSMENT_CACHE[user_id] = _ASSESSMENT_CACHE[user_id][-200:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": entity_type,
                "data": json.dumps(event),
                "entity_id": f"{user_id}_{entity_type}_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 149: WoL store failed: {e}")


async def _get_wol_events(user_id, entity_type):
    cached = [e for e in _ASSESSMENT_CACHE.get(user_id, []) if e.get("entity_type") == entity_type]
    backend = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": entity_type})
            if resp.status_code == 200:
                for entry in resp.json().get("history", []):
                    try:
                        backend.append(json.loads(entry.get("data", "{}")) if isinstance(entry.get("data"), str) else entry.get("data", {}))
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception:
        pass
    pc_ts = {e.get("timestamp", "") for e in backend}
    return backend + [e for e in cached if e.get("timestamp", "") not in pc_ts]


def _analyze_scores(scores):
    valid = {d: s for d, s in scores.items() if d in DIMENSIONS and isinstance(s, (int, float)) and 1 <= s <= 10}
    if not valid:
        return {"error": "No valid dimension scores provided"}
    avg = round(sum(valid.values()) / len(valid), 2)
    sorted_dims = sorted(valid.items(), key=lambda x: x[1])
    lowest = sorted_dims[0]
    highest = sorted_dims[-1]
    bottom_3 = sorted_dims[:3]
    recommendations = []
    for dim, score in bottom_3:
        if score <= 3:
            recommendations.append(f"{dim} ({score}/10): Critical — needs immediate attention and daily micro-actions")
        elif score <= 5:
            recommendations.append(f"{dim} ({score}/10): Below average — set 1-2 weekly improvement goals")
        else:
            recommendations.append(f"{dim} ({score}/10): Moderate — small consistent habits will elevate this area")
    return {
        "scores": valid,
        "average": avg,
        "lowest_dimension": {"name": lowest[0], "score": lowest[1]},
        "highest_dimension": {"name": highest[0], "score": highest[1]},
        "bottom_3_recommendations": recommendations,
        "balance_rating": "well-balanced" if (highest[1] - lowest[1]) <= 3 else "imbalanced",
        "dimensions_rated": len(valid),
    }


def _compute_trends(assessments):
    if len(assessments) < 2:
        return {"status": "insufficient_data", "message": "Need at least 2 assessments for trends"}
    trends = {}
    for dim in DIMENSIONS:
        values = [a.get("scores", {}).get(dim) for a in assessments if a.get("scores", {}).get(dim) is not None]
        if len(values) >= 2:
            recent = values[-1]
            previous = values[-2]
            diff = recent - previous
            if diff > 0.5:
                trend = "improving"
            elif diff < -0.5:
                trend = "declining"
            else:
                trend = "stable"
            trends[dim] = {"current": recent, "previous": previous, "change": round(diff, 2), "trend": trend}
    return trends


@app.get("/", summary="Service information")
async def root():
    return {"service": "wheel_of_life_service", "type": "backend", "domain": "wellness",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan149",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["wheel_of_life", "dimension_assessment", "goal_setting", "trend_tracking"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "wheel_of_life_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan149", "persistence": PERSISTENCE_PROVIDER, "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "wheel_of_life_service", "port": SERVICE_PORT, "uptime_seconds": time.time()}

@app.post("/wheel/assess", summary="Rate 8 life dimensions (1-10)", status_code=201)
async def wheel_assess(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    scores = body.get("scores", {})
    if not scores or not isinstance(scores, dict):
        raise HTTPException(status_code=400, detail=f"scores dict required with dimensions: {DIMENSIONS}")
    analysis = _analyze_scores(scores)
    if "error" in analysis:
        raise HTTPException(status_code=400, detail=analysis["error"])
    assessment = {
        "assessment_id": f"wol-{int(time.time())}",
        "scores": analysis["scores"],
        "average": analysis["average"],
        "lowest_dimension": analysis["lowest_dimension"],
        "highest_dimension": analysis["highest_dimension"],
        "balance_rating": analysis["balance_rating"],
        "bottom_3_recommendations": analysis["bottom_3_recommendations"],
    }
    await _store_wol_event(user_id, "wol_assessment", assessment)
    return {"service": "wheel_of_life_service", "endpoint": "/wheel/assess",
            "status": "created", "source": PERSISTENCE_PROVIDER,
            "data": assessment, "timestamp": time.time()}

@app.get("/wheel/result", summary="Get latest assessment result")
async def wheel_result(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    assessments = await _get_wol_events(user_id, "wol_assessment")
    if not assessments:
        return {"service": "wheel_of_life_service", "endpoint": "/wheel/result",
                "status": "ok", "source": PERSISTENCE_PROVIDER,
                "data": {"message": "No assessments found", "assessments": []},
                "timestamp": time.time()}
    latest = assessments[-1]
    return {"service": "wheel_of_life_service", "endpoint": "/wheel/result",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {
                "latest": latest,
                "scores": latest.get("scores", {}),
                "average": latest.get("average"),
                "lowest_dimension": latest.get("lowest_dimension"),
                "highest_dimension": latest.get("highest_dimension"),
                "balance_rating": latest.get("balance_rating"),
                "bottom_3_recommendations": latest.get("bottom_3_recommendations", []),
                "total_assessments": len(assessments),
            },
            "timestamp": time.time()}

@app.post("/wheel/goals", summary="Set improvement goals per dimension", status_code=201)
async def wheel_goals(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    goals = body.get("goals", {})
    if not goals or not isinstance(goals, dict):
        raise HTTPException(status_code=400, detail="goals dict required: {dimension: {target_score, action_plan}}")
    validated_goals = {}
    for dim, goal_data in goals.items():
        if dim not in DIMENSIONS:
            continue
        if not isinstance(goal_data, dict):
            continue
        validated_goals[dim] = {
            "target_score": min(10, max(1, int(goal_data.get("target_score", 8)))),
            "action_plan": goal_data.get("action_plan", ""),
            "set_at": _wol_dt.now().isoformat(),
        }
    if not validated_goals:
        raise HTTPException(status_code=400, detail=f"No valid goals. Dimensions: {DIMENSIONS}")
    goal_record = {
        "goal_id": f"wol-goal-{int(time.time())}",
        "goals": validated_goals,
        "dimensions_targeted": list(validated_goals.keys()),
    }
    _GOALS_CACHE.setdefault(user_id, []).append(goal_record)
    await _store_wol_event(user_id, "wol_goal", goal_record)
    return {"service": "wheel_of_life_service", "endpoint": "/wheel/goals",
            "status": "created", "source": PERSISTENCE_PROVIDER,
            "data": goal_record, "timestamp": time.time()}

@app.get("/wheel/history", summary="Past assessments with trends")
async def wheel_history(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    assessments = await _get_wol_events(user_id, "wol_assessment")
    trends = _compute_trends(assessments)
    return {"service": "wheel_of_life_service", "endpoint": "/wheel/history",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {
                "assessments": assessments[-20:],
                "total": len(assessments),
                "trends": trends,
            },
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "wheel_of_life_service", "error": exc.detail})

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
    if "Plan 149" in content and "_store_wol_event" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "wheel_of_life_service"
    if svc.exists():
        patch_service(svc)
