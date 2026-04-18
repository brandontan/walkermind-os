"""CrusaderBot — health and readiness router."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

CRUSADERBOT_VERSION = "7.7.0"

_REQUIRED_DEPLOY_ENV: list[str] = ["DB_DSN"]


@router.get("/health")
async def health() -> dict[str, Any]:
    """/health — deterministic liveness check for Fly.io."""
    return {
        "status": "ok",
        "app": "CrusaderBot",
        "version": CRUSADERBOT_VERSION,
    }


@router.get("/ready")
async def ready() -> JSONResponse:
    """/ready — validates deploy-critical env vars are present."""
    missing = [v for v in _REQUIRED_DEPLOY_ENV if not os.environ.get(v)]
    if missing:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "app": "CrusaderBot",
                "missing_env": missing,
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "status": "ready",
            "app": "CrusaderBot",
            "version": CRUSADERBOT_VERSION,
        },
    )
