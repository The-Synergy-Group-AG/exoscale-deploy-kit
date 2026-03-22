#!/usr/bin/env python3
"""
_patch_portfolio_wiring.py -- Plan 149: Portfolio Manager

Wires portfolio_service with portfolio management:
- Project portfolio (PDF or digital)
- Work samples / Case studies
- Publications, Articles, Whitepapers
- Certifications & Diplomas
- Awards, Grants, Fellowships
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _pf_os
from datetime import datetime as _pf_dt, timezone as _pf_tz

PERSISTENCE_SERVICE_URL = _pf_os.getenv("PERSISTENCE_SERVICE_URL",
    _pf_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _pf_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

PORTFOLIO_CATEGORIES = ["project", "publication", "certification", "award", "case_study",
                         "work_sample", "testimonial", "media_mention", "speaking"]

_PORTFOLIO_CACHE: dict = {}  # {user_id: [items...]}


async def _store_portfolio_event(user_id, data_dict):
    event = {**data_dict, "entity_type": "portfolio",
             "timestamp": _pf_dt.now(_pf_tz.utc).isoformat()}
    _PORTFOLIO_CACHE.setdefault(user_id, []).append(event)
    if len(_PORTFOLIO_CACHE.get(user_id, [])) > 200:
        _PORTFOLIO_CACHE[user_id] = _PORTFOLIO_CACHE[user_id][-200:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": "portfolio",
                "data": json.dumps(event),
                "entity_id": f"{user_id}_portfolio_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 149: portfolio store failed: {e}")


async def _get_portfolio_items(user_id):
    cached = _PORTFOLIO_CACHE.get(user_id, [])
    backend = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": "portfolio"})
            if resp.status_code == 200:
                for entry in resp.json().get("history", []):
                    try:
                        d = entry.get("data", "{}")
                        backend.append(json.loads(d) if isinstance(d, str) else d)
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception:
        pass
    pc_ts = {e.get("timestamp", "") for e in backend}
    return backend + [e for e in cached if e.get("timestamp", "") not in pc_ts]


@app.get("/", summary="Service information")
async def root():
    return {"service": "portfolio_service", "type": "backend",
            "domain": "document", "status": "running", "port": SERVICE_PORT,
            "version": "2.0.0-plan149", "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["portfolio_management", "work_samples", "publications",
                             "certifications", "awards"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "portfolio_service",
            "port": SERVICE_PORT, "version": "2.0.0-plan149",
            "persistence": PERSISTENCE_PROVIDER, "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "portfolio_service", "port": SERVICE_PORT,
            "uptime_seconds": time.time()}

@app.post("/portfolio/add", summary="Add portfolio item", status_code=201)
async def portfolio_add(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    category = body.get("category", "project")
    if category not in PORTFOLIO_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Valid: {PORTFOLIO_CATEGORIES}")

    item = {
        "item_id": f"pf-{int(time.time())}",
        "category": category,
        "title": body.get("title", ""),
        "description": body.get("description", ""),
        "url": body.get("url", ""),
        "date": body.get("date", ""),
        "organization": body.get("organization", ""),
        "tags": body.get("tags", []),
    }
    await _store_portfolio_event(user_id, item)
    return {"service": "portfolio_service", "endpoint": "/portfolio/add",
            "status": "created", "source": PERSISTENCE_PROVIDER,
            "data": item, "timestamp": time.time()}

@app.get("/portfolio/list", summary="List portfolio items")
async def portfolio_list(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    category = dict(request.query_params).get("category", "")
    items = await _get_portfolio_items(user_id) if user_id else []
    if category:
        items = [i for i in items if i.get("category") == category]
    by_category = {}
    for cat in PORTFOLIO_CATEGORIES:
        cat_items = [i for i in items if i.get("category") == cat]
        if cat_items:
            by_category[cat] = cat_items
    return {"service": "portfolio_service", "endpoint": "/portfolio/list",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"items": items[-50:], "total": len(items),
                     "by_category": {k: len(v) for k, v in by_category.items()},
                     "categories": PORTFOLIO_CATEGORIES},
            "timestamp": time.time()}

@app.post("/portfolio/generate-page", summary="Generate portfolio summary page")
async def portfolio_generate(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    items = await _get_portfolio_items(user_id)
    summary_sections = []
    for cat in PORTFOLIO_CATEGORIES:
        cat_items = [i for i in items if i.get("category") == cat]
        if cat_items:
            summary_sections.append({
                "category": cat,
                "count": len(cat_items),
                "highlights": [{"title": i.get("title"), "org": i.get("organization")}
                               for i in cat_items[:5]]
            })
    return {"service": "portfolio_service", "endpoint": "/portfolio/generate-page",
            "status": "ok",
            "data": {"sections": summary_sections, "total_items": len(items),
                     "categories_used": len(summary_sections)},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "portfolio_service", "error": exc.detail})

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
    if "Plan 149" in content and "portfolio" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "portfolio_service"
    if svc.exists():
        patch_service(svc)
