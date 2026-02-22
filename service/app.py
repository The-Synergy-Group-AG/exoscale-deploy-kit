#!/usr/bin/env python3
"""
Sample Web Service — Exoscale Deploy Kit
=========================================
A minimal Flask web service to demonstrate the Exoscale Deploy Kit pipeline.
Replace with your own application code.

Endpoints:
  GET /                          — Service info + status
  GET /health                    — Health check (used by K8s probes)
  GET /api/v1/info               — Generic service information
"""
import os
import socket
import time
from datetime import datetime
from flask import Flask, jsonify, request
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVICE_NAME = os.getenv("SERVICE_NAME", "my-service")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
BUILD_TIME = os.getenv("BUILD_TIME", datetime.now().isoformat())

_start_time = time.time()


@app.route("/")
def home():
    """Service information endpoint."""
    return jsonify({
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "hostname": socket.gethostname(),
        "timestamp": datetime.now().isoformat(),
        "status": "healthy",
        "message": "Service is running!",
    })


@app.route("/health")
def health():
    """Health check — used by Kubernetes readiness and liveness probes."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": round(time.time() - _start_time, 1),
    })


@app.route("/api/v1/info")
def api_info():
    """Generic service information endpoint."""
    return jsonify({
        "service": {
            "name": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "environment": ENVIRONMENT,
            "build_time": BUILD_TIME,
            "hostname": socket.gethostname(),
        },
        "request": {
            "method": request.method,
            "path": request.path,
            "user_agent": request.headers.get("User-Agent", "unknown"),
        },
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting {SERVICE_NAME} on {host}:{port}")
    logger.info("Endpoints: / | /health | /api/v1/info")

    app.run(host=host, port=port, debug=False)
