"""CrusaderBot FastAPI control-plane runtime."""
from __future__ import annotations

import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from projects.polymarket.polyquantbot.server.api.client_auth_routes import build_client_auth_router
from projects.polymarket.polyquantbot.server.api.multi_user_foundation_routes import build_multi_user_router
from projects.polymarket.polyquantbot.server.api.public_beta_routes import build_public_beta_router
from projects.polymarket.polyquantbot.server.api.routes import build_router
from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
from projects.polymarket.polyquantbot.server.core.runtime import (
    ApiSettings,
    RuntimeState,
    run_shutdown,
    run_startup_validation,
    telegram_runtime_required_from_env,
)
from projects.polymarket.polyquantbot.server.core.sentry_runtime import (
    capture_runtime_exception,
    initialize_sentry,
)
from projects.polymarket.polyquantbot.client.telegram.backend_client import CrusaderBackendClient
from projects.polymarket.polyquantbot.client.telegram.bot import TelegramBotSettings, validate_bot_environment
from projects.polymarket.polyquantbot.client.telegram.dispatcher import TelegramDispatcher
from projects.polymarket.polyquantbot.client.telegram.runtime import HttpTelegramAdapter, run_polling_loop
from projects.polymarket.polyquantbot.server.services.account_service import AccountService
from projects.polymarket.polyquantbot.server.services.auth_session_service import AuthSessionService
from projects.polymarket.polyquantbot.server.services.telegram_activation_service import TelegramActivationService
from projects.polymarket.polyquantbot.server.services.telegram_identity_service import TelegramIdentityService
from projects.polymarket.polyquantbot.server.services.telegram_onboarding_service import TelegramOnboardingService
from projects.polymarket.polyquantbot.server.services.telegram_session_issuance_service import (
    TelegramSessionIssuanceService,
)
from projects.polymarket.polyquantbot.server.services.user_service import UserService
from projects.polymarket.polyquantbot.server.services.wallet_link_service import WalletLinkService
from projects.polymarket.polyquantbot.server.services.wallet_service import WalletService
from projects.polymarket.polyquantbot.server.services.wallet_lifecycle_service import WalletLifecycleService
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import FalconGateway
from projects.polymarket.polyquantbot.server.storage.multi_user_store import PersistentMultiUserStore
from projects.polymarket.polyquantbot.server.storage.session_store import PersistentSessionStore
from projects.polymarket.polyquantbot.server.storage.wallet_link_store import PersistentWalletLinkStore
from projects.polymarket.polyquantbot.server.storage.wallet_lifecycle_store import WalletLifecycleStore
from projects.polymarket.polyquantbot.server.storage.portfolio_store import PortfolioStore
from projects.polymarket.polyquantbot.server.services.portfolio_service import PortfolioService
from projects.polymarket.polyquantbot.server.api.portfolio_routes import build_portfolio_router
from projects.polymarket.polyquantbot.server.api.orchestration_routes import build_orchestration_router
from projects.polymarket.polyquantbot.server.orchestration.cross_wallet_aggregator import CrossWalletStateAggregator
from projects.polymarket.polyquantbot.server.orchestration.decision_store import OrchestrationDecisionStore
from projects.polymarket.polyquantbot.server.orchestration.wallet_controls import WalletControlsStore
from projects.polymarket.polyquantbot.server.orchestration.wallet_orchestrator import WalletOrchestrator
from projects.polymarket.polyquantbot.server.services.orchestration_service import OrchestratorService
from projects.polymarket.polyquantbot.server.settlement.settlement_persistence import SettlementPersistence
from projects.polymarket.polyquantbot.server.settlement.settlement_alert_policy import SettlementAlertPolicy
from projects.polymarket.polyquantbot.server.settlement.operator_console import OperatorConsole
from projects.polymarket.polyquantbot.server.services.settlement_operator_service import SettlementOperatorService
from projects.polymarket.polyquantbot.server.api.settlement_operator_routes import build_settlement_operator_router
from projects.polymarket.polyquantbot.server.storage.capital_mode_confirmation_store import (
    CapitalModeConfirmationStore,
)
from projects.polymarket.polyquantbot.infra.db import DatabaseClient

