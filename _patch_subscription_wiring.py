#!/usr/bin/env python3
"""
_patch_subscription_wiring.py — Plan 143: Wire subscription_management_service

Replaces mock endpoints with real Pinecone-backed plan management +
Stripe integration (sandbox mode).

Pricing: Free tier + Premium (CHF 29/mo)
Persistence: Pinecone via memory-system:8009
Payment: Stripe Checkout (sandbox first, then live)
XP Offset: 100 XP points = 1 CHF credit against subscription
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

_ENDPOINTS_CODE = '''

# ── Plan 143: Subscription Management with Pinecone + Stripe ────────────────

import os as _sub_os
from datetime import datetime as _sub_dt

MEMORY_SYSTEM_URL = _sub_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009")
STRIPE_API_KEY = _sub_os.getenv("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET = _sub_os.getenv("STRIPE_WEBHOOK_SECRET", "")
GAMIFICATION_URL = _sub_os.getenv("GAMIFICATION_URL", "http://gamification-service:8000")
BASE_DOMAIN = _sub_os.getenv("BASE_DOMAIN", "https://jobtrackerpro.ch")

# Plan pricing
PREMIUM_PRICE_CHF = 29.00
PREMIUM_PLAN_NAME = "Premium"
FREE_PLAN_NAME = "Free"
XP_TO_CHF_RATE = 100  # 100 XP = 1 CHF

# Local plan cache (instant consistency, same pattern as gamification)
_PLAN_CACHE: dict = {}  # {user_id: {plan, status, ...}}


async def _store_subscription_event(user_id, event_type, data_dict):
    """Store subscription event to Pinecone via memory-system."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{MEMORY_SYSTEM_URL}/store", json={
                "user_id": user_id, "entity_type": "subscription",
                "data": json.dumps({**data_dict, "event_type": event_type,
                                    "timestamp": _sub_dt.now().isoformat()}),
                "entity_id": f"{user_id}_sub_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 143: store subscription event failed: {e}")


async def _get_subscription_events(user_id):
    """Fetch subscription events from Pinecone."""
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
    except Exception as e:
        logger.warning(f"Plan 143: fetch subscription events failed: {e}")
    return []


def _get_current_plan(user_id, events=None):
    """Determine current plan from cache or events."""
    # Check cache first
    if user_id in _PLAN_CACHE:
        return _PLAN_CACHE[user_id]

    # Default free plan
    plan = {"plan": FREE_PLAN_NAME, "status": "active", "amount_chf": 0,
            "started_at": _sub_dt.now().isoformat(), "renewal_date": None,
            "stripe_customer_id": None, "stripe_subscription_id": None,
            "xp_credit_chf": 0}

    if not events:
        return plan

    # Find latest plan event
    for ev in reversed(events):
        et = ev.get("event_type", "")
        if et == "plan_upgraded":
            plan = {"plan": PREMIUM_PLAN_NAME, "status": "active",
                    "amount_chf": PREMIUM_PRICE_CHF,
                    "started_at": ev.get("timestamp", ""),
                    "renewal_date": ev.get("renewal_date", ""),
                    "stripe_customer_id": ev.get("stripe_customer_id", ""),
                    "stripe_subscription_id": ev.get("stripe_subscription_id", ""),
                    "xp_credit_chf": ev.get("xp_credit_chf", 0)}
            break
        elif et == "plan_cancelled":
            plan["plan"] = FREE_PLAN_NAME
            plan["status"] = "cancelled"
            break

    _PLAN_CACHE[user_id] = plan
    return plan


