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


def telegram_runtime_required_from_env() -> bool:
    raw = os.getenv("CRUSADER_TELEGRAM_RUNTIME_REQUIRED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def run_startup_validation(settings: ApiSettings, state: RuntimeState) -> None:
    validation_errors = validate_api_environment(settings)
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
    log.info(
        "crusaderbot_api_ready",
        app_name=settings.app_name,
        port=settings.port,
        trading_mode=settings.trading_mode,
    )


async def run_shutdown(state: RuntimeState) -> None:
    await asyncio.sleep(0)
    state.mark_stopped()
    log.info("crusaderbot_api_stopped")
