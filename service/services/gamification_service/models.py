"""Pydantic models for gamification_service.
Domain: gamification
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "gamification_service"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "gamification_service"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "gamification_service"
    error: str
    status_code: int


# ── Domain models (gamification) ────────────────────────────────────

class AwardPointsRequest(BaseModel):
    user_id: str
    points: int
    reason: str
    badge_id: Optional[str] = None

class GamificationResponse(BaseModel):
    user_id: str
    total_points: int
    level: int = 1
    biological_harmony: float = 0.997