async def _get_user_xp_credit(user_id):
    """Get available XP credit in CHF from gamification service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            resp = await c.get(f"{GAMIFICATION_URL}/points", params={"user_id": user_id})
            if resp.status_code == 200:
                balance = resp.json().get("data", {}).get("points_balance", 0)
                return balance / XP_TO_CHF_RATE  # 100 XP = 1 CHF
    except Exception:
        pass
    return 0.0


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/", summary="Service information")
async def root():
    return {"service": "subscription_management_service", "type": "backend",
            "domain": "payment", "status": "running", "port": SERVICE_PORT,
            "version": "2.0.0-plan143",
            "pricing": {"free": {"name": FREE_PLAN_NAME, "price_chf": 0},
                        "premium": {"name": PREMIUM_PLAN_NAME, "price_chf": PREMIUM_PRICE_CHF}},
            "capabilities": ["plan_check", "checkout", "cancel", "billing_history", "xp_offset"]}

@app.get("/health", summary="Health check")
async def health():
    stripe_configured = bool(STRIPE_API_KEY)
    return {"status": "healthy", "service": "subscription_management_service",
            "port": SERVICE_PORT, "version": "2.0.0-plan143",
            "stripe": "configured" if stripe_configured else "not_configured",
            "persistence": "pinecone", "timestamp": time.time()}

@app.get("/metrics", summary="Prometheus metrics")
async def metrics():
    return {"service": "subscription_management_service", "port": SERVICE_PORT,
            "uptime_seconds": time.time(), "requests_total": 0}

@app.get("/plan", summary="Get user subscription plan")
async def get_plan(request: Request):
    """Get current subscription plan for a user."""
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"service": "subscription_management_service", "endpoint": "/plan",
                "data": {"plan": FREE_PLAN_NAME, "status": "active", "amount_chf": 0},
                "timestamp": time.time()}

    events = await _get_subscription_events(user_id)
    plan = _get_current_plan(user_id, events)
    xp_credit = await _get_user_xp_credit(user_id)
    plan["xp_credit_chf"] = round(xp_credit, 2)
    plan["effective_charge"] = round(max(0, plan["amount_chf"] - xp_credit), 2)

    return {"service": "subscription_management_service", "endpoint": "/plan",
            "status": "ok", "source": "pinecone",
            "data": plan, "timestamp": time.time()}

@app.get("/subscriptions", summary="List active subscriptions")
async def subscriptions(request: Request):
    """List user subscriptions (backward compatible)."""
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_subscription_events(user_id) if user_id else []
    plan = _get_current_plan(user_id, events) if user_id else {
        "plan": FREE_PLAN_NAME, "status": "active", "amount_chf": 0}

    return {"service": "subscription_management_service", "endpoint": "/subscriptions",
            "status": "ok", "source": "pinecone",
            "data": {"subscriptions": [
                {"id": f"sub-{user_id[:8]}" if user_id else "sub-anon",
                 "plan": plan.get("plan", FREE_PLAN_NAME),
                 "status": plan.get("status", "active"),
                 "renewal_date": plan.get("renewal_date", ""),
                 "amount_chf": plan.get("amount_chf", 0)}
            ], "total": 1},
            "timestamp": time.time()}

@app.post("/plan/checkout", summary="Create Stripe Checkout session", status_code=200)
async def plan_checkout(request: Request):
    """Create a Stripe Checkout session for Premium upgrade."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    if not STRIPE_API_KEY:
        # Sandbox mode without Stripe — return mock checkout
        await _store_subscription_event(user_id, "plan_upgraded", {
            "plan": PREMIUM_PLAN_NAME, "amount_chf": PREMIUM_PRICE_CHF,
            "renewal_date": "", "stripe_customer_id": "mock",
            "stripe_subscription_id": "mock", "payment_method": "sandbox"})
        _PLAN_CACHE[user_id] = {"plan": PREMIUM_PLAN_NAME, "status": "active",
                                 "amount_chf": PREMIUM_PRICE_CHF}
        return {"service": "subscription_management_service", "endpoint": "/plan/checkout",
                "status": "success", "mode": "sandbox",
                "data": {"checkout_url": f"{BASE_DOMAIN}/?subscription=success",
                         "plan": PREMIUM_PLAN_NAME, "amount_chf": PREMIUM_PRICE_CHF,
                         "message": "Sandbox mode — plan upgraded without payment"},
                "timestamp": time.time()}

    # Real Stripe checkout
    try:
        import stripe
        stripe.api_key = STRIPE_API_KEY

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "chf",
                    "product_data": {
                        "name": f"JobTrackerPro {PREMIUM_PLAN_NAME}",
                        "description": "Unlimited job searches, CV enhancement, AI coaching, PDF export",
                    },
                    "unit_amount": int(PREMIUM_PRICE_CHF * 100),  # Stripe uses cents
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{BASE_DOMAIN}/?subscription=success",
            cancel_url=f"{BASE_DOMAIN}/?subscription=cancelled",
            metadata={"user_id": user_id},
        )

        return {"service": "subscription_management_service", "endpoint": "/plan/checkout",
                "status": "success", "mode": "stripe",
                "data": {"checkout_url": session.url, "session_id": session.id,
                         "plan": PREMIUM_PLAN_NAME, "amount_chf": PREMIUM_PRICE_CHF},
                "timestamp": time.time()}

    except Exception as e:
        logger.error(f"Plan 143: Stripe checkout failed: {e}")
        raise HTTPException(status_code=500, detail=f"Checkout failed: {e}")

