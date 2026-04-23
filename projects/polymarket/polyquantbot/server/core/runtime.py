"""Runtime configuration and lifecycle helpers for CrusaderBot surfaces."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ApiSettings:
    app_name: str = "CrusaderBot"
    host: str = "0.0.0.0"
    port: int = 8080
    environment: str = "development"
    startup_mode: str = "strict"
    trading_mode: str = "PAPER"

    @classmethod
    def from_env(cls) -> "ApiSettings":
        raw_port = os.getenv("PORT", "8080").strip() or "8080"
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise RuntimeError(f"Invalid PORT value: {raw_port!r}") from exc

        if port <= 0:
            raise RuntimeError(f"PORT must be greater than zero: {port}")

        environment = os.getenv("APP_ENV", "development").strip() or "development"
        startup_mode = os.getenv("CRUSADER_STARTUP_MODE", "strict").strip().lower() or "strict"
        if startup_mode != "strict":
            raise RuntimeError(
                "CRUSADER_STARTUP_MODE must be 'strict' for the current runtime contract."
            )

        trading_mode = os.getenv("TRADING_MODE", "PAPER").strip().upper() or "PAPER"
        if trading_mode not in {"PAPER", "LIVE"}:
            raise RuntimeError("TRADING_MODE must be PAPER or LIVE.")

        if trading_mode == "LIVE" and os.getenv("ENABLE_LIVE_TRADING", "").strip().lower() != "true":
            raise RuntimeError("LIVE mode requires ENABLE_LIVE_TRADING=true.")

        return cls(
            port=port,
            environment=environment,
            startup_mode=startup_mode,
            trading_mode=trading_mode,
        )


@dataclass
class RuntimeState:
    started_at: datetime | None = None
    shutdown_at: datetime | None = None
    validation_errors: list[str] = field(default_factory=list)
    ready: bool = False
    telegram_runtime_required: bool = False
    telegram_runtime_enabled: bool = False
    telegram_runtime_startup_complete: bool = False
    telegram_runtime_active: bool = False
    telegram_runtime_shutdown_complete: bool = False
    telegram_runtime_iterations_total: int = 0
    telegram_runtime_last_error: str = ""
    telegram_runtime_task: Optional[asyncio.Task[None]] = None
    db_runtime_required: bool = False
    db_runtime_enabled: bool = False
    db_runtime_connected: bool = False
    db_runtime_healthcheck_ok: bool = False
    db_runtime_last_error: str = ""
    db_connect_max_attempts: int = 0
    db_connect_base_backoff_s: float = 0.0
    db_connect_timeout_s: float = 0.0
    db_client: object | None = None
    lifecycle_phase: str = "created"
    lifecycle_transitions_total: int = 0
    dependency_failures_total: int = 0
    last_dependency_failure_surface: str = ""
    last_dependency_failure_error: str = ""

    def mark_started(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self.ready = True

    def mark_stopped(self) -> None:
        self.shutdown_at = datetime.now(timezone.utc)
        self.ready = False


def validate_api_environment(settings: ApiSettings) -> list[str]:
    errors: list[str] = []

    if settings.startup_mode != "strict":
        errors.append("CRUSADER_STARTUP_MODE must remain 'strict' at runtime.")

    return errors


def validate_runtime_dependencies_from_env() -> list[str]:
    errors: list[str] = []
    db_runtime_enabled = os.getenv("CRUSADER_DB_RUNTIME_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    falcon_enabled = os.getenv("FALCON_ENABLED", "false").strip().lower() == "true"

    if db_runtime_enabled and not os.getenv("DB_DSN", "").strip():
        errors.append(
            "DB_DSN is required when CRUSADER_DB_RUNTIME_ENABLED=true to avoid unsafe local-default persistence targets."
        )

    if falcon_enabled and not os.getenv("FALCON_API_KEY", "").strip():
        errors.append(
            "FALCON_API_KEY is required when FALCON_ENABLED=true; disabled or missing-key mode is not startup-valid."
        )

    return errors


def startup_config_summary(settings: ApiSettings) -> dict[str, object]:
    db_runtime_enabled = os.getenv("CRUSADER_DB_RUNTIME_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    db_runtime_required = os.getenv("CRUSADER_DB_RUNTIME_REQUIRED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    telegram_runtime_required = telegram_runtime_required_from_env()
    falcon_enabled = os.getenv("FALCON_ENABLED", "false").strip().lower() == "true"

    return {
        "startup_mode": settings.startup_mode,
        "trading_mode": settings.trading_mode,
        "environment": settings.environment,
        "paper_only_boundary": settings.trading_mode == "PAPER",
        "db_runtime_enabled": db_runtime_enabled,
        "db_runtime_required": db_runtime_required,
        "db_dsn_configured": bool(os.getenv("DB_DSN", "").strip()),
        "telegram_runtime_required": telegram_runtime_required,
        "telegram_token_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip()),
        "falcon_enabled": falcon_enabled,
        "falcon_api_key_configured": bool(os.getenv("FALCON_API_KEY", "").strip()),
    }


def telegram_runtime_required_from_env() -> bool:
    raw = os.getenv("CRUSADER_TELEGRAM_RUNTIME_REQUIRED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def run_startup_validation(settings: ApiSettings, state: RuntimeState) -> None:
    validation_errors = validate_api_environment(settings) + validate_runtime_dependencies_from_env()
    state.validation_errors = validation_errors

    if validation_errors:
        log.error(
            "crusaderbot_api_startup_validation_failed",
            errors=validation_errors,
            startup_mode=settings.startup_mode,
        )
        raise RuntimeError("; ".join(validation_errors))

    await asyncio.sleep(0)
    state.mark_started()
    summary = startup_config_summary(settings)
    log.info(
        "crusaderbot_api_ready",
        app_name=settings.app_name,
        port=settings.port,
        startup_config_summary=summary,
    )


async def run_shutdown(state: RuntimeState) -> None:
    await asyncio.sleep(0)
    state.mark_stopped()
    log.info("crusaderbot_api_stopped")
