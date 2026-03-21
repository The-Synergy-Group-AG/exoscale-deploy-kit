#!/usr/bin/env python3
"""
_patch_crm_wiring.py — Plan 147: Wire crm_integration_service

Contact management + application pipeline:
- Contact CRUD (recruiters, companies, networking connections)
- Application pipeline stages (applied → interview → offer → accepted/rejected)
- Follow-up reminders
- Interview scheduling (calendar events)
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _crm_os
from datetime import datetime as _crm_dt

PERSISTENCE_SERVICE_URL = _crm_os.getenv("PERSISTENCE_SERVICE_URL",
    _crm_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _crm_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

_CONTACT_CACHE: dict = {}
_EVENT_CACHE: dict = {}

PIPELINE_STAGES = ["applied", "phone_screen", "interview_scheduled", "interviewed",
                   "second_round", "offer", "accepted", "rejected", "withdrawn"]


async def _store_crm_event(user_id, entity_type, data_dict):
    event = {**data_dict, "entity_type": entity_type, "timestamp": _crm_dt.now().isoformat()}
    _EVENT_CACHE.setdefault(user_id, []).append(event)
    if len(_EVENT_CACHE.get(user_id, [])) > 200:
        _EVENT_CACHE[user_id] = _EVENT_CACHE[user_id][-200:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": entity_type,
                "data": json.dumps(event),
                "entity_id": f"{user_id}_{entity_type}_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 147: CRM store failed: {e}")


async def _get_crm_events(user_id, entity_type):
    cached = [e for e in _EVENT_CACHE.get(user_id, []) if e.get("entity_type") == entity_type]
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


@app.get("/", summary="Service information")
async def root():
    return {"service": "crm_integration_service", "type": "backend", "domain": "workflow",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan147",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["contacts", "pipeline", "follow_ups", "calendar_events"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "crm_integration_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan147", "persistence": PERSISTENCE_PROVIDER, "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "crm_integration_service", "port": SERVICE_PORT, "uptime_seconds": time.time()}

@app.post("/contacts", summary="Add contact", status_code=201)
async def add_contact(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    contact = {
        "contact_id": f"contact-{int(time.time())}",
        "name": body.get("name", ""),
        "company": body.get("company", ""),
        "role": body.get("role", ""),
        "email": body.get("email", ""),
        "phone": body.get("phone", ""),
        "notes": body.get("notes", ""),
        "type": body.get("type", "recruiter"),  # recruiter, hiring_manager, network, other
        "status": "active",
    }
    await _store_crm_event(user_id, "contact", contact)
    return {"service": "crm_integration_service", "endpoint": "/contacts",
            "status": "created", "source": PERSISTENCE_PROVIDER,
            "data": contact, "timestamp": time.time()}

@app.get("/contacts", summary="List contacts")
async def list_contacts(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    contacts = await _get_crm_events(user_id, "contact") if user_id else []
    return {"service": "crm_integration_service", "endpoint": "/contacts",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"contacts": contacts[-50:], "total": len(contacts)},
            "timestamp": time.time()}

@app.get("/pipeline", summary="Application pipeline")
async def pipeline(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    apps = await _get_crm_events(user_id, "pipeline_event") if user_id else []
    by_stage = {}
    for stage in PIPELINE_STAGES:
        by_stage[stage] = [a for a in apps if a.get("stage") == stage]
    return {"service": "crm_integration_service", "endpoint": "/pipeline",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"stages": PIPELINE_STAGES, "by_stage": {s: len(v) for s, v in by_stage.items()},
                     "total_active": sum(len(v) for s, v in by_stage.items() if s not in ("rejected", "withdrawn", "accepted")),
                     "applications": apps[-30:]},
            "timestamp": time.time()}

@app.post("/pipeline/update", summary="Update pipeline stage", status_code=200)
async def update_pipeline(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    company = body.get("company", "")
    role = body.get("role", "")
    stage = body.get("stage", "applied")
    if not user_id or not company:
        raise HTTPException(status_code=400, detail="user_id and company required")
    if stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Valid: {PIPELINE_STAGES}")
    event = {"company": company, "role": role, "stage": stage, "notes": body.get("notes", "")}
    await _store_crm_event(user_id, "pipeline_event", event)
    return {"service": "crm_integration_service", "endpoint": "/pipeline/update",
            "status": "updated", "source": PERSISTENCE_PROVIDER,
            "data": event, "timestamp": time.time()}

@app.post("/calendar/event", summary="Create calendar event", status_code=201)
async def create_calendar_event(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    event = {
        "event_id": f"cal-{int(time.time())}",
        "type": body.get("type", "interview"),
        "date": body.get("date", ""),
        "time": body.get("time", ""),
        "company": body.get("company", ""),
        "role": body.get("role", ""),
        "location": body.get("location", ""),
        "notes": body.get("notes", ""),
        "reminder_24h": True,
        "reminder_1h": True,
    }
    await _store_crm_event(user_id, "calendar_event", event)
    return {"service": "crm_integration_service", "endpoint": "/calendar/event",
            "status": "created", "source": PERSISTENCE_PROVIDER,
            "data": event, "timestamp": time.time()}

@app.get("/calendar/upcoming", summary="List upcoming events")
async def upcoming_events(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_crm_events(user_id, "calendar_event") if user_id else []
    # Sort by date (most recent first)
    events.sort(key=lambda e: e.get("date", ""), reverse=False)
    return {"service": "crm_integration_service", "endpoint": "/calendar/upcoming",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"events": events[-20:], "total": len(events)},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "crm_integration_service", "error": exc.detail})

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
    if "Plan 147" in content and "_store_crm_event" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "crm_integration_service"
    if svc.exists():
        patch_service(svc)
