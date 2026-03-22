#!/usr/bin/env python3
"""
_patch_personality_assessment.py — Plan 149: Wire personality_assessment_service (port 8275)

Jungian personality assessment system:
- 12-question assessment probing Extrovert↔Introvert and Thinker↔Feeler axes
- Session-based question flow with 1-5 scoring
- Four quadrants: Red (Extrovert+Thinker), Yellow (Extrovert+Feeler),
  Blue (Introvert+Thinker), Green (Introvert+Feeler)
- Career fit recommendations + CV tone suggestions per quadrant
- Async persistence to Pinecone via memory-system
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _pa_os
import uuid as _pa_uuid
from datetime import datetime as _pa_dt

PERSISTENCE_SERVICE_URL = _pa_os.getenv("PERSISTENCE_SERVICE_URL",
    _pa_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _pa_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

_SESSION_CACHE: dict = {}
_RESULT_CACHE: dict = {}

# 12 Jungian assessment questions — each scores on two axes:
#   ei = Extrovert(+) / Introvert(-),  tf = Thinker(+) / Feeler(-)
# answer scale: 1 (strongly disagree) to 5 (strongly agree)
_QUESTIONS = [
    {"id": "q01", "text": "I feel energized after spending time with a large group of people.",
     "axis": "ei", "direction": 1, "category": "energy_source"},
    {"id": "q02", "text": "I prefer to think through a problem alone before discussing it with others.",
     "axis": "ei", "direction": -1, "category": "problem_solving"},
    {"id": "q03", "text": "When making decisions, I prioritize logical consistency over how people feel.",
     "axis": "tf", "direction": 1, "category": "decision_making"},
    {"id": "q04", "text": "I find it easy to start conversations with strangers.",
     "axis": "ei", "direction": 1, "category": "communication"},
    {"id": "q05", "text": "I value harmony in a team more than being objectively correct.",
     "axis": "tf", "direction": -1, "category": "team_dynamics"},
    {"id": "q06", "text": "I prefer structured plans and clear agendas over spontaneous collaboration.",
     "axis": "tf", "direction": 1, "category": "problem_solving"},
    {"id": "q07", "text": "I recharge best through quiet reflection rather than social activity.",
     "axis": "ei", "direction": -1, "category": "energy_source"},
    {"id": "q08", "text": "I naturally consider the emotional impact of a decision on others.",
     "axis": "tf", "direction": -1, "category": "decision_making"},
    {"id": "q09", "text": "I enjoy leading meetings and facilitating group discussions.",
     "axis": "ei", "direction": 1, "category": "communication"},
    {"id": "q10", "text": "I prefer working independently on deep-focus tasks.",
     "axis": "ei", "direction": -1, "category": "team_dynamics"},
    {"id": "q11", "text": "I am more persuaded by data and evidence than by personal stories.",
     "axis": "tf", "direction": 1, "category": "decision_making"},
    {"id": "q12", "text": "I find it important that everyone on the team feels included and heard.",
     "axis": "tf", "direction": -1, "category": "team_dynamics"},
]

_QUADRANT_PROFILES = {
    "Red": {
        "label": "Extroverted Thinker",
        "color": "Red",
        "traits": ["Structured", "Assertive", "Efficient", "Decisive", "Results-driven"],
        "career_fit": ["Executive", "Project Lead", "Operations Director", "Management Consultant", "Entrepreneur"],
        "cv_tone": "Lead with measurable results and impact. Use action verbs (drove, delivered, optimized). "
                   "Structure sections with clear metrics. Emphasize leadership scope and strategic outcomes.",
        "strengths": "Drive performance, manage teams, implement systems, make tough calls quickly",
        "risks": "Can be overly focused on results, emotionally blunt, may overlook team morale",
    },
    "Yellow": {
        "label": "Extroverted Feeler",
        "color": "Yellow",
        "traits": ["Expressive", "Enthusiastic", "Inclusive", "Supportive", "Energizing"],
        "career_fit": ["Coach", "Customer Success Manager", "Sales Leader", "HR Director", "Community Manager"],
        "cv_tone": "Highlight collaboration, team-building, and stakeholder relationships. "
                   "Use warm, engaging language. Show how you create belonging and drive engagement. "
                   "Include cross-functional impact and mentoring outcomes.",
        "strengths": "Lead with empathy, energize teams, create belonging, build consensus",
        "risks": "Can prioritize harmony over hard truths, may avoid difficult feedback",
    },
    "Blue": {
        "label": "Introverted Thinker",
        "color": "Blue",
        "traits": ["Analytical", "Strategic", "Independent", "Precise", "Methodical"],
        "career_fit": ["Analyst", "Consultant", "Researcher", "Engineer", "Data Scientist"],
        "cv_tone": "Emphasize analytical depth, technical expertise, and problem-solving methodology. "
                   "Use precise language with quantified outcomes. Structure logically with clear cause-effect. "
                   "Highlight patents, publications, or complex systems built.",
        "strengths": "Deep focus, problem-solving, objective insights, systematic thinking",
        "risks": "May struggle with collaboration or emotional expression, can over-analyze",
    },
    "Green": {
        "label": "Introverted Feeler",
        "color": "Green",
        "traits": ["Loyal", "Thoughtful", "Empathetic", "Reflective", "Purpose-driven"],
        "career_fit": ["Therapist", "Mentor", "Creator", "Facilitator", "UX Researcher"],
        "cv_tone": "Convey purpose and values alignment. Use reflective language showing depth of understanding. "
                   "Highlight long-term commitment, mentoring, and meaningful impact on individuals. "
                   "Show how your work connects to larger mission.",
        "strengths": "Deep purpose, resilience, values-based leadership, authentic relationships",
        "risks": "Overly self-critical, conflict-averse, may internalize stress",
    },
}


def _compute_result(answers):
    ei_score = 0.0
    tf_score = 0.0
    for qid, value in answers.items():
        q = next((q for q in _QUESTIONS if q["id"] == qid), None)
        if not q:
            continue
        centered = value - 3  # center around 0: -2 to +2
        if q["axis"] == "ei":
            ei_score += centered * q["direction"]
        else:
            tf_score += centered * q["direction"]
    # Determine quadrant
    is_extrovert = ei_score >= 0
    is_thinker = tf_score >= 0
    if is_extrovert and is_thinker:
        quadrant = "Red"
    elif is_extrovert and not is_thinker:
        quadrant = "Yellow"
    elif not is_extrovert and is_thinker:
        quadrant = "Blue"
    else:
        quadrant = "Green"
    profile = _QUADRANT_PROFILES[quadrant]
    return {
        "quadrant": quadrant,
        "label": profile["label"],
        "ei_score": round(ei_score, 2),
        "tf_score": round(tf_score, 2),
        "axis_labels": {
            "ei": "Extrovert" if is_extrovert else "Introvert",
            "tf": "Thinker" if is_thinker else "Feeler",
        },
        "traits": profile["traits"],
        "career_fit": profile["career_fit"],
        "cv_tone": profile["cv_tone"],
        "strengths": profile["strengths"],
        "risks": profile["risks"],
    }


async def _persist_assessment(user_id, result_data):
    _RESULT_CACHE.setdefault(user_id, []).append(result_data)
    if len(_RESULT_CACHE.get(user_id, [])) > 50:
        _RESULT_CACHE[user_id] = _RESULT_CACHE[user_id][-50:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": "personality_assessment",
                "data": json.dumps(result_data),
                "entity_id": f"{user_id}_personality_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 149: Personality assessment store failed: {e}")


async def _get_assessment_history(user_id):
    cached = _RESULT_CACHE.get(user_id, [])
    backend = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": "personality_assessment"})
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


@app.get("/", summary="Service information")
async def root():
    return {"service": "personality_assessment_service", "type": "backend", "domain": "assessment",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan149",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["personality_assessment", "jungian_quadrants", "career_fit", "cv_tone"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "personality_assessment_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan149", "persistence": PERSISTENCE_PROVIDER, "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "personality_assessment_service", "port": SERVICE_PORT, "uptime_seconds": time.time(),
            "active_sessions": len(_SESSION_CACHE), "completed_assessments": sum(len(v) for v in _RESULT_CACHE.values())}

@app.post("/assessment/start", summary="Start personality assessment", status_code=201)
async def assessment_start(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    session_id = f"session-{_pa_uuid.uuid4().hex[:12]}"
    session = {
        "session_id": session_id,
        "user_id": user_id,
        "started_at": _pa_dt.now().isoformat(),
        "answers": {},
        "current_index": 0,
        "total_questions": len(_QUESTIONS),
        "completed": False,
    }
    _SESSION_CACHE[f"{user_id}_{session_id}"] = session
    first_q = _QUESTIONS[0]
    return {"service": "personality_assessment_service", "endpoint": "/assessment/start",
            "status": "started", "data": {
                "session_id": session_id,
                "total_questions": len(_QUESTIONS),
                "question": {"id": first_q["id"], "text": first_q["text"],
                             "category": first_q["category"], "index": 1,
                             "scale": "1 (strongly disagree) to 5 (strongly agree)"},
            }, "timestamp": time.time()}

@app.post("/assessment/answer", summary="Submit answer to current question")
async def assessment_answer(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    session_id = body.get("session_id", "")
    question_id = body.get("question_id", "")
    answer = body.get("answer")
    if not user_id or not session_id:
        raise HTTPException(status_code=400, detail="user_id and session_id required")
    if not question_id or answer is None:
        raise HTTPException(status_code=400, detail="question_id and answer required")
    try:
        answer = int(answer)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="answer must be integer 1-5")
    if answer < 1 or answer > 5:
        raise HTTPException(status_code=400, detail="answer must be between 1 and 5")
    session_key = f"{user_id}_{session_id}"
    session = _SESSION_CACHE.get(session_key)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Start a new assessment.")
    if session.get("completed"):
        raise HTTPException(status_code=400, detail="Assessment already completed. Get results at /assessment/result")
    # Validate question_id exists
    if not any(q["id"] == question_id for q in _QUESTIONS):
        raise HTTPException(status_code=400, detail=f"Invalid question_id: {question_id}")
    session["answers"][question_id] = answer
    session["current_index"] = len(session["answers"])
    # Check if all questions answered
    if len(session["answers"]) >= len(_QUESTIONS):
        session["completed"] = True
        session["completed_at"] = _pa_dt.now().isoformat()
        result = _compute_result(session["answers"])
        result["session_id"] = session_id
        result["user_id"] = user_id
        result["timestamp"] = _pa_dt.now().isoformat()
        result["answers"] = session["answers"]
        session["result"] = result
        await _persist_assessment(user_id, result)
        return {"service": "personality_assessment_service", "endpoint": "/assessment/answer",
                "status": "completed", "data": {
                    "completed": True,
                    "quadrant": result["quadrant"],
                    "label": result["label"],
                    "message": "Assessment complete! Get full results at GET /assessment/result",
                }, "timestamp": time.time()}
    # Return next question
    next_idx = session["current_index"]
    next_q = _QUESTIONS[next_idx]
    return {"service": "personality_assessment_service", "endpoint": "/assessment/answer",
            "status": "answered", "data": {
                "completed": False,
                "answered": len(session["answers"]),
                "remaining": len(_QUESTIONS) - len(session["answers"]),
                "next_question": {"id": next_q["id"], "text": next_q["text"],
                                  "category": next_q["category"],
                                  "index": next_idx + 1,
                                  "scale": "1 (strongly disagree) to 5 (strongly agree)"},
            }, "timestamp": time.time()}

@app.get("/assessment/result", summary="Get assessment result")
async def assessment_result(request: Request):
    params = dict(request.query_params)
    user_id = params.get("user_id", "")
    session_id = params.get("session_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if session_id:
        session_key = f"{user_id}_{session_id}"
        session = _SESSION_CACHE.get(session_key)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not session.get("completed"):
            remaining = len(_QUESTIONS) - len(session.get("answers", {}))
            raise HTTPException(status_code=400, detail=f"Assessment not complete. {remaining} questions remaining.")
        result = session.get("result", {})
    else:
        # Return most recent result from cache or Pinecone
        history = await _get_assessment_history(user_id)
        if not history:
            raise HTTPException(status_code=404, detail="No assessment results found for this user")
        result = history[-1]
    return {"service": "personality_assessment_service", "endpoint": "/assessment/result",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": result, "timestamp": time.time()}

@app.get("/assessment/history", summary="Past personality assessments")
async def assessment_history(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    history = await _get_assessment_history(user_id)
    return {"service": "personality_assessment_service", "endpoint": "/assessment/history",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"assessments": history[-20:], "total": len(history)},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "personality_assessment_service", "error": exc.detail})

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
    if "Plan 149" in content and "_persist_assessment" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "personality_assessment_service"
    if svc.exists():
        patch_service(svc)
