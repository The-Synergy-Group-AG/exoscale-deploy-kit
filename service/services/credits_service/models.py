"""Pydantic models for credits_service.
Domain: payment
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "credits_service"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "credits_service"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "credits_service"
    error: str
    status_code: int


# ── Domain models (payment) ────────────────────────────────────

class ChargeRequest(BaseModel):
    amount: float
    currency: str = "CHF"
    user_id: str
    description: Optional[str] = None

class PaymentResponse(BaseModel):
    transaction_id: str
    status: str
    amount: float
    currency: str
    biological_harmony: float = 0.997
