"""Sentry runtime integration helpers for CrusaderBot Python surfaces."""
from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_SENTRY_INITIALIZED = False


def initialize_sentry() -> bool:
    """Initialize Sentry SDK for Python runtime if SENTRY_DSN is configured.

    Returns True when initialization completes; otherwise False (safe no-op).
    """
    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        log.info("crusaderbot_sentry_disabled", reason="missing_sentry_dsn")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
    except ImportError:
        log.error(
            "crusaderbot_sentry_unavailable",
            reason="missing_sentry_sdk_dependency",
        )
        return False

    environment = os.getenv("SENTRY_ENVIRONMENT", "").strip() or os.getenv("APP_ENV", "development")
    release = os.getenv("SENTRY_RELEASE", "").strip() or None
    traces_sample_rate = _read_float_env("SENTRY_TRACES_SAMPLE_RATE", default=0.0)

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        integrations=[FastApiIntegration()],
        send_default_pii=False,
        traces_sample_rate=traces_sample_rate,
    )
    _SENTRY_INITIALIZED = True
    log.info(
        "crusaderbot_sentry_initialized",
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        pii_mode="disabled",
    )
    return True


def capture_runtime_exception(exc: BaseException, **context: Any) -> None:
    """Capture runtime exceptions when Sentry is active.

    This helper is safe to call even when Sentry is disabled or unavailable.
    """
    if not _SENTRY_INITIALIZED:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_tag(key, str(value))
            sentry_sdk.capture_exception(exc)
    except Exception:
        log.error("crusaderbot_sentry_capture_failed")


def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.error("crusaderbot_sentry_invalid_float_env", variable=name, value=raw)
        return default
