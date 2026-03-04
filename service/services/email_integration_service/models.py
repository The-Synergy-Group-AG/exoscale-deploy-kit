"""Pydantic models for email_integration_service.
Domain: notification
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "email_integration_service"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "email_integration_service"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "email_integration_service"
    error: str
    status_code: int


# ── Domain models (notification) ────────────────────────────────────

class SendNotificationRequest(BaseModel):
    recipient: str
    message: str
    channel: str = "email"
    priority: str = "normal"

class NotificationResponse(BaseModel):
    notification_id: str
    status: str
    delivered: bool = False
    biological_harmony: float = 0.997
