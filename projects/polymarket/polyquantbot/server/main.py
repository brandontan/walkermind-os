"""CrusaderBot — FastAPI control-plane runtime.

Primary Fly.io-facing HTTP surface.
Binds to the PORT env variable injected by Fly.io.

Endpoints:
    GET /health   — deterministic liveness check (always 200 when process is up)
    GET /ready    — readiness check (503 if required env vars are missing)

Startup: env validation is performed by the entry script (scripts/run_api.py)
before uvicorn starts, so this module is a pure FastAPI application object.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    _repo_root = Path(__file__).resolve().parents[4]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

import structlog
from fastapi import FastAPI

from projects.polymarket.polyquantbot.server.api.health import router as health_router

log = structlog.get_logger(__name__)

CRUSADERBOT_VERSION = "7.7.0"

app = FastAPI(
    title="CrusaderBot",
    description="Polymarket autonomous trading platform — CrusaderBot control plane",
    version=CRUSADERBOT_VERSION,
    docs_url="/docs",
    redoc_url=None,
)

app.include_router(health_router)

log.info("crusaderbot_app_created", app="CrusaderBot", version=CRUSADERBOT_VERSION)
