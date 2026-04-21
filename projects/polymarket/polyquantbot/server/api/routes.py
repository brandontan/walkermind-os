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
        falcon_api_key_configured = falcon_settings.api_key_configured()
        execution_ready_for_paper_entries = (
            beta_state.mode == "paper"
            and beta_state.autotrade_enabled
            and not beta_state.kill_switch
        )
        worker_prerequisites = {
            "paper_mode_enforced": beta_state.mode == "paper",
            "autotrade_enabled": beta_state.autotrade_enabled,
            "kill_switch_enabled": beta_state.kill_switch,
            "execution_ready_for_paper_entries": execution_ready_for_paper_entries,
        }
        telegram_runtime_ready = (
            state.telegram_runtime_startup_complete and state.telegram_runtime_active
        )
        telegram_readiness_ok = telegram_runtime_ready if state.telegram_runtime_required else True
        ready_dimensions = {
            "scope": {
                "contract_version": "phase8-6-public-paper-beta-confidence-pass",
                "runtime_assertion": "local_runtime_only",
                "worker_state_visibility": "in_process_state_snapshot",
                "external_dependencies_probed": False,
                "external_dependencies_note": "falcon_and_telegram_apis_not_health_probed_in_ready",
            },
            "api_boot_complete": state.ready,
            "worker_runtime": {
                "startup_complete": beta_state.worker_runtime.startup_complete,
                "active": beta_state.worker_runtime.active,
                "shutdown_complete": beta_state.worker_runtime.shutdown_complete,
                "iterations_total": beta_state.worker_runtime.iterations_total,
                "last_iteration_visible": beta_state.worker_runtime.iterations_total > 0,
                "last_error": beta_state.worker_runtime.last_error,
            },
            "telegram_runtime": {
                "required": state.telegram_runtime_required,
                "enabled": state.telegram_runtime_enabled,
                "startup_complete": state.telegram_runtime_startup_complete,
                "active": state.telegram_runtime_active,
                "shutdown_complete": state.telegram_runtime_shutdown_complete,
                "iterations_total": state.telegram_runtime_iterations_total,
                "last_iteration_visible": state.telegram_runtime_iterations_total > 0,
                "last_error": state.telegram_runtime_last_error,
            },
            "worker_prerequisites": worker_prerequisites,
            "falcon_config_state": {
                "enabled": falcon_settings.enabled,
                "api_key_configured": falcon_api_key_configured,
                "enabled_without_api_key": falcon_settings.enabled and not falcon_api_key_configured,
                "config_valid_for_enabled_mode": (not falcon_settings.enabled)
                or falcon_api_key_configured,
                "candidate_source_contract": "placeholder_bounded_narrow_integration",
            },
            "control_plane": {
                "trading_mode_env": settings.trading_mode,
                "beta_mode_state": beta_state.mode,
                "autotrade_enabled": beta_state.autotrade_enabled,
                "kill_switch_enabled": beta_state.kill_switch,
                "live_mode_execution_allowed": False,
                "paper_only_execution_boundary": True,
            },
        }
        return JSONResponse(
            {
                "status": "ready" if state.ready and telegram_readiness_ok else "not_ready",
                "service": settings.app_name,
                "validation_errors": state.validation_errors,
                "readiness": ready_dimensions,
            },
            status_code=200 if state.ready and telegram_readiness_ok else 503,
        )

    return router
