#!/usr/bin/env python3
"""
_patch_vision_mission.py — Plan 149: Wire vision_mission_service

Vision/Mission/Values/USP builder:
- POST /vision/build — Guided vision/mission builder (5 questions → AI generation)
- GET /vision/current — Get current vision/mission/values/USP
- POST /mission/refine — AI refinement with feedback
- POST /values/rank — Re-rank core values
- GET /usp — Get current USP statement

Output feeds into:
- CV summary/header (USP)
- Cover letter Paragraph 3: Desire (values alignment)
- Interview prep (motivation answers)
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _vm_os
import re as _vm_re
from datetime import datetime as _vm_dt

PERSISTENCE_SERVICE_URL = _vm_os.getenv("PERSISTENCE_SERVICE_URL",
    _vm_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _vm_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

_VISION_CACHE: dict = {}

VISION_QUESTIONS = [
    "What impact do you want to make?",
    "What are you passionate about?",
    "What are your top 3 values?",
    "Where do you see yourself in 5 years?",
    "What legacy do you want to leave?",
]


async def _store_vision_event(user_id, entity_type, data_dict):
    event = {**data_dict, "entity_type": entity_type, "timestamp": _vm_dt.now().isoformat()}
    _VISION_CACHE.setdefault(user_id, {})[entity_type] = event
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": entity_type,
                "data": json.dumps(event),
                "entity_id": f"{user_id}_{entity_type}_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 149: Vision store failed: {e}")


async def _get_vision_latest(user_id, entity_type):
    cached = _VISION_CACHE.get(user_id, {}).get(entity_type)
    backend = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": entity_type})
            if resp.status_code == 200:
                history = resp.json().get("history", [])
                if history:
                    latest = history[-1]
                    try:
                        backend = json.loads(latest.get("data", "{}")) if isinstance(latest.get("data"), str) else latest.get("data", {})
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception:
        pass
    if backend:
        return backend
    return cached


def _build_vision_from_answers(answers):
    a1 = answers.get("impact", answers.get("q1", ""))
    a2 = answers.get("passion", answers.get("q2", ""))
    a3 = answers.get("values", answers.get("q3", ""))
    a4 = answers.get("five_year", answers.get("q4", ""))
    a5 = answers.get("legacy", answers.get("q5", ""))
    values_list = [v.strip() for v in str(a3).split(",") if v.strip()][:10]
    vision = f"To {a1.lower().rstrip('.')} by leveraging my passion for {a2.lower().rstrip('.')}."
    mission = (f"I am committed to {a2.lower().rstrip('.')} and making an impact through "
               f"{a1.lower().rstrip('.')}. In five years, I see myself {a4.lower().rstrip('.')}.")
    usp = (f"A professional driven by {', '.join(values_list[:3]) if values_list else 'excellence'}, "
           f"passionate about {a2.lower().rstrip('.')}, with a clear vision to {a1.lower().rstrip('.')}.")
    return {
        "vision_statement": vision,
        "mission_statement": mission,
        "core_values": values_list,
        "usp": usp,
        "answers": {"impact": a1, "passion": a2, "values": a3, "five_year": a4, "legacy": a5},
    }


@app.get("/", summary="Service information")
async def root():
    return {"service": "vision_mission_service", "type": "backend", "domain": "career_strategy",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan149",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["vision_builder", "mission_refine", "values_ranking", "usp"],
            "feeds_into": ["cv_summary_header", "cover_letter_paragraph3", "interview_prep"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "vision_mission_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan149", "persistence": PERSISTENCE_PROVIDER, "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "vision_mission_service", "port": SERVICE_PORT, "uptime_seconds": time.time()}

@app.post("/vision/build", summary="Guided vision/mission builder", status_code=201)
async def vision_build(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    answers = body.get("answers", {})
    if not answers:
        return {"service": "vision_mission_service", "endpoint": "/vision/build",
                "status": "questions", "data": {"questions": VISION_QUESTIONS},
                "timestamp": time.time()}
    result = _build_vision_from_answers(answers)
    await _store_vision_event(user_id, "vision_profile", result)
    return {"service": "vision_mission_service", "endpoint": "/vision/build",
            "status": "created", "source": PERSISTENCE_PROVIDER,
            "data": result, "timestamp": time.time()}

@app.get("/vision/current", summary="Get current vision/mission/values/USP")
async def vision_current(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    profile = await _get_vision_latest(user_id, "vision_profile")
    if not profile:
        return {"service": "vision_mission_service", "endpoint": "/vision/current",
                "status": "not_found", "data": None, "timestamp": time.time()}
    return {"service": "vision_mission_service", "endpoint": "/vision/current",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": profile, "timestamp": time.time()}

@app.post("/mission/refine", summary="AI refinement with feedback", status_code=200)
async def mission_refine(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    feedback = body.get("feedback", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if not feedback:
        raise HTTPException(status_code=400, detail="feedback text required")
    current = await _get_vision_latest(user_id, "vision_profile")
    if not current:
        raise HTTPException(status_code=404, detail="No vision profile found. Use /vision/build first.")
    old_vision = current.get("vision_statement", "")
    old_mission = current.get("mission_statement", "")
    old_usp = current.get("usp", "")
    refined_vision = f"{old_vision.rstrip('.')} — refined: {feedback.rstrip('.')}."
    refined_mission = f"{old_mission.rstrip('.')} Additionally, {feedback.lower().rstrip('.')}."
    refined_usp = f"{old_usp.rstrip('.')} — {feedback.rstrip('.')}."
    refined = {
        **current,
        "vision_statement": refined_vision,
        "mission_statement": refined_mission,
        "usp": refined_usp,
        "refinement_history": current.get("refinement_history", []) + [
            {"feedback": feedback, "timestamp": _vm_dt.now().isoformat()}
        ],
    }
    await _store_vision_event(user_id, "vision_profile", refined)
    return {"service": "vision_mission_service", "endpoint": "/mission/refine",
            "status": "refined", "source": PERSISTENCE_PROVIDER,
            "data": refined, "timestamp": time.time()}

@app.post("/values/rank", summary="Re-rank core values", status_code=200)
async def values_rank(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    ordered_values = body.get("values", [])
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if not ordered_values or not isinstance(ordered_values, list):
        raise HTTPException(status_code=400, detail="values list required (ordered)")
    current = await _get_vision_latest(user_id, "vision_profile")
    if not current:
        raise HTTPException(status_code=404, detail="No vision profile found. Use /vision/build first.")
    updated = {**current, "core_values": ordered_values[:10]}
    usp_values = ", ".join(ordered_values[:3])
    old_usp = current.get("usp", "")
    if old_usp:
        updated["usp"] = _vm_re.sub(r"driven by [^,]+(?:, [^,]+)*", f"driven by {usp_values}", old_usp)
    await _store_vision_event(user_id, "vision_profile", updated)
    return {"service": "vision_mission_service", "endpoint": "/values/rank",
            "status": "ranked", "source": PERSISTENCE_PROVIDER,
            "data": {"core_values": ordered_values[:10], "usp": updated.get("usp", "")},
            "timestamp": time.time()}

@app.get("/usp", summary="Get current USP statement")
async def get_usp(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    profile = await _get_vision_latest(user_id, "vision_profile")
    if not profile:
        return {"service": "vision_mission_service", "endpoint": "/usp",
                "status": "not_found", "data": None, "timestamp": time.time()}
    return {"service": "vision_mission_service", "endpoint": "/usp",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"usp": profile.get("usp", ""), "core_values": profile.get("core_values", [])},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "vision_mission_service", "error": exc.detail})

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
    if "Plan 149" in content and "_store_vision_event" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "vision_mission_service"
    if svc.exists():
        patch_service(svc)
