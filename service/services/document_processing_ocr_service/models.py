"""Pydantic models for document_processing_ocr_service.
Domain: document
Plan 123 Phase 2 — domain-specific request/response schemas.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time


# ── Base models (all services) ────────────────────────────────────────

class ServiceResponse(BaseModel):
    service: str = "document_processing_ocr_service"
    status: str = "success"
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None

    def model_post_init(self, __context):
        if self.timestamp is None:
            self.timestamp = time.time()


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "document_processing_ocr_service"
    timestamp: Optional[float] = None
    biological_harmony: float = 0.997
    port: Optional[int] = None
    resource_tier: Optional[str] = None


class ErrorResponse(BaseModel):
    service: str = "document_processing_ocr_service"
    error: str
    status_code: int


# ── Domain models (document) ────────────────────────────────────

class ServiceRequest(BaseModel):
    data: Dict[str, Any] = {}
    user_id: Optional[str] = None

class ServiceResponse(BaseModel):
    service: str
    status: str
    result: Optional[Dict[str, Any]] = None
    biological_harmony: float = 0.997
