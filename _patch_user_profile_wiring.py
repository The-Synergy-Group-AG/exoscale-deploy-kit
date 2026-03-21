#!/usr/bin/env python3
"""
_patch_user_profile_wiring.py — Plan 146: Wire user_profile_service

User profile persistence with cross-device sync:
- Profile CRUD (name, skills, target role, preferences)
- Cross-device data via Pinecone
- Profile completeness scoring
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _up_os
from datetime import datetime as _up_dt

PERSISTENCE_SERVICE_URL = _up_os.getenv("PERSISTENCE_SERVICE_URL",
    _up_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _up_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

_PROFILE_CACHE: dict = {}


async def _store_profile(user_id, profile_data):
    _PROFILE_CACHE[user_id] = {**profile_data, "updated_at": _up_dt.now().isoformat()}
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": "user_profile",
                "data": json.dumps(_PROFILE_CACHE[user_id]),
                "entity_id": f"{user_id}_profile_latest",
            })
    except Exception as e:
        logger.warning(f"Plan 146: Profile store failed: {e}")


async def _get_profile(user_id):
    if user_id in _PROFILE_CACHE:
        return _PROFILE_CACHE[user_id]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": "user_profile"})
            if resp.status_code == 200:
                history = resp.json().get("history", [])
                if history:
                    data_str = history[-1].get("data", "{}")
                    profile = json.loads(data_str) if isinstance(data_str, str) else data_str
                    _PROFILE_CACHE[user_id] = profile
                    return profile
    except Exception:
        pass
    return {}


def _calc_completeness(profile):
    fields = ["name", "email", "target_role", "skills", "experience_years", "languages", "location"]
    filled = sum(1 for f in fields if profile.get(f))
    return round(filled / len(fields), 2)


@app.get("/", summary="Service information")
async def root():
    return {"service": "user_profile_service", "type": "backend", "domain": "user_management",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan146",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["profile_crud", "completeness_scoring", "cross_device_sync"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "user_profile_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan146", "persistence": PERSISTENCE_PROVIDER, "timestamp": time.time()}

@app.get("/metrics", summary="Prometheus metrics")
async def metrics():
    return {"service": "user_profile_service", "port": SERVICE_PORT, "uptime_seconds": time.time()}

@app.get("/profile", summary="Get user profile")
async def get_profile(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    profile = await _get_profile(user_id) if user_id else {}
    completeness = _calc_completeness(profile) if profile else 0
    return {"service": "user_profile_service", "endpoint": "/profile",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {**profile, "completeness": completeness},
            "timestamp": time.time()}

@app.put("/profile", summary="Update user profile")
async def update_profile(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.pop("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    existing = await _get_profile(user_id)
    merged = {**existing, **body}
    await _store_profile(user_id, merged)
    return {"service": "user_profile_service", "endpoint": "/profile",
            "status": "updated", "source": PERSISTENCE_PROVIDER,
            "data": {"completeness": _calc_completeness(merged)},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "user_profile_service", "error": exc.detail})

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
    if "Plan 146" in content and "_store_profile" in content:
        print(f"  SKIP: {main_py} already patched")
        return False
    app_match = re.search(r"app = FastAPI\([^)]+\)", content, re.DOTALL)
    if not app_match:
        return False
    main_py.write_text(content[:app_match.end()] + "\n" + _ENDPOINTS_CODE)
    print(f"  PATCHED: {main_py}")
    return True


if __name__ == "__main__":
    from pathlib import Path
    gen = (Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / "CURRENT").read_text().strip()
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "user_profile_service"
    if svc.exists():
        patch_service(svc)
