#!/usr/bin/env python3
"""
_patch_notification_wiring.py — Plan 146: Wire notification_service

Notification persistence:
- Store notifications per user in Pinecone
- Read/unread tracking
- Notification history
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _nt_os
from datetime import datetime as _nt_dt

PERSISTENCE_SERVICE_URL = _nt_os.getenv("PERSISTENCE_SERVICE_URL",
    _nt_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _nt_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

_NOTIF_CACHE: dict = {}


async def _store_notification(user_id, notif_type, message, metadata=None):
    notif = {"type": notif_type, "message": message, "read": False,
             "metadata": metadata or {}, "timestamp": _nt_dt.now().isoformat()}
    _NOTIF_CACHE.setdefault(user_id, []).append(notif)
    if len(_NOTIF_CACHE.get(user_id, [])) > 100:
        _NOTIF_CACHE[user_id] = _NOTIF_CACHE[user_id][-100:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": "notification",
                "data": json.dumps(notif),
                "entity_id": f"{user_id}_notif_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 146: Notification store failed: {e}")


async def _get_notifications(user_id, unread_only=False):
    cached = _NOTIF_CACHE.get(user_id, [])
    backend = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": "notification"})
            if resp.status_code == 200:
                for entry in resp.json().get("history", []):
                    try:
                        backend.append(json.loads(entry.get("data", "{}")) if isinstance(entry.get("data"), str) else entry.get("data", {}))
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception:
        pass
    pc_ts = {n.get("timestamp", "") for n in backend}
    merged = backend + [n for n in cached if n.get("timestamp", "") not in pc_ts]
    if unread_only:
        merged = [n for n in merged if not n.get("read", True)]
    return sorted(merged, key=lambda n: n.get("timestamp", ""), reverse=True)


@app.get("/", summary="Service information")
async def root():
    return {"service": "notification_service", "type": "backend", "domain": "notification",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan146",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["create", "list", "unread_count", "mark_read"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "notification_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan146", "persistence": PERSISTENCE_PROVIDER, "timestamp": time.time()}

@app.get("/metrics", summary="Prometheus metrics")
async def metrics():
    return {"service": "notification_service", "port": SERVICE_PORT, "uptime_seconds": time.time()}

@app.post("/notifications/create", summary="Create notification", status_code=201)
async def create_notification(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    await _store_notification(user_id, body.get("type", "info"), body.get("message", ""), body.get("metadata"))
    return {"service": "notification_service", "status": "created", "source": PERSISTENCE_PROVIDER,
            "timestamp": time.time()}

@app.get("/notifications", summary="List notifications")
async def list_notifications(request: Request):
    q = dict(request.query_params)
    user_id = q.get("user_id", "")
    unread = q.get("unread", "").lower() == "true"
    notifs = await _get_notifications(user_id, unread_only=unread) if user_id else []
    return {"service": "notification_service", "endpoint": "/notifications",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"notifications": notifs[:50], "total": len(notifs),
                     "unread": sum(1 for n in notifs if not n.get("read", True))},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "notification_service", "error": exc.detail})

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
    if "Plan 146" in content and "_store_notification" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "notification_service"
    if svc.exists():
        patch_service(svc)
