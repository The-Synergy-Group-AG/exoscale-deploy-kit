"""Pydantic models for secure_messaging_gateway_communication.
Domain: security
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "secure_messaging_gateway_communication"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "secure_messaging_gateway_communication"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "secure_messaging_gateway_communication"
    error: str
    status_code: int


# ── Domain models (security) ────────────────────────────────────

class ScanRequest(BaseModel):
    target: str
    scan_type: str = "full"
    severity_threshold: str = "medium"

class ThreatResponse(BaseModel):
    threat_id: str
    severity: str
    description: str
    mitigated: bool = False
    biological_harmony: float = 0.997
