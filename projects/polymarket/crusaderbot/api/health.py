"""Health and readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from ..cache import cache
from ..config import settings
from ..database import db

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": settings.APP_ENV}


@router.get("/ready")
async def ready() -> dict:
    db_ok = await db.ping()
    cache_ok = await cache.ping()
    return {
        "ready": db_ok and cache_ok,
        "db": db_ok,
        "cache": cache_ok,
        "live_trading": settings.ENABLE_LIVE_TRADING,
        "paper_mode": not settings.ENABLE_LIVE_TRADING,
    }
