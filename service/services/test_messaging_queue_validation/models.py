"""Pydantic models for test_messaging_queue_validation.
Domain: notification
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "test_messaging_queue_validation"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "test_messaging_queue_validation"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "test_messaging_queue_validation"
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
