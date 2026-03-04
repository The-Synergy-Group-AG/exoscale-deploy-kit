"""Pydantic models for neural_network_validation_service.
Domain: monitoring
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "neural_network_validation_service"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "neural_network_validation_service"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "neural_network_validation_service"
    error: str
    status_code: int


# ── Domain models (monitoring) ────────────────────────────────────

class AlertCreateRequest(BaseModel):
    alert_name: str
    severity: str = "medium"
    threshold: Optional[float] = None
    service: Optional[str] = None

class MetricsResponse(BaseModel):
    metrics: Dict[str, Any] = {}
    timestamp: float = 0.0
    biological_harmony: float = 0.997
