"""Pydantic models for machine_learning_pipelines_service.
Domain: ai
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "machine_learning_pipelines_service"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "machine_learning_pipelines_service"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "machine_learning_pipelines_service"
    error: str
    status_code: int


# ── Domain models (ai) ────────────────────────────────────

class AIProcessRequest(BaseModel):
    input_data: Dict[str, Any]
    model_id: Optional[str] = None
    parameters: Dict[str, Any] = {}

class AIGenerateRequest(BaseModel):
    prompt: str
    model: str = "default"
    max_tokens: int = 1000

class AIResponse(BaseModel):
    result: Optional[Dict[str, Any]] = None
    model_used: str = "default"
    biological_harmony: float = 0.997
