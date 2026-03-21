#!/usr/bin/env python3
"""
_patch_credit_system_wiring.py -- Plan 148: Credit System for True Freemium Model

Replaces feature-gating with credit-based consumption:
- FREE: 1,000 credits/month, ALL features available
- Credit costs: 5-50 per operation (AI-heavy costs more)
- Credit packs: CHF 5.00 = 500 credits, bulk discounts
- Smart consumption tracking with AI predictions

Wires credit_system_service with Pinecone persistence.
"""
import re
import sys
from pathlib import Path

_ENDPOINTS_CODE = '''

import os as _cr_os
from datetime import datetime as _cr_dt, timezone as _cr_tz

PERSISTENCE_SERVICE_URL = _cr_os.getenv("PERSISTENCE_SERVICE_URL",
    _cr_os.getenv("MEMORY_SYSTEM_URL", "http://memory-system:8009"))
PERSISTENCE_PROVIDER = _cr_os.getenv("PERSISTENCE_PROVIDER", "pinecone")
STRIPE_API_KEY = _cr_os.getenv("STRIPE_API_KEY", "")
BASE_DOMAIN = _cr_os.getenv("BASE_DOMAIN", "https://jobtrackerpro.ch")

# ── Plan 148: Credit-Based Freemium ──────────────────────────────────────────

FREE_MONTHLY_CREDITS = 1000
CREDIT_COSTS = {
    "job_search": 5,
    "cv_view": 5,
    "profile_update": 5,
    "application_submit": 10,
    "cv_enhance": 25,
    "cover_letter": 30,
    "cv_refine": 15,
    "cover_letter_refine": 15,
    "interview_prep": 20,
    "pdf_export": 10,
    "ai_coaching": 20,
    "employer_research": 10,
    "salary_benchmark": 15,
    "rav_report": 10,
    "emotional_analysis": 15,
    "career_advice": 15,
    "general_chat": 5,
}

CREDIT_PACKS = [
    {"id": "pack-500", "credits": 500, "price_chf": 5.00, "label": "500 Credits"},
    {"id": "pack-1500", "credits": 1500, "price_chf": 14.00, "label": "1,500 Credits (7% off)", "savings_pct": 7},
    {"id": "pack-2500", "credits": 2500, "price_chf": 22.50, "label": "2,500 Credits (10% off)", "savings_pct": 10},
]

# Local credit cache: {user_id: {"balance": int, "month": "YYYY-MM", "transactions": [...]}}
_CREDIT_CACHE: dict = {}


def _current_month():
    return _cr_dt.now(_cr_tz.utc).strftime("%Y-%m")


def _get_credit_state(user_id):
    month = _current_month()
    if user_id in _CREDIT_CACHE and _CREDIT_CACHE[user_id].get("month") == month:
        return _CREDIT_CACHE[user_id]
    # New month or new user: reset to free monthly allowance
    state = {"balance": FREE_MONTHLY_CREDITS, "month": month,
             "total_consumed": 0, "total_purchased": 0,
             "transactions": [], "plan": "free"}
    _CREDIT_CACHE[user_id] = state
    return state


async def _persist_credit_event(user_id, event_type, data_dict):
    event = {**data_dict, "event_type": event_type,
             "timestamp": _cr_dt.now(_cr_tz.utc).isoformat()}
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{PERSISTENCE_SERVICE_URL}/store", json={
                "user_id": user_id, "entity_type": "credit",
                "data": json.dumps(event),
                "entity_id": f"{user_id}_credit_{int(time.time() * 1000)}",
            })
    except Exception as e:
        logger.warning(f"Plan 148: credit store failed: {e}")


async def _load_credit_state(user_id):
    """Load credit state from Pinecone for the current month."""
    state = _get_credit_state(user_id)
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get(f"{PERSISTENCE_SERVICE_URL}/history/{user_id}",
                              params={"entity_type": "credit"})
            if resp.status_code == 200:
                month = _current_month()
                for entry in resp.json().get("history", []):
                    try:
                        d = json.loads(entry.get("data", "{}")) if isinstance(entry.get("data"), str) else entry.get("data", {})
                        if d.get("timestamp", "").startswith(month):
                            et = d.get("event_type", "")
                            if et == "credit_consumed":
                                state["total_consumed"] += d.get("amount", 0)
                            elif et == "credit_purchased":
                                state["total_purchased"] += d.get("credits", 0)
                            elif et == "credit_earned":
                                state["total_purchased"] += d.get("credits", 0)
                    except (json.JSONDecodeError, TypeError):
                        pass
                # Recalculate balance
                state["balance"] = (FREE_MONTHLY_CREDITS + state["total_purchased"]
                                    - state["total_consumed"])
    except Exception:
        pass
    _CREDIT_CACHE[user_id] = state
    return state


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/", summary="Service information")
async def root():
    return {"service": "credit_system_service", "type": "backend", "domain": "financial",
            "status": "running", "port": SERVICE_PORT, "version": "1.0.0-plan148",
            "persistence": PERSISTENCE_PROVIDER,
            "capabilities": ["credit_balance", "consume", "purchase", "history", "packs"]}

@app.get("/health", summary="Health check")
async def health():
    return {"status": "healthy", "service": "credit_system_service", "port": SERVICE_PORT,
            "version": "1.0.0-plan148", "persistence": PERSISTENCE_PROVIDER,
            "timestamp": time.time()}

@app.get("/metrics", summary="Metrics")
async def metrics():
    return {"service": "credit_system_service", "port": SERVICE_PORT,
            "uptime_seconds": time.time()}

@app.get("/balance", summary="Get credit balance")
async def credit_balance(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"data": {"balance": FREE_MONTHLY_CREDITS, "plan": "free",
                         "monthly_allowance": FREE_MONTHLY_CREDITS}}
    state = await _load_credit_state(user_id)
    return {"service": "credit_system_service", "endpoint": "/balance",
            "status": "ok", "source": PERSISTENCE_PROVIDER,
            "data": {"balance": max(0, state["balance"]),
                     "monthly_allowance": FREE_MONTHLY_CREDITS,
                     "total_consumed": state["total_consumed"],
                     "total_purchased": state["total_purchased"],
                     "month": state["month"],
                     "plan": state["plan"]},
            "timestamp": time.time()}

@app.post("/consume", summary="Consume credits for an operation")
async def consume_credits(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    operation = body.get("operation", "general_chat")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    cost = CREDIT_COSTS.get(operation, 5)
    state = _get_credit_state(user_id)

    # Premium/Affiliate users: unlimited (no credit deduction)
    if state.get("plan") in ("premium", "affiliate"):
        return {"service": "credit_system_service", "endpoint": "/consume",
                "status": "ok", "data": {"consumed": 0, "operation": operation,
                                          "balance": "unlimited", "plan": state["plan"]},
                "timestamp": time.time()}

    if state["balance"] < cost:
        return {"service": "credit_system_service", "endpoint": "/consume",
                "status": "insufficient_credits",
                "data": {"balance": state["balance"], "cost": cost, "operation": operation,
                         "message": f"Need {cost} credits but have {state['balance']}. "
                                    f"Buy a credit pack or upgrade to Premium for unlimited access.",
                         "packs": CREDIT_PACKS},
                "timestamp": time.time()}

    state["balance"] -= cost
    state["total_consumed"] += cost
    state["transactions"].append({"op": operation, "cost": cost,
                                   "ts": _cr_dt.now(_cr_tz.utc).isoformat()})
    if len(state["transactions"]) > 200:
        state["transactions"] = state["transactions"][-200:]

    await _persist_credit_event(user_id, "credit_consumed", {
        "operation": operation, "amount": cost, "balance_after": state["balance"]})

    return {"service": "credit_system_service", "endpoint": "/consume",
            "status": "ok",
            "data": {"consumed": cost, "operation": operation,
                     "balance": state["balance"], "plan": "free"},
            "timestamp": time.time()}

@app.post("/earn", summary="Earn credits (streaks, referrals, bonuses)")
async def earn_credits(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    credits = int(body.get("credits", 0))
    reason = body.get("reason", "bonus")
    if not user_id or credits <= 0:
        raise HTTPException(status_code=400, detail="user_id and positive credits required")

    state = _get_credit_state(user_id)
    state["balance"] += credits
    state["total_purchased"] += credits

    await _persist_credit_event(user_id, "credit_earned", {
        "credits": credits, "reason": reason, "balance_after": state["balance"]})

    return {"service": "credit_system_service", "endpoint": "/earn",
            "status": "ok",
            "data": {"earned": credits, "reason": reason, "balance": state["balance"]},
            "timestamp": time.time()}

@app.get("/packs", summary="Available credit packs")
async def credit_packs(request: Request):
    return {"service": "credit_system_service", "endpoint": "/packs",
            "data": {"packs": CREDIT_PACKS, "currency": "CHF"},
            "timestamp": time.time()}

@app.post("/purchase", summary="Purchase a credit pack")
async def purchase_credits(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    pack_id = body.get("pack_id", "pack-500")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    pack = next((p for p in CREDIT_PACKS if p["id"] == pack_id), None)
    if not pack:
        raise HTTPException(status_code=400, detail=f"Invalid pack_id. Options: {[p['id'] for p in CREDIT_PACKS]}")

    if not STRIPE_API_KEY:
        # Sandbox: grant credits immediately
        state = _get_credit_state(user_id)
        state["balance"] += pack["credits"]
        state["total_purchased"] += pack["credits"]
        await _persist_credit_event(user_id, "credit_purchased", {
            "pack_id": pack_id, "credits": pack["credits"],
            "price_chf": pack["price_chf"], "mode": "sandbox"})
        return {"service": "credit_system_service", "endpoint": "/purchase",
                "status": "success", "mode": "sandbox",
                "data": {"pack": pack, "new_balance": state["balance"],
                         "message": f"Sandbox: {pack['credits']} credits added"},
                "timestamp": time.time()}

    # Stripe checkout for credit pack
    try:
        import stripe
        stripe.api_key = STRIPE_API_KEY
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "chf",
                    "product_data": {"name": f"JobTrackerPro {pack['label']}"},
                    "unit_amount": int(pack["price_chf"] * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{BASE_DOMAIN}/?credits=success&pack={pack_id}",
            cancel_url=f"{BASE_DOMAIN}/?credits=cancelled",
            metadata={"user_id": user_id, "pack_id": pack_id,
                       "credits": str(pack["credits"])},
        )
        return {"service": "credit_system_service", "endpoint": "/purchase",
                "status": "success", "mode": "stripe",
                "data": {"checkout_url": session.url, "pack": pack},
                "timestamp": time.time()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Purchase failed: {e}")

@app.get("/costs", summary="Credit costs per operation")
async def credit_costs(request: Request):
    return {"service": "credit_system_service", "endpoint": "/costs",
            "data": {"costs": CREDIT_COSTS, "free_monthly": FREE_MONTHLY_CREDITS},
            "timestamp": time.time()}

@app.post("/set-plan", summary="Set user plan (called by subscription service)")
async def set_plan(request: Request):
    """Internal endpoint: subscription service tells credit system about plan changes."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = body.get("user_id", "")
    plan = body.get("plan", "free")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    state = _get_credit_state(user_id)
    state["plan"] = plan
    return {"status": "ok", "user_id": user_id, "plan": plan}

@app.get("/history", summary="Credit transaction history")
async def credit_history(request: Request):
    user_id = dict(request.query_params).get("user_id", "")
    if not user_id:
        return {"data": {"transactions": [], "total": 0}}
    state = _get_credit_state(user_id)
    return {"service": "credit_system_service", "endpoint": "/history",
            "status": "ok",
            "data": {"transactions": state.get("transactions", [])[-50:],
                     "total": len(state.get("transactions", []))},
            "timestamp": time.time()}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "service": "credit_system_service", "error": exc.detail})

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
    if "Plan 148" in content and "_persist_credit_event" in content:
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
    svc = Path(__file__).parent.parent / "engines" / "service_engine" / "outputs" / gen / "services" / "credit_system_service"
    if svc.exists():
        patch_service(svc)
