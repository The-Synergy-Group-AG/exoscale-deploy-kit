#!/usr/bin/env python3
"""
_patch_interview_wiring.py — Plan 145: Wire interview_prep_service to Pinecone

Replaces mock endpoints with real interview tracking:
- Mock interview sessions with Q&A state
- STAR method scoring per answer
- Interview history per user
- Company/role-specific question generation tracking
"""
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

_ENDPOINTS_CODE = '''

# ── Plan 145: Interview Tracking with Pinecone Persistence ──────────────────

import os as _iv_os
from datetime import datetime as _iv_dt

MEMORY_SYSTEM_URL = _iv_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009")

_INTERVIEW_CACHE: dict = {}


async def _store_interview_event(user_id, event_type, data_dict):
    try:
        _INTERVIEW_CACHE.setdefault(user_id, []).append({**data_dict, "event_type": event_type, "timestamp": _iv_dt.now().isoformat()})
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{MEMORY_SYSTEM_URL}/store", json={
                "user_id": user_id, "entity_type": "interview",
                "data": json.dumps({**data_dict, "event_type": event_type, "timestamp": _iv_dt.now().isoformat()}),
                "entity_id": f"{user_id}_interview_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 145: interview store failed: {e}")


async def _get_interview_history(user_id):
    cached = _INTERVIEW_CACHE.get(user_id, [])
    pinecone_events = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{MEMORY_SYSTEM_URL}/history/{user_id}", params={"entity_type": "interview"})
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


@app.get("/", summary="Service information")
async def root():
    return {"service": "interview_prep_service", "type": "backend", "domain": "career",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan145",
            "capabilities": ["mock_interview", "star_scoring", "question_generation", "interview_history"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "interview_prep_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan145", "persistence": "pinecone", "timestamp": time.time()}

@app.get("/metrics", summary="Prometheus metrics")
async def metrics():
    return {"service": "interview_prep_service", "port": SERVICE_PORT, "uptime_seconds": time.time()}

@app.post("/mock-interview/start", summary="Start mock interview session")
async def start_mock_interview(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    role = body.get("role", "General")
    company = body.get("company", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    session_id = f"mock-{int(time.time())}"
    await _store_interview_event(user_id, "mock_interview_started", {
        "session_id": session_id, "role": role, "company": company})
    return {"service": "interview_prep_service", "endpoint": "/mock-interview/start",
            "status": "success", "source": "pinecone",
            "data": {"session_id": session_id, "role": role, "company": company,
                     "message": f"Mock interview started for {role}" + (f" at {company}" if company else "")},
            "timestamp": time.time()}

@app.post("/mock-interview/answer", summary="Score an interview answer using STAR")
async def score_answer(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    question = body.get("question", "")
    answer = body.get("answer", "")
    if not user_id or not answer:
        raise HTTPException(status_code=400, detail="user_id and answer required")
    # STAR scoring heuristic
    answer_lower = answer.lower()
    star_scores = {
        "situation": 1.0 if any(w in answer_lower for w in ["situation", "context", "background", "when", "at my"]) else 0.0,
        "task": 1.0 if any(w in answer_lower for w in ["task", "responsible", "needed to", "goal", "objective"]) else 0.0,
        "action": 1.0 if any(w in answer_lower for w in ["action", "i did", "i led", "i managed", "implemented", "created"]) else 0.0,
        "result": 1.0 if any(w in answer_lower for w in ["result", "outcome", "achieved", "improved", "increased", "reduced", "%"]) else 0.0,
    }
    total_score = sum(star_scores.values()) / 4.0
    await _store_interview_event(user_id, "answer_scored", {
        "question": question[:200], "star_scores": star_scores, "total_score": total_score})
    return {"service": "interview_prep_service", "endpoint": "/mock-interview/answer",
            "status": "success", "source": "pinecone",
            "data": {"star_scores": star_scores, "total_score": round(total_score, 2),
                     "feedback": "Great STAR structure!" if total_score >= 0.75 else
                                 "Try including more STAR elements: " + ", ".join(k.upper() for k, v in star_scores.items() if v == 0)},
            "timestamp": time.time()}

@app.get("/history", summary="Get interview prep history")
async def interview_history(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_interview_history(user_id) if user_id else []
    return {"service": "interview_prep_service", "endpoint": "/history",
            "status": "ok", "source": "pinecone",
            "data": {"sessions": len([e for e in events if e.get("event_type") == "mock_interview_started"]),
                     "answers_scored": len([e for e in events if e.get("event_type") == "answer_scored"]),
                     "history": events[-20:]},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "interview_prep_service", "error": exc.detail})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
'''


def patch_service(service_dir: Path) -> bool:
    import re
    for candidate in [service_dir / "src" / "main.py", service_dir / "main.py"]:
        if candidate.exists():
            main_py = candidate
            break
    else:
        return False
    content = main_py.read_text()
    if "Plan 145" in content and "_store_interview_event" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "interview_prep_service"
    if svc.exists():
        patch_service(svc)
