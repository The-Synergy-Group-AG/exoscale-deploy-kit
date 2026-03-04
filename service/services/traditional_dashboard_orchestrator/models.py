"""Pydantic models for traditional_dashboard_orchestrator.
Domain: analytics
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "traditional_dashboard_orchestrator"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "traditional_dashboard_orchestrator"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "traditional_dashboard_orchestrator"
    error: str
    status_code: int


# ── Domain models (analytics) ────────────────────────────────────

class TrackEventRequest(BaseModel):
    event_name: str
    user_id: Optional[str] = None
    properties: Dict[str, Any] = {}
    timestamp: Optional[float] = None

class AnalyticsResponse(BaseModel):
    event_id: str
    accepted: bool
    processed_at: float
