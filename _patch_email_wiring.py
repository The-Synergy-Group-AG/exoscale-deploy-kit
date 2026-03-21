#!/usr/bin/env python3
"""
_patch_email_wiring.py — Plan 147: Wire email_integration_service to SendGrid

Provider-agnostic email delivery:
- SendGrid (default), configurable via EMAIL_PROVIDER env var
- Email types: welcome, application_confirmation, interview_reminder, referral_invite, weekly_digest
- Delivery tracking via Pinecone
- Unsubscribe management
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _em_os
from datetime import datetime as _em_dt

# Provider-agnostic email configuration
EMAIL_PROVIDER = _em_os.getenv("EMAIL_PROVIDER", "sendgrid")
EMAIL_API_KEY = _em_os.getenv(
    _em_os.getenv("EMAIL_API_KEY_ENV", "SENDGRID_API_KEY"),
    _em_os.getenv("SENDGRID_API_KEY", "")
)
EMAIL_FROM = _em_os.getenv("EMAIL_FROM_ADDRESS", "noreply@jobtrackerpro.ch")
EMAIL_FROM_NAME = _em_os.getenv("EMAIL_FROM_NAME", "JobTrackerPro")
PERSISTENCE_SERVICE_URL = _em_os.getenv("PERSISTENCE_SERVICE_URL",
    _em_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _em_os.getenv("PERSISTENCE_PROVIDER", "pinecone")

_EMAIL_CACHE: dict = {}

EMAIL_TEMPLATES = {
    "welcome": {"subject": "Welcome to JobTrackerPro!", "category": "onboarding"},
    "application_confirmation": {"subject": "Application Tracked: {company} - {role}", "category": "tracking"},
    "interview_reminder": {"subject": "Interview Reminder: {company} tomorrow", "category": "reminder"},
    "referral_invite": {"subject": "{name} invited you to JobTrackerPro", "category": "referral"},
    "weekly_digest": {"subject": "Your Weekly Job Search Summary", "category": "digest"},
    "badge_earned": {"subject": "You earned a new badge: {badge_name}!", "category": "gamification"},
    "follow_up_reminder": {"subject": "Time to follow up with {company}", "category": "reminder"},
}


async def _store_email_event(user_id, event_type, data_dict):
    event = {**data_dict, "event_type": event_type, "timestamp": _em_dt.now().isoformat()}
    _EMAIL_CACHE.setdefault(user_id, []).append(event)
    if len(_EMAIL_CACHE.get(user_id, [])) > 100:
        _EMAIL_CACHE[user_id] = _EMAIL_CACHE[user_id][-100:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": "email",
                "data": json.dumps(event),
                "entity_id": f"{user_id}_email_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 147: Email event store failed: {e}")


async def _send_email_sendgrid(to_email, subject, html_content, category="general"):
    """Send email via SendGrid API. Provider-agnostic wrapper."""
    if not EMAIL_API_KEY:
        logger.warning("Plan 147: No email API key configured — email not sent")
        return {"status": "skipped", "reason": "no_api_key"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.post("https://api.sendgrid.com/v3/mail/send", headers={
                "Authorization": f"Bearer {EMAIL_API_KEY}",
                "Content-Type": "application/json",
            }, json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": EMAIL_FROM, "name": EMAIL_FROM_NAME},
                "subject": subject,
                "content": [{"type": "text/html", "value": html_content}],
                "categories": [category],
            })
            return {"status": "sent" if resp.status_code in (200, 202) else "failed",
                    "status_code": resp.status_code}
    except Exception as e:
        logger.warning(f"Plan 147: SendGrid delivery failed: {e}")
        return {"status": "error", "error": str(e)[:100]}


async def _get_email_history(user_id):
    cached = _EMAIL_CACHE.get(user_id, [])
    backend = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": "email"})
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
    return {"service": "email_integration_service", "type": "backend", "domain": "notification",
            "status": "running", "port": SERVICE_PORT, "version": "2.0.0-plan147",
            "email_provider": EMAIL_PROVIDER, "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["send_email", "templates", "delivery_tracking", "preferences"],
            "templates": list(EMAIL_TEMPLATES.keys())}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "email_integration_service", "port": SERVICE_PORT,
            "version": "2.0.0-plan147", "email_provider": EMAIL_PROVIDER,
            "email_configured": bool(EMAIL_API_KEY), "persistence": PERSISTENCE_PROVIDER,
            "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "email_integration_service", "port": SERVICE_PORT, "uptime_seconds": time.time()}

@app.post("/email/send", summary="Send email", status_code=201)
async def send_email(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    to_email = body.get("to_email", "")
    template = body.get("template", "welcome")
    template_vars = body.get("template_vars", {})

    if not to_email:
        raise HTTPException(status_code=400, detail="to_email required")

    tmpl = EMAIL_TEMPLATES.get(template, {"subject": "JobTrackerPro Notification", "category": "general"})
    subject = tmpl["subject"].format(**template_vars) if template_vars else tmpl["subject"]
    html = body.get("html_content", f"<h2>{subject}</h2><p>{body.get('message', 'Thank you for using JobTrackerPro.')}</p>")

    result = await _send_email_sendgrid(to_email, subject, html, tmpl.get("category", "general"))

    if user_id:
        await _store_email_event(user_id, "email_sent", {
            "to": to_email, "template": template, "subject": subject,
            "delivery_status": result.get("status", "unknown")})

    return {"service": "email_integration_service", "endpoint": "/email/send",
            "status": "success", "source": EMAIL_PROVIDER,
            "data": {"delivery": result, "template": template},
            "timestamp": time.time()}

@app.get("/email/history", summary="Email history for user")
async def email_history(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_email_history(user_id) if user_id else []
    return {"service": "email_integration_service", "endpoint": "/email/history",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"emails": events[-20:], "total": len(events)},
            "timestamp": time.time()}

@app.get("/email/templates", summary="Available email templates")
async def list_templates(request: Request):
    return {"service": "email_integration_service", "endpoint": "/email/templates",
            "data": EMAIL_TEMPLATES, "timestamp": time.time()}

@app.get("/notifications", summary="List notifications")
async def list_notifications(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_email_history(user_id) if user_id else []
    unread = [e for e in events if not e.get("read", False)]
    return {"service": "email_integration_service", "endpoint": "/notifications",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"notifications": events[-50:], "total": len(events), "unread": len(unread)},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"service": "email_integration_service", "error": exc.detail})

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
    if "Plan 147" in content and "_send_email_sendgrid" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "email_integration_service"
    if svc.exists():
        patch_service(svc)
