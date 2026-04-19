"""FastAPI routes for the CrusaderBot control plane."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState, STATE
from projects.polymarket.polyquantbot.server.core.runtime import ApiSettings, RuntimeState


def build_router(
    settings: ApiSettings,
    state: RuntimeState,
    falcon_settings: FalconSettings,
    beta_state: PublicBetaState = STATE,
) -> APIRouter:
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
        falcon_api_key_configured = bool(falcon_settings.api_key.strip())
        worker_prerequisites = {
            "paper_mode_enforced": beta_state.mode == "paper",
            "autotrade_enabled": beta_state.autotrade_enabled,
            "kill_switch_enabled": beta_state.kill_switch,
        }
        ready_dimensions = {
            "api_boot_complete": state.ready,
            "worker_runtime": {
                "startup_complete": beta_state.worker_runtime.startup_complete,
                "active": beta_state.worker_runtime.active,
                "shutdown_complete": beta_state.worker_runtime.shutdown_complete,
                "iterations_total": beta_state.worker_runtime.iterations_total,
                "last_error": beta_state.worker_runtime.last_error,
            },
            "worker_prerequisites": worker_prerequisites,
            "falcon_config_state": {
                "enabled": falcon_settings.enabled,
                "api_key_configured": falcon_api_key_configured,
                "candidate_source_contract": "placeholder_bounded_narrow_integration",
            },
            "control_plane": {
                "trading_mode_env": settings.trading_mode,
                "beta_mode_state": beta_state.mode,
                "paper_only_execution_boundary": True,
            },
        }
        return JSONResponse(
            {
                "status": "ready" if state.ready else "not_ready",
                "service": settings.app_name,
                "validation_errors": state.validation_errors,
                "readiness": ready_dimensions,
            },
            status_code=200 if state.ready else 503,
        )

    return router
