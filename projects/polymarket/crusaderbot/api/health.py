"""Health + readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Response

from ..cache import ping_cache
from ..database import ping

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "crusaderbot"}


@router.get("/ready")
async def ready(response: Response):
    db_ok = await ping()
    cache_ok = await ping_cache()
    ok = db_ok and cache_ok
    response.status_code = 200 if ok else 503
    return {"db": db_ok, "cache": cache_ok, "ready": ok}
