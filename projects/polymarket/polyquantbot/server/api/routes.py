"""FastAPI routes for the CrusaderBot control plane."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from projects.polymarket.polyquantbot.server.core.runtime import ApiSettings, RuntimeState


def build_router(settings: ApiSettings, state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": settings.app_name,
            "runtime": "server.main",
            "ready": state.ready,
        }

    @router.get("/ready")
    async def ready() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ready" if state.ready else "not_ready",
                "service": settings.app_name,
                "validation_errors": state.validation_errors,
            },
            status_code=200 if state.ready else 503,
        )

    return router
