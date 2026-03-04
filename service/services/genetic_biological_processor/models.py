"""Pydantic models for genetic_biological_processor.
Domain: authentication
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "genetic_biological_processor"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "genetic_biological_processor"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "genetic_biological_processor"
    error: str
    status_code: int


# ── Domain models (authentication) ────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str
    mfa_token: Optional[str] = None

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int = 3600
    user_id: str
    biological_harmony: float = 0.997

class AuthStatusResponse(BaseModel):
    service: str
    authenticated: bool
    user_id: Optional[str] = None
    template: Optional[str] = None
