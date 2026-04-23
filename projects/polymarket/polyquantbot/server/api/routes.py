"""FastAPI routes for the CrusaderBot control plane."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState, STATE
from projects.polymarket.polyquantbot.server.core.runtime import ApiSettings, RuntimeState


def _dependency_failure_category(raw_error: str) -> str:
    if not raw_error:
        return "none"
    lowered = raw_error.lower()
    if "timeout" in lowered:
        return "timeout"
    if "healthcheck" in lowered:
        return "healthcheck_failed"
    if "refused" in lowered or "unavailable" in lowered:
        return "connection_failed"
    return "runtime_error"


def _public_error_view(raw_error: str, reference: str) -> dict[str, str | bool]:
    category = _dependency_failure_category(raw_error)
    return {
        "error_present": bool(raw_error),
        "error_category": category,
        "error_reference": reference if raw_error else "",
    }


def build_router(
    settings: ApiSettings,
    state: RuntimeState,
    falcon_settings: FalconSettings,
    beta_state: PublicBetaState = STATE,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> JSONResponse:
        payload = {
            "status": "ok" if state.ready else "degraded",
            "service": settings.app_name,
            "runtime": "server.main",
            "ready": state.ready,
        }
        return JSONResponse(payload, status_code=200 if state.ready else 503)

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
        telegram_runtime_relevant = state.telegram_runtime_required or state.telegram_runtime_enabled
        telegram_readiness_ok = telegram_runtime_ready if telegram_runtime_relevant else True
        db_runtime_ready = state.db_runtime_connected and state.db_runtime_healthcheck_ok
        db_runtime_relevant = state.db_runtime_required or state.db_runtime_enabled
        db_readiness_ok = db_runtime_ready if db_runtime_relevant else True
        falcon_config_ready = (not falcon_settings.enabled) or falcon_api_key_configured
        overall_ready = state.ready and telegram_readiness_ok and db_readiness_ok and falcon_config_ready
        ready_dimensions = {
            "scope": {
                "contract_version": "phase8-6-public-paper-beta-confidence-pass",
                "runtime_assertion": "local_runtime_only",
                "worker_state_visibility": "in_process_state_snapshot",
                "external_dependencies_probed": True,
                "external_dependencies_note": "db_runtime_healthcheck_probed_during_startup_and_ready",
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
                "relevant": telegram_runtime_relevant,
                "required": state.telegram_runtime_required,
                "enabled": state.telegram_runtime_enabled,
                "startup_complete": state.telegram_runtime_startup_complete,
                "active": state.telegram_runtime_active,
                "shutdown_complete": state.telegram_runtime_shutdown_complete,
                "iterations_total": state.telegram_runtime_iterations_total,
                "last_iteration_visible": state.telegram_runtime_iterations_total > 0,
                **_public_error_view(
                    raw_error=state.telegram_runtime_last_error,
                    reference="telegram_runtime",
                ),
            },
            "db_runtime": {
                "relevant": db_runtime_relevant,
                "required": state.db_runtime_required,
                "enabled": state.db_runtime_enabled,
                "connected": state.db_runtime_connected,
                "healthcheck_ok": state.db_runtime_healthcheck_ok,
                "connect_max_attempts": state.db_connect_max_attempts,
                "connect_base_backoff_s": state.db_connect_base_backoff_s,
                "connect_timeout_s": state.db_connect_timeout_s,
                **_public_error_view(
                    raw_error=state.db_runtime_last_error,
                    reference="db_runtime",
                ),
            },
            "worker_prerequisites": worker_prerequisites,
            "falcon_config_state": {
                "enabled": falcon_settings.enabled,
                "api_key_configured": falcon_api_key_configured,
                "enabled_without_api_key": falcon_settings.enabled and not falcon_api_key_configured,
                "config_valid_for_enabled_mode": falcon_config_ready,
                "candidate_source_contract": "placeholder_bounded_narrow_integration",
            },
            "dependency_gates": {
                "api_boot_complete": state.ready,
                "telegram_runtime_ready": telegram_readiness_ok,
                "db_runtime_ready": db_readiness_ok,
                "falcon_config_ready": falcon_config_ready,
            },
            "control_plane": {
                "trading_mode_env": settings.trading_mode,
                "beta_mode_state": beta_state.mode,
                "autotrade_enabled": beta_state.autotrade_enabled,
                "kill_switch_enabled": beta_state.kill_switch,
                "live_mode_execution_allowed": False,
                "paper_only_execution_boundary": True,
            },
            "monitoring_outputs": {
                "lifecycle_phase": state.lifecycle_phase,
                "lifecycle_transitions_total": state.lifecycle_transitions_total,
                "dependency_failures_total": state.dependency_failures_total,
                "failure_present": bool(state.last_dependency_failure_error),
                "last_dependency_failure_category": _dependency_failure_category(
                    state.last_dependency_failure_error
                ),
                "last_dependency_failure_surface": state.last_dependency_failure_surface,
                "operator_trace_contract": "startup_shutdown_dependency_monitoring_minimum_v1",
            },
        }
        return JSONResponse(
            {
                "status": "ready" if overall_ready else "not_ready",
                "service": settings.app_name,
                "validation_errors": state.validation_errors,
                "readiness": ready_dimensions,
            },
            status_code=200 if overall_ready else 503,
        )

    return router