@app.post("/plan/cancel", summary="Cancel subscription")
async def plan_cancel(request: Request):
    """Cancel user subscription."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    events = await _get_subscription_events(user_id)
    plan = _get_current_plan(user_id, events)

    if plan.get("plan") == FREE_PLAN_NAME:
        return {"service": "subscription_management_service", "endpoint": "/plan/cancel",
                "status": "already_free",
                "data": {"message": "You are already on the Free plan"},
                "timestamp": time.time()}

    # Cancel in Stripe if applicable
    stripe_sub_id = plan.get("stripe_subscription_id", "")
    if stripe_sub_id and stripe_sub_id != "mock" and STRIPE_API_KEY:
        try:
            import stripe
            stripe.api_key = STRIPE_API_KEY
            stripe.Subscription.cancel(stripe_sub_id)
        except Exception as e:
            logger.warning(f"Plan 143: Stripe cancel failed: {e}")

    # Store cancellation event
    await _store_subscription_event(user_id, "plan_cancelled", {
        "previous_plan": PREMIUM_PLAN_NAME, "reason": body.get("reason", "user_requested")})
    _PLAN_CACHE[user_id] = {"plan": FREE_PLAN_NAME, "status": "cancelled", "amount_chf": 0}

    return {"service": "subscription_management_service", "endpoint": "/plan/cancel",
            "status": "success",
            "data": {"plan": FREE_PLAN_NAME, "message": "Subscription cancelled. You can re-subscribe anytime."},
            "timestamp": time.time()}

@app.get("/billing/history", summary="Billing history")
async def billing_history(request: Request):
    """Get user billing history."""
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_subscription_events(user_id) if user_id else []
    payments = [ev for ev in events if ev.get("event_type") in ("payment_completed", "plan_upgraded")]
    return {"service": "subscription_management_service", "endpoint": "/billing/history",
            "status": "ok", "source": "pinecone",
            "data": {"payments": payments, "total": len(payments)},
            "timestamp": time.time()}

@app.get("/pricing", summary="Get pricing information")
async def pricing(request: Request):
    """Return plan pricing details."""
    return {"service": "subscription_management_service", "endpoint": "/pricing",
            "data": {
                "plans": [
                    {"name": FREE_PLAN_NAME, "price_chf": 0, "interval": None,
                     "features": ["5 job searches/day", "CV analysis (read-only)",
                                  "Basic AI chat", "XP & badges", "Leaderboard"]},
                    {"name": PREMIUM_PLAN_NAME, "price_chf": PREMIUM_PRICE_CHF, "interval": "month",
                     "features": ["Unlimited job searches", "CV enhancement (3 versions)",
                                  "PDF export (CV + cover letter)", "AIDA cover letters",
                                  "Full AI coaching (12 benefits)", "XP offset against fee",
                                  "Priority AI responses"]},
                ],
                "xp_offset_rate": f"{XP_TO_CHF_RATE} XP = 1 CHF",
            },
            "timestamp": time.time()}

@app.post("/webhook/stripe", summary="Stripe webhook handler")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
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

        if event_type == "checkout.session.completed" and user_id:
            await _store_subscription_event(user_id, "plan_upgraded", {
                "plan": PREMIUM_PLAN_NAME, "amount_chf": PREMIUM_PRICE_CHF,
                "stripe_customer_id": data.get("customer", ""),
                "stripe_subscription_id": data.get("subscription", ""),
                "payment_method": "stripe"})
            _PLAN_CACHE[user_id] = {"plan": PREMIUM_PLAN_NAME, "status": "active",
                                     "amount_chf": PREMIUM_PRICE_CHF}
            logger.info(f"Plan 143: User {user_id} upgraded to Premium via Stripe")

        elif event_type == "invoice.paid" and user_id:
            await _store_subscription_event(user_id, "payment_completed", {
                "amount_chf": data.get("amount_paid", 0) / 100,
                "invoice_id": data.get("id", "")})

        elif event_type == "customer.subscription.deleted" and user_id:
            await _store_subscription_event(user_id, "plan_cancelled", {
                "reason": "stripe_subscription_deleted"})
            _PLAN_CACHE[user_id] = {"plan": FREE_PLAN_NAME, "status": "cancelled", "amount_chf": 0}

        return {"status": "processed", "event_type": event_type}

    except Exception as e:
        logger.error(f"Plan 143: Stripe webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# Keep legacy endpoints for backward compatibility
@app.get("/payments", summary="List payment records (legacy)")
async def payments(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    events = await _get_subscription_events(user_id) if user_id else []
    payment_events = [ev for ev in events if "payment" in ev.get("event_type", "")]
    if not payment_events:
        payment_events = [{"id": "none", "amount": 0, "status": "no_payments"}]
    return {"service": "subscription_management_service", "endpoint": "/payments",
            "status": "ok", "source": "pinecone",
            "data": {"payments": payment_events, "total": len(payment_events)},
            "timestamp": time.time()}

@app.post("/payments/process", summary="Process payment (legacy)", status_code=201)
async def payments_process(request: Request):
    return {"service": "subscription_management_service", "endpoint": "/payments/process",
            "status": "redirect", "data": {"message": "Use /plan/checkout for subscription payments"},
            "timestamp": time.time()}

@app.post("/billing/invoice", summary="Generate invoice (legacy)", status_code=201)
async def billing_invoice(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    return {"service": "subscription_management_service", "endpoint": "/billing/invoice",
            "status": "ok",
            "data": {"invoice_id": f"inv-{int(time.time())}", "status": "generated",
                     "amount_chf": PREMIUM_PRICE_CHF, "plan": PREMIUM_PLAN_NAME},
            "timestamp": time.time()}

@app.post("/credits/apply", summary="Apply credits (legacy)", status_code=201)
async def credits_apply(request: Request):
    return {"service": "subscription_management_service", "endpoint": "/credits/apply",
            "status": "redirect",
            "data": {"message": "Use gamification-service /points/redeem for credit conversion"},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "subscription_management_service", "error": exc.detail})

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting subscription_management_service (Plan 143) port=%d", SERVICE_PORT)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
'''


def patch_subscription_service(service_dir: Path) -> bool:
    """Patch subscription_management_service with Pinecone + Stripe."""
    import re
    for candidate in [service_dir / "src" / "main.py", service_dir / "main.py"]:
        if candidate.exists():
            main_py = candidate
            break
    else:
        print(f"  SKIP: main.py not found in {service_dir}")
        return False

    content = main_py.read_text()

    if "Plan 143" in content and "_store_subscription_event" in content:
        print(f"  SKIP: {main_py} already patched")
        return False

    app_match = re.search(r"app = FastAPI\([^)]+\)", content, re.DOTALL)
    if not app_match:
        print(f"  ERROR: Could not find FastAPI app definition")
        return False

    header = content[:app_match.end()]
    new_content = header + "\n" + _ENDPOINTS_CODE
    main_py.write_text(new_content)
    print(f"  PATCHED: {main_py} ({len(new_content)} bytes)")
    return True


if __name__ == "__main__":
    current_file = SCRIPT_DIR.parent / "engines" / "service_engine" / "outputs" / "CURRENT"
    if current_file.exists():
        gen = current_file.read_text().strip()
        svc_dir = SCRIPT_DIR.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "subscription_management_service"
        if svc_dir.exists():
            patch_subscription_service(svc_dir)
        else:
            print(f"subscription_management_service not found in {gen}")
    else:
        print("No CURRENT pointer found")
