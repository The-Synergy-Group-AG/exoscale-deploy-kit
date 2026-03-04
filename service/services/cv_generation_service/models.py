"""Pydantic models for cv_generation_service.
Domain: career
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "cv_generation_service"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "cv_generation_service"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "cv_generation_service"
    error: str
    status_code: int


# ── Domain models (career) ────────────────────────────────────

class JobSearchRequest(BaseModel):
    query: str
    location: Optional[str] = None
    domain: Optional[str] = None
    limit: int = 20

class CVGenerateRequest(BaseModel):
    user_id: str
    template: str = "standard"
    language: str = "en"

class CareerResponse(BaseModel):
    results: list = []
    total: int = 0
    biological_harmony: float = 0.997