log = structlog.get_logger(__name__)


def _sanitize_runtime_error(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    secret_markers = ("token", "secret", "password", "dsn", "api_key", "apikey")
    if any(marker in lowered for marker in secret_markers):
        return "sensitive_runtime_error_redacted"
    if len(raw) > 240:
        return f"{raw[:240]}..."
    return raw


def _runtime_monitoring_snapshot(state: RuntimeState) -> dict[str, object]:
    return {
        "lifecycle_phase": state.lifecycle_phase,
        "lifecycle_transitions_total": state.lifecycle_transitions_total,
        "dependency_failures_total": state.dependency_failures_total,
        "last_dependency_failure_surface": state.last_dependency_failure_surface,
        "telegram_runtime": {
            "required": state.telegram_runtime_required,
            "enabled": state.telegram_runtime_enabled,
            "active": state.telegram_runtime_active,
            "shutdown_complete": state.telegram_runtime_shutdown_complete,
            "last_error_present": bool(state.telegram_runtime_last_error),
        },
        "db_runtime": {
            "required": state.db_runtime_required,
            "enabled": state.db_runtime_enabled,
            "connected": state.db_runtime_connected,
            "healthcheck_ok": state.db_runtime_healthcheck_ok,
            "last_error_present": bool(state.db_runtime_last_error),
        },
    }


def _transition_runtime_phase(state: RuntimeState, phase: str) -> None:
    state.lifecycle_phase = phase
    state.lifecycle_transitions_total += 1


def _record_dependency_failure(state: RuntimeState, surface: str, error: str) -> None:
    state.dependency_failures_total += 1
    state.last_dependency_failure_surface = surface
    state.last_dependency_failure_error = _sanitize_runtime_error(error)


class RuntimeTelegramObserver:
    def __init__(self, state: RuntimeState) -> None:
        self._state = state

    def on_startup(self) -> None:
        self._state.telegram_runtime_startup_complete = True
        self._state.telegram_runtime_active = True
        self._state.telegram_runtime_shutdown_complete = False
        self._state.telegram_runtime_last_error = ""
        log.info("crusaderbot_telegram_runtime_started")

    def on_iteration(self, processed_count: int) -> None:
        self._state.telegram_runtime_iterations_total += processed_count

    def on_reply_sent(self) -> None:
        log.info("crusaderbot_telegram_reply_sent")

    def on_error(self, error: str) -> None:
        sanitized_error = _sanitize_runtime_error(error)
        self._state.telegram_runtime_last_error = sanitized_error
        log.error("crusaderbot_telegram_runtime_error", error=sanitized_error)

    def on_shutdown(self) -> None:
        self._state.telegram_runtime_active = False
        self._state.telegram_runtime_shutdown_complete = True
        log.info("crusaderbot_telegram_runtime_stopped")


def _reset_runtime_state_for_startup(state: RuntimeState) -> None:
    _transition_runtime_phase(state=state, phase="startup_reset")
    state.validation_errors = []
    state.telegram_runtime_startup_complete = False
    state.telegram_runtime_active = False
    state.telegram_runtime_shutdown_complete = False
    state.telegram_runtime_last_error = ""
    state.telegram_runtime_task = None
    state.db_runtime_connected = False
    state.db_runtime_healthcheck_ok = False
    state.db_runtime_last_error = ""
    state.db_client = None
    state.last_dependency_failure_surface = ""
    state.last_dependency_failure_error = ""
    log.info("crusaderbot_runtime_transition", transition="startup_reset", monitoring=_runtime_monitoring_snapshot(state))


async def _start_telegram_runtime(state: RuntimeState) -> None:
    _transition_runtime_phase(state=state, phase="telegram_startup")
    log.info("crusaderbot_runtime_transition", transition="telegram_startup", monitoring=_runtime_monitoring_snapshot(state))
    settings = TelegramBotSettings.from_env()
    validation_errors = validate_bot_environment(settings)
    raw_validation_error = "; ".join(validation_errors)
    state.telegram_runtime_required = telegram_runtime_required_from_env()
    state.telegram_runtime_enabled = not validation_errors
    if validation_errors:
        state.telegram_runtime_last_error = _sanitize_runtime_error(raw_validation_error)
        _record_dependency_failure(
            state=state,
            surface="telegram_runtime_startup",
            error=state.telegram_runtime_last_error,
        )
        log.error(
            "crusaderbot_telegram_runtime_disabled",
            required=state.telegram_runtime_required,
            errors=validation_errors,
            failure_surface="telegram_runtime_startup",
        )
        if state.telegram_runtime_required:
            raise RuntimeError(raw_validation_error)
        return

    backend = CrusaderBackendClient(
        base_url=settings.backend_base_url,
        identity_tenant_id=settings.staging_tenant_id,
    )
    dispatcher = TelegramDispatcher(
        backend=backend,
        operator_chat_id=settings.telegram_chat_id,
    )
    if not settings.telegram_chat_id:
        log.warning(
            "crusaderbot_telegram_operator_chat_guard_disabled",
            reason="missing_TELEGRAM_CHAT_ID",
            internal_command_surface="blocked_for_public_runtime",
        )
    adapter = HttpTelegramAdapter(token=settings.telegram_token)
    observer = RuntimeTelegramObserver(state=state)
    state.telegram_runtime_task = asyncio.create_task(
        run_polling_loop(
            adapter=adapter,
            dispatcher=dispatcher,
            identity_resolver=backend,
            onboarding_initiator=backend,
            activation_confirmer=backend,
            session_issuer=backend,
            staging_tenant_id=settings.staging_tenant_id,
            staging_user_id=settings.staging_user_id,
            observer=observer,
        )
    )
    log.info(
        "crusaderbot_telegram_runtime_bootstrap_ready",
        backend_base_url=settings.backend_base_url,
        chat_id_configured=bool(settings.telegram_chat_id),
        required=state.telegram_runtime_required,
    )


async def _shutdown_telegram_runtime(state: RuntimeState, timeout_s: float = 5.0) -> None:
    _transition_runtime_phase(state=state, phase="telegram_shutdown")
    log.info("crusaderbot_runtime_transition", transition="telegram_shutdown", monitoring=_runtime_monitoring_snapshot(state))
    task = state.telegram_runtime_task
    if task is None:
        state.telegram_runtime_active = False
        state.telegram_runtime_shutdown_complete = True
        return

    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=timeout_s)
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        state.telegram_runtime_last_error = "telegram_shutdown_timeout"
        _record_dependency_failure(state=state, surface="telegram_runtime_shutdown", error=state.telegram_runtime_last_error)
        log.error("crusaderbot_telegram_runtime_shutdown_timeout", timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001
        state.telegram_runtime_last_error = str(exc)
        _record_dependency_failure(state=state, surface="telegram_runtime_shutdown", error=state.telegram_runtime_last_error)
        log.error("crusaderbot_telegram_runtime_shutdown_error", error=state.telegram_runtime_last_error)
    finally:
        state.telegram_runtime_task = None
        state.telegram_runtime_active = False
        state.telegram_runtime_shutdown_complete = True


def _db_runtime_required_from_env() -> bool:
    raw = os.getenv("CRUSADER_DB_RUNTIME_REQUIRED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _db_runtime_enabled_from_env() -> bool:
    raw = os.getenv("CRUSADER_DB_RUNTIME_ENABLED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _db_retry_budget_s(max_attempts: int, base_backoff_s: float, per_attempt_timeout_s: float = 10.0) -> float:
    if max_attempts < 1:
        raise RuntimeError("CRUSADER_DB_CONNECT_MAX_ATTEMPTS must be >= 1.")
    if base_backoff_s < 0:
        raise RuntimeError("CRUSADER_DB_CONNECT_BASE_BACKOFF_S must be >= 0.")
    backoff_total = sum(base_backoff_s * (2 ** attempt) for attempt in range(max_attempts - 1))
    return (max_attempts * per_attempt_timeout_s) + backoff_total


async def _start_database_runtime(state: RuntimeState) -> None:
    _transition_runtime_phase(state=state, phase="db_startup")
    log.info("crusaderbot_runtime_transition", transition="db_startup", monitoring=_runtime_monitoring_snapshot(state))
    state.db_runtime_required = _db_runtime_required_from_env()
    state.db_runtime_enabled = _db_runtime_enabled_from_env()
    state.db_runtime_last_error = ""
    state.db_runtime_connected = False
    state.db_runtime_healthcheck_ok = False

    if not state.db_runtime_enabled:
        return

    max_attempts = int(os.getenv("CRUSADER_DB_CONNECT_MAX_ATTEMPTS", "4").strip() or "4")
    base_backoff_s = float(os.getenv("CRUSADER_DB_CONNECT_BASE_BACKOFF_S", "1.0").strip() or "1.0")
    configured_timeout_s = float(os.getenv("CRUSADER_DB_CONNECT_TIMEOUT_S", "30.0").strip() or "30.0")
    retry_budget_s = _db_retry_budget_s(max_attempts=max_attempts, base_backoff_s=base_backoff_s)
    timeout_s = max(configured_timeout_s, retry_budget_s + 1.0)

    state.db_connect_max_attempts = max_attempts
    state.db_connect_base_backoff_s = base_backoff_s
    state.db_connect_timeout_s = timeout_s
    db_client = DatabaseClient()
    state.db_client = db_client

    if timeout_s > configured_timeout_s:
        log.warning(
            "crusaderbot_db_connect_timeout_adjusted",
            configured_timeout_s=configured_timeout_s,
            adjusted_timeout_s=timeout_s,
            retry_budget_s=retry_budget_s,
        )

    try:
        await asyncio.wait_for(
            db_client.connect_with_retry(max_attempts=max_attempts, base_backoff_s=base_backoff_s),
            timeout=timeout_s,
        )
        state.db_runtime_connected = True
        state.db_runtime_healthcheck_ok = await db_client.healthcheck()
        if not state.db_runtime_healthcheck_ok:
            raise RuntimeError("Database healthcheck failed after startup connect path.")
        log.info("crusaderbot_db_runtime_ready")
    except Exception as exc:
        state.db_runtime_last_error = _sanitize_runtime_error(str(exc))
        _record_dependency_failure(
            state=state,
            surface="db_runtime_startup",
            error=state.db_runtime_last_error,
        )
        state.db_runtime_connected = False
        state.db_runtime_healthcheck_ok = False
        if state.db_client is not None:
            await state.db_client.close()
            state.db_client = None
        log.error(
            "crusaderbot_db_runtime_startup_failed",
            required=state.db_runtime_required,
            error=state.db_runtime_last_error,
            failure_surface="db_runtime_startup",
        )
        if state.db_runtime_required:
            raise


async def _stop_database_runtime(state: RuntimeState) -> None:
    _transition_runtime_phase(state=state, phase="db_shutdown")
    log.info("crusaderbot_runtime_transition", transition="db_shutdown", monitoring=_runtime_monitoring_snapshot(state))
    if state.db_client is None:
        return
    close_attempts = 2
    for attempt in range(1, close_attempts + 1):
        try:
            await state.db_client.close()
            state.db_client = None
            state.db_runtime_connected = False
            state.db_runtime_healthcheck_ok = False
            return
        except Exception as exc:  # noqa: BLE001
            state.db_runtime_last_error = _sanitize_runtime_error(
                f"db_close_attempt_{attempt}_failed: {exc}"
            )
            _record_dependency_failure(
                state=state,
                surface="db_runtime_shutdown",
                error=state.db_runtime_last_error,
            )
            log.warning(
                "crusaderbot_db_runtime_shutdown_retry",
                attempt=attempt,
                max_attempts=close_attempts,
                error=state.db_runtime_last_error,
            )
            if attempt < close_attempts:
                await asyncio.sleep(0.05)
    state.db_client = None
    state.db_runtime_connected = False
    state.db_runtime_healthcheck_ok = False


async def _shutdown_runtime_components(state: RuntimeState) -> None:
    _transition_runtime_phase(state=state, phase="shutdown_begin")
    log.info("crusaderbot_runtime_transition", transition="shutdown_begin", monitoring=_runtime_monitoring_snapshot(state))
    await _shutdown_telegram_runtime(state=state)
    await _stop_database_runtime(state=state)
    _transition_runtime_phase(state=state, phase="shutdown_complete")
    log.info("crusaderbot_runtime_transition", transition="shutdown_complete", monitoring=_runtime_monitoring_snapshot(state))


def create_app() -> FastAPI:
    initialize_sentry()
    settings = ApiSettings.from_env()
    falcon_settings = FalconSettings.from_env()
    state = RuntimeState()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            _transition_runtime_phase(state=state, phase="startup_begin")
            log.info("crusaderbot_runtime_transition", transition="startup_begin", monitoring=_runtime_monitoring_snapshot(state))
            _reset_runtime_state_for_startup(state)
            _transition_runtime_phase(state=state, phase="startup_validation")
            log.info(
                "crusaderbot_runtime_transition",
                transition="startup_validation",
                monitoring=_runtime_monitoring_snapshot(state),
            )
            await run_startup_validation(settings=settings, state=state)
            await _start_database_runtime(state=state)
            # P4: wire wallet lifecycle service after DB is connected
            if state.db_client is not None:
                _wlc_store = WalletLifecycleStore(db=state.db_client)
                _app.state.wallet_lifecycle_store = _wlc_store
                _app.state.wallet_lifecycle_service = WalletLifecycleService(store=_wlc_store)
                log.info("wallet_lifecycle_service_wired")
            # P5: wire portfolio service after DB is connected
            if state.db_client is not None:
                _portfolio_store = PortfolioStore(db=state.db_client)
                _app.state.portfolio_store = _portfolio_store
                _app.state.portfolio_service = PortfolioService(store=_portfolio_store)
                log.info("portfolio_service_wired")
            # P6 Phase C: wire orchestration service after DB is connected
            if state.db_client is not None:
                _wlc_store_for_orch = getattr(_app.state, "wallet_lifecycle_store", None)
                if _wlc_store_for_orch is None:
                    _wlc_store_for_orch = WalletLifecycleStore(db=state.db_client)
                _controls_store = WalletControlsStore()
                _decision_store = OrchestrationDecisionStore(db=state.db_client)
                _orchestration_svc = OrchestratorService(
                    lifecycle_store=_wlc_store_for_orch,
                    controls_store=_controls_store,
                    decision_store=_decision_store,
                    aggregator=CrossWalletStateAggregator(),
                    orchestrator=WalletOrchestrator(),
                    db=state.db_client,
                )
                _app.state.orchestration_service = _orchestration_svc
                await _orchestration_svc.load_controls_from_db("system", "paper_user")
                log.info("orchestration_service_wired")
            # P7: wire settlement operator service after DB is connected
            if state.db_client is not None:
                _settlement_persistence = SettlementPersistence(db=state.db_client)
                _settlement_alert_policy = SettlementAlertPolicy()
                _operator_console = OperatorConsole(alert_policy=_settlement_alert_policy)
                _app.state.settlement_operator_service = SettlementOperatorService(
                    persistence=_settlement_persistence,
                    console=_operator_console,
                )
                log.info("settlement_operator_service_wired")
            # P8-E: wire capital-mode confirmation store after DB is connected
            if state.db_client is not None:
                _app.state.capital_mode_confirmation_store = (
                    CapitalModeConfirmationStore(db=state.db_client)
                )
                log.info("capital_mode_confirmation_store_wired")
            try:
                await _start_telegram_runtime(state=state)
            except Exception as exc:
                capture_runtime_exception(exc, surface="telegram_runtime_startup")
                raise
            _transition_runtime_phase(state=state, phase="runtime_ready")
            log.info("crusaderbot_runtime_transition", transition="runtime_ready", monitoring=_runtime_monitoring_snapshot(state))
            yield
        finally:
            await _shutdown_runtime_components(state=state)
            await run_shutdown(state=state)
            _transition_runtime_phase(state=state, phase="stopped")
            log.info("crusaderbot_runtime_transition", transition="stopped", monitoring=_runtime_monitoring_snapshot(state))

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.crusader_settings = settings
    app.state.crusader_runtime = state
    app.state.falcon_settings = falcon_settings

    multi_user_storage_path = Path(
        os.getenv(
            "CRUSADER_MULTI_USER_STORAGE_PATH",
            "/tmp/crusaderbot/runtime/multi_user.json",
        )
    )
    store = PersistentMultiUserStore(storage_path=multi_user_storage_path)
    user_service = UserService(store=store)
    account_service = AccountService(store=store)
    wallet_service = WalletService(store=store)
    telegram_identity_service = TelegramIdentityService(user_service=user_service)
    telegram_onboarding_service = TelegramOnboardingService(user_service=user_service)
    telegram_activation_service = TelegramActivationService(user_service=user_service)

    session_storage_path = Path(
        os.getenv(
            "CRUSADER_SESSION_STORAGE_PATH",
            "/tmp/crusaderbot/runtime/foundation_sessions.json",
        )
    )
    persistent_session_store = PersistentSessionStore(storage_path=session_storage_path)
    auth_session_service = AuthSessionService(store=store, session_store=persistent_session_store)
    telegram_session_issuance_service = TelegramSessionIssuanceService(
        user_service=user_service,
        auth_session_service=auth_session_service,
    )

    wallet_link_storage_path = Path(
        os.getenv(
            "CRUSADER_WALLET_LINK_STORAGE_PATH",
            "/tmp/crusaderbot/runtime/wallet_links.json",
        )
    )
    wallet_link_store = PersistentWalletLinkStore(storage_path=wallet_link_storage_path)
    wallet_link_service = WalletLinkService(store=wallet_link_store)

    app.state.multi_user_storage_path = multi_user_storage_path
    app.state.multi_user_store = store
    app.state.telegram_identity_service = telegram_identity_service
    app.state.telegram_onboarding_service = telegram_onboarding_service
    app.state.telegram_activation_service = telegram_activation_service
    app.state.telegram_session_issuance_service = telegram_session_issuance_service
    app.state.persistent_session_store = persistent_session_store
    app.state.user_service = user_service
    app.state.account_service = account_service
    app.state.wallet_service = wallet_service
    app.state.auth_session_service = auth_session_service
    app.state.wallet_link_storage_path = wallet_link_storage_path
    app.state.wallet_link_store = wallet_link_store
    app.state.wallet_link_service = wallet_link_service
    # P4 lifecycle service is wired in lifespan after DB connects — see lifespan below

    falcon_gateway = FalconGateway(settings=falcon_settings)
    router = build_router(settings=settings, state=state, falcon_settings=falcon_settings)
    app.include_router(router)
    app.include_router(
        build_multi_user_router(
            user_service=user_service,
            account_service=account_service,
            wallet_service=wallet_service,
            auth_session_service=auth_session_service,
        )
    )
    app.include_router(
        build_client_auth_router(
            auth_session_service=auth_session_service,
            wallet_link_service=wallet_link_service,
            telegram_identity_service=telegram_identity_service,
            telegram_onboarding_service=telegram_onboarding_service,
            telegram_activation_service=telegram_activation_service,
            telegram_session_issuance_service=telegram_session_issuance_service,
        )
    )

    app.include_router(build_public_beta_router(falcon=falcon_gateway))
    app.include_router(build_portfolio_router())
    app.include_router(build_orchestration_router())
    app.include_router(build_settlement_operator_router())

    @app.get("/")
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": settings.app_name,
                "status": "ok",
                "docs": "/docs",
            }
        )

    log.info(
        "crusaderbot_api_app_created",
        runtime="server.main",
        port=settings.port,
        trading_mode=settings.trading_mode,
        falcon_enabled=falcon_settings.enabled,
        falcon_key_configured=falcon_settings.api_key_configured(),
        multi_user_storage_path=str(multi_user_storage_path),
        session_storage_path=str(session_storage_path),
        wallet_link_storage_path=str(wallet_link_storage_path),
        phase="8.6-public-paper-beta-confidence-pass",
    )
    return app


app = create_app()


def main() -> None:
    settings: ApiSettings = app.state.crusader_settings
    uvicorn.run(
        "projects.polymarket.polyquantbot.server.main:app",
        host=settings.host,
        port=settings.port,
        factory=False,
    )


if __name__ == "__main__":
    main()
