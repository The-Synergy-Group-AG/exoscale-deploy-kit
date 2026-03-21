#!/usr/bin/env python3
"""
_patch_subscription_wiring.py -- Plan 148: True Freemium Subscription Model

3-tier model:
  FREE:      CHF 0/mo  - 1,000 credits/month, ALL features available
  PREMIUM:   CHF 29.99/mo - Unlimited credits
  AFFILIATE: CHF 49.99/mo - Unlimited credits + commission program

Replaces Plan 143 feature-gating with credit-based access.
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

_ENDPOINTS_CODE = '''

# ── Plan 148: True Freemium Subscription Model ──────────────────────────────

import os as _sub_os
from datetime import datetime as _sub_dt, timezone as _sub_tz, timedelta as _sub_td

MEMORY_SYSTEM_URL = _sub_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009")
STRIPE_API_KEY = _sub_os.getenv("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET = _sub_os.getenv("STRIPE_WEBHOOK_SECRET", "")
CREDIT_SYSTEM_URL = _sub_os.getenv("CREDIT_SYSTEM_URL", "http://credit-system-service:8000")
GAMIFICATION_URL = _sub_os.getenv("GAMIFICATION_URL", "http://gamification-service:8000")
BASE_DOMAIN = _sub_os.getenv("BASE_DOMAIN", "https://jobtrackerpro.ch")

# Plan pricing (Plan 148: true freemium)
PLANS = {
    "free": {"name": "Free", "price_chf": 0, "interval": None,
             "credits_monthly": 1000, "features": "all", "unlimited": False},
    "premium": {"name": "Premium", "price_chf": 29.99, "interval": "month",
                "credits_monthly": "unlimited", "features": "all", "unlimited": True},
    "affiliate": {"name": "Affiliate", "price_chf": 49.99, "interval": "month",
                  "credits_monthly": "unlimited", "features": "all", "unlimited": True,
                  "commission_pct": 20},
}

# Local plan cache
_PLAN_CACHE: dict = {}  # {user_id: {plan_id, status, ...}}
# Subscription pause tracking
_PAUSE_CACHE: dict = {}  # {user_id: {paused_at, resume_at, months}}


async def _store_subscription_event(user_id, event_type, data_dict):
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{MEMORY_SYSTEM_URL}/store", json={
                "user_id": user_id, "entity_type": "subscription",
                "data": json.dumps({**data_dict, "event_type": event_type,
                                    "timestamp": _sub_dt.now(_sub_tz.utc).isoformat()}),
                "entity_id": f"{user_id}_sub_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 148: store subscription event failed: {e}")


async def _get_subscription_events(user_id):
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{MEMORY_SYSTEM_URL}/history/{user_id}",
                              params={"entity_type": "subscription"})
            if resp.status_code == 200:
                events = []
                for entry in resp.json().get("history", []):
                    try:
                        d = entry.get("data", "{}")
                        events.append(json.loads(d) if isinstance(d, str) else d)
                    except (json.JSONDecodeError, TypeError):
                        pass
                return events
    except Exception:
        pass
    return []


def _get_current_plan(user_id, events=None):
    if user_id in _PLAN_CACHE:
        return _PLAN_CACHE[user_id]
    plan = {"plan_id": "free", "plan_name": "Free", "status": "active",
            "price_chf": 0, "credits_monthly": 1000, "unlimited": False,
            "started_at": _sub_dt.now(_sub_tz.utc).isoformat(),
            "renewal_date": None, "stripe_customer_id": None,
            "stripe_subscription_id": None, "paused": False}
    if events:
        for ev in reversed(events):
            et = ev.get("event_type", "")
            if et == "plan_upgraded":
                pid = ev.get("plan_id", "premium")
                plan_def = PLANS.get(pid, PLANS["premium"])
                plan = {"plan_id": pid, "plan_name": plan_def["name"],
                        "status": "active", "price_chf": plan_def["price_chf"],
                        "credits_monthly": plan_def["credits_monthly"],
                        "unlimited": plan_def["unlimited"],
                        "started_at": ev.get("timestamp", ""),
                        "renewal_date": ev.get("renewal_date", ""),
                        "stripe_customer_id": ev.get("stripe_customer_id", ""),
                        "stripe_subscription_id": ev.get("stripe_subscription_id", ""),
                        "paused": False}
                break
            elif et == "plan_cancelled":
                plan["status"] = "cancelled"
                break
            elif et == "subscription_paused":
                plan["paused"] = True
                plan["pause_resume_at"] = ev.get("resume_at", "")
                break
            elif et == "subscription_resumed":
                plan["paused"] = False
                break
    _PLAN_CACHE[user_id] = plan
    return plan


async def _notify_credit_system(user_id, plan_id):
    """Tell credit system about plan change so it can set unlimited mode."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.post(f"{CREDIT_SYSTEM_URL}/set-plan",
                        json={"user_id": user_id, "plan": plan_id})
    except Exception:
        pass


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/", summary="Service information")
async def root():
    return {"service": "subscription_management_service", "type": "backend",
            "domain": "payment", "status": "running", "port": SERVICE_PORT,
            "version": "3.0.0-plan148",
            "model": "true_freemium",
            "pricing": {pid: {"name": p["name"], "price_chf": p["price_chf"],
                              "credits": p["credits_monthly"]}
                        for pid, p in PLANS.items()},
            "capabilities": ["plan_check", "checkout", "cancel", "pause", "resume",
                             "billing_history", "pricing"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "subscription_management_service",
            "port": SERVICE_PORT, "version": "3.0.0-plan148",
            "stripe": "configured" if STRIPE_API_KEY else "sandbox",
            "persistence": "pinecone", "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "subscription_management_service", "port": SERVICE_PORT,
            "uptime_seconds": time.time()}

@app.get("/plan", summary="Get user subscription plan")
async def get_plan(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"service": "subscription_management_service", "endpoint": "/plan",
                "data": {"plan_id": "free", "plan_name": "Free", "status": "active",
                         "price_chf": 0, "credits_monthly": 1000, "unlimited": False}}
    events = await _get_subscription_events(user_id)
    plan = _get_current_plan(user_id, events)
    return {"service": "subscription_management_service", "endpoint": "/plan",
            "status": "ok", "source": "pinecone", "data": plan,
            "timestamp": time.time()}

@app.get("/subscriptions", summary="List subscriptions (backward compat)")
async def subscriptions(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_subscription_events(user_id) if user_id else []
    plan = _get_current_plan(user_id, events) if user_id else {
        "plan_id": "free", "plan_name": "Free", "status": "active", "price_chf": 0}
    return {"service": "subscription_management_service", "endpoint": "/subscriptions",
            "status": "ok", "source": "pinecone",
            "data": {"subscriptions": [plan], "total": 1},
            "timestamp": time.time()}

@app.post("/plan/checkout", summary="Create Stripe Checkout for upgrade")
async def plan_checkout(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    plan_id = body.get("plan_id", "premium")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if plan_id not in ("premium", "affiliate"):
        raise HTTPException(status_code=400, detail="plan_id must be 'premium' or 'affiliate'")

    plan_def = PLANS[plan_id]

    if not STRIPE_API_KEY:
        # Sandbox mode
        await _store_subscription_event(user_id, "plan_upgraded", {
            "plan_id": plan_id, "amount_chf": plan_def["price_chf"],
            "stripe_customer_id": "sandbox", "stripe_subscription_id": "sandbox",
            "payment_method": "sandbox"})
        _PLAN_CACHE[user_id] = {"plan_id": plan_id, "plan_name": plan_def["name"],
                                 "status": "active", "price_chf": plan_def["price_chf"],
                                 "credits_monthly": plan_def["credits_monthly"],
                                 "unlimited": True, "paused": False}
        await _notify_credit_system(user_id, plan_id)
        return {"service": "subscription_management_service", "endpoint": "/plan/checkout",
                "status": "success", "mode": "sandbox",
                "data": {"checkout_url": f"{BASE_DOMAIN}/?subscription=success",
                         "plan_id": plan_id, "plan_name": plan_def["name"],
                         "price_chf": plan_def["price_chf"],
                         "message": f"Sandbox: upgraded to {plan_def['name']}"},
                "timestamp": time.time()}

    # Real Stripe checkout
    try:
        import stripe
        stripe.api_key = STRIPE_API_KEY
        desc = f"Unlimited credits, all features"
        if plan_id == "affiliate":
            desc += f", {plan_def.get('commission_pct', 20)}% referral commissions"
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "chf",
                    "product_data": {
                        "name": f"JobTrackerPro {plan_def['name']}",
                        "description": desc,
                    },
                    "unit_amount": int(plan_def["price_chf"] * 100),
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{BASE_DOMAIN}/?subscription=success&plan={plan_id}",
            cancel_url=f"{BASE_DOMAIN}/?subscription=cancelled",
            metadata={"user_id": user_id, "plan_id": plan_id},
        )
        return {"service": "subscription_management_service", "endpoint": "/plan/checkout",
                "status": "success", "mode": "stripe",
                "data": {"checkout_url": session.url, "session_id": session.id,
                         "plan_id": plan_id, "price_chf": plan_def["price_chf"]},
                "timestamp": time.time()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Checkout failed: {e}")

@app.post("/plan/cancel", summary="Cancel subscription")
async def plan_cancel(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    events = await _get_subscription_events(user_id)
    plan = _get_current_plan(user_id, events)
    if plan.get("plan_id") == "free":
        return {"service": "subscription_management_service", "endpoint": "/plan/cancel",
                "status": "already_free",
                "data": {"message": "You are already on the Free plan (1,000 credits/month)"},
                "timestamp": time.time()}

    # Cancel in Stripe if applicable
    stripe_sub_id = plan.get("stripe_subscription_id", "")
    if stripe_sub_id and stripe_sub_id not in ("sandbox", "mock") and STRIPE_API_KEY:
        try:
            import stripe
            stripe.api_key = STRIPE_API_KEY
            stripe.Subscription.cancel(stripe_sub_id)
        except Exception as e:
            logger.warning(f"Plan 148: Stripe cancel failed: {e}")

    await _store_subscription_event(user_id, "plan_cancelled", {
        "previous_plan": plan.get("plan_id"), "reason": body.get("reason", "user_requested")})
    _PLAN_CACHE[user_id] = {"plan_id": "free", "plan_name": "Free", "status": "cancelled",
                             "price_chf": 0, "credits_monthly": 1000, "unlimited": False,
                             "paused": False}
    await _notify_credit_system(user_id, "free")

    return {"service": "subscription_management_service", "endpoint": "/plan/cancel",
            "status": "success",
            "data": {"plan_id": "free", "message": "Subscription cancelled. "
                     "You still have 1,000 free credits/month with all features."},
            "timestamp": time.time()}

@app.post("/plan/pause", summary="Pause subscription (up to 3 months)")
async def plan_pause(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    months = min(int(body.get("months", 1)), 3)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    events = await _get_subscription_events(user_id)
    plan = _get_current_plan(user_id, events)
    if plan.get("plan_id") == "free":
        return {"status": "error", "data": {"message": "Cannot pause free plan"}}

    resume_at = (_sub_dt.now(_sub_tz.utc) + _sub_td(days=30 * months)).isoformat()
    await _store_subscription_event(user_id, "subscription_paused", {
        "months": months, "resume_at": resume_at})

    plan["paused"] = True
    plan["pause_resume_at"] = resume_at
    _PLAN_CACHE[user_id] = plan
    _PAUSE_CACHE[user_id] = {"paused_at": _sub_dt.now(_sub_tz.utc).isoformat(),
                              "resume_at": resume_at, "months": months}
    await _notify_credit_system(user_id, "free")  # Paused = free tier credits

    return {"service": "subscription_management_service", "endpoint": "/plan/pause",
            "status": "success",
            "data": {"paused": True, "months": months, "resume_at": resume_at,
                     "message": f"Subscription paused for {months} month(s). "
                                f"You'll have 1,000 free credits/month during pause."},
            "timestamp": time.time()}

@app.post("/plan/resume", summary="Resume paused subscription")
async def plan_resume(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    events = await _get_subscription_events(user_id)
    plan = _get_current_plan(user_id, events)
    if not plan.get("paused"):
        return {"status": "error", "data": {"message": "Subscription is not paused"}}

    await _store_subscription_event(user_id, "subscription_resumed", {
        "plan_id": plan.get("plan_id", "premium")})
    plan["paused"] = False
    _PLAN_CACHE[user_id] = plan
    _PAUSE_CACHE.pop(user_id, None)
    await _notify_credit_system(user_id, plan.get("plan_id", "premium"))

    return {"service": "subscription_management_service", "endpoint": "/plan/resume",
            "status": "success",
            "data": {"plan_id": plan["plan_id"], "message": "Subscription resumed. Unlimited credits restored."},
            "timestamp": time.time()}

@app.get("/pricing", summary="Get pricing information")
async def pricing(request: Request):
    return {"service": "subscription_management_service", "endpoint": "/pricing",
            "data": {
                "model": "true_freemium",
                "description": "All features available on all plans. Credits limit usage on Free plan.",
                "plans": [
                    {"id": "free", "name": "Free", "price_chf": 0,
                     "credits": "1,000/month", "features": "ALL features",
                     "highlights": ["1,000 credits/month", "All features available",
                                    "Earn more via streaks & referrals"]},
                    {"id": "premium", "name": "Premium", "price_chf": 29.99,
                     "interval": "month", "credits": "Unlimited",
                     "features": "ALL features",
                     "highlights": ["Unlimited credits", "Priority AI responses",
                                    "Can pause up to 3 months"]},
                    {"id": "affiliate", "name": "Affiliate", "price_chf": 49.99,
                     "interval": "month", "credits": "Unlimited",
                     "features": "ALL features + commissions",
                     "highlights": ["Everything in Premium", "20% commission on referral upgrades",
                                    "Affiliate dashboard", "Priority support"]},
                ],
                "credit_packs": [
                    {"credits": 500, "price_chf": 5.00},
                    {"credits": 1500, "price_chf": 14.00, "savings": "7%"},
                    {"credits": 2500, "price_chf": 22.50, "savings": "10%"},
                ],
            },
            "timestamp": time.time()}

@app.get("/billing/history", summary="Billing history")
async def billing_history(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_subscription_events(user_id) if user_id else []
    payments = [ev for ev in events if ev.get("event_type") in
                ("payment_completed", "plan_upgraded", "credit_purchased")]
    return {"service": "subscription_management_service", "endpoint": "/billing/history",
            "status": "ok", "source": "pinecone",
            "data": {"payments": payments, "total": len(payments)},
            "timestamp": time.time()}

@app.post("/webhook/stripe", summary="Stripe webhook handler")
async def stripe_webhook(request: Request):
    if not STRIPE_API_KEY:
        return {"status": "ignored", "reason": "stripe_not_configured"}
    try:
        import stripe
        stripe.api_key = STRIPE_API_KEY
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
        event_type = event.get("type", "")
        data = event.get("data", {}).get("object", {})
        user_id = data.get("metadata", {}).get("user_id", "")
        plan_id = data.get("metadata", {}).get("plan_id", "premium")

        if event_type == "checkout.session.completed" and user_id:
            # Check if this is a credit pack purchase or subscription
            pack_credits = data.get("metadata", {}).get("credits", "")
            if pack_credits:
                # Credit pack purchase
                try:
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        await c.post(f"{CREDIT_SYSTEM_URL}/earn", json={
                            "user_id": user_id, "credits": int(pack_credits),
                            "reason": "credit_pack_purchase"})
                except Exception:
                    pass
            else:
                # Subscription upgrade
                plan_def = PLANS.get(plan_id, PLANS["premium"])
                await _store_subscription_event(user_id, "plan_upgraded", {
                    "plan_id": plan_id, "amount_chf": plan_def["price_chf"],
                    "stripe_customer_id": data.get("customer", ""),
                    "stripe_subscription_id": data.get("subscription", "")})
                _PLAN_CACHE[user_id] = {"plan_id": plan_id, "plan_name": plan_def["name"],
                                         "status": "active", "price_chf": plan_def["price_chf"],
                                         "unlimited": True, "paused": False}
                await _notify_credit_system(user_id, plan_id)

        elif event_type == "customer.subscription.deleted" and user_id:
            await _store_subscription_event(user_id, "plan_cancelled", {
                "reason": "stripe_subscription_deleted"})
            _PLAN_CACHE[user_id] = {"plan_id": "free", "plan_name": "Free",
                                     "status": "cancelled", "price_chf": 0, "unlimited": False}
            await _notify_credit_system(user_id, "free")

        return {"status": "processed", "event_type": event_type}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Legacy compatibility
@app.get("/payments", summary="Payments (legacy)")
async def payments(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_subscription_events(user_id) if user_id else []
    return {"service": "subscription_management_service", "endpoint": "/payments",
            "status": "ok", "data": {"payments": events[-10:], "total": len(events)},
            "timestamp": time.time()}

@app.post("/credits/apply", summary="Credits (legacy)")
async def credits_apply(request: Request):
    return {"service": "subscription_management_service", "endpoint": "/credits/apply",
            "status": "redirect",
            "data": {"message": "Use credit-system-service /purchase for credit packs"},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "subscription_management_service", "error": exc.detail})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
'''


def patch_subscription_service(service_dir: Path) -> bool:
    import re
    for candidate in [service_dir / "src" / "main.py", service_dir / "main.py"]:
        if candidate.exists():
            main_py = candidate
            break
    else:
        return False
    content = main_py.read_text()
    if "Plan 148" in content and "true_freemium" in content:
        print(f"  SKIP: {main_py} already patched")
        return False
    app_match = re.search(r"app = FastAPI\([^)]+\)", content, re.DOTALL)
    if not app_match:
        return False
    main_py.write_text(content[:app_match.end()] + "\n" + _ENDPOINTS_CODE)
    print(f"  PATCHED: {main_py}")
    return True


if __name__ == "__main__":
    current_file = SCRIPT_DIR.parent / "engines" / "service_engine" / "outputs" / "CURRENT"
    if current_file.exists():
        gen = current_file.read_text().strip()
        svc_dir = SCRIPT_DIR.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "subscription_management_service"
        if svc_dir.exists():
            patch_subscription_service(svc_dir)
