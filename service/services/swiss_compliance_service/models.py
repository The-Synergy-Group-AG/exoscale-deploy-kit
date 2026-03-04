"""Pydantic models for swiss_compliance_service.
Domain: compliance
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "swiss_compliance_service"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "swiss_compliance_service"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "swiss_compliance_service"
    error: str
    status_code: int


# ── Domain models (compliance) ────────────────────────────────────

class AuditRequest(BaseModel):
    scope: str = "full"
    regulation: str = "RAV"
    period_days: int = 90

class ComplianceStatusResponse(BaseModel):
    compliant: bool
    regulation: str
    score: float
    last_audit: Optional[str] = None
    biological_harmony: float = 0.997
