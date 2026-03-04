"""Pydantic models for reproductive_system_biological.
Domain: biological
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "reproductive_system_biological"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "reproductive_system_biological"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "reproductive_system_biological"
    error: str
    status_code: int


# ── Domain models (biological) ────────────────────────────────────

class HarmonyRequest(BaseModel):
    service_id: str
    target_harmony: float = 0.997
    biological_system: Optional[str] = None

class ConsciousnessResponse(BaseModel):
    level: str
    harmony_score: float
    biological_system: str
    biological_harmony: float = 0.997
