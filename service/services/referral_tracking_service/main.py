"""
referral_tracking_service - Backend Service

Auto-generated from template: unknown
Generated at: 1772003817.9966028
"""

import json
import logging
from fastapi import FastAPI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration
with open('config.json', 'r') as f:
    config = json.load(f)

# Create FastAPI app
app = FastAPI(
    title=f"Referral_Tracking_Service API",
    description=f"Auto-generated backend service",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "referral_tracking_service",
        "type": "backend",
        "status": "running",
        "message": f"Hello from referral_tracking_service!"
    }

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": 1772003817.996609
    }

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting referral_tracking_service service...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
