"""Sentry SDK bootstrap.

Init is gated on ``SENTRY_DSN`` being set — when unset (local / CI), this
module is a no-op so test runs and local development don't ship events to
the production project. The init helper never raises: a misconfigured DSN
must NOT block FastAPI startup.

Sentry config is read **directly from ``os.environ``** rather than via
``config.get_settings()`` — building the full ``Settings`` model would
validate every required app secret (``TELEGRAM_BOT_TOKEN``,
``DATABASE_URL``, ...), so a partially-configured environment would raise
``pydantic.ValidationError`` before the DSN check and break the "quiet
no-op when DSN unset" promise. Decoupling here keeps Sentry init
independent of the rest of the app config and lets it run *first* in the
lifespan hook so any subsequent settings-validation failure is captured.

Production sets ``SENTRY_DSN`` as a Fly.io secret. ``APP_VERSION`` (git
short SHA) is propagated as the release tag so triage can pin events to a
build, and the app environment (``APP_ENV``) is propagated as the
environment tag. ``SENTRY_TRACES_SAMPLE_RATE`` defaults to ``0.0``
(errors-only).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_initialised: bool = False


def _read_env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _read_traces_sample_rate() -> float:
    """Parse ``SENTRY_TRACES_SAMPLE_RATE`` from env, falling back to ``0.0``.

    A malformed value (non-numeric, empty after strip) falls back to
    ``0.0`` rather than raising — the env-read must never block boot.
    """
    raw = _read_env("SENTRY_TRACES_SAMPLE_RATE")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "SENTRY_TRACES_SAMPLE_RATE=%r is not a float; defaulting to 0.0.",
            raw,
        )
        return 0.0


def init_sentry() -> bool:
    """Initialise the Sentry SDK if a DSN is configured.

    Returns ``True`` when Sentry is now active (DSN present + SDK init
    succeeded), ``False`` otherwise. Idempotent — safe to call from the
    lifespan hook on every cold start; subsequent calls are a no-op.
    """
    global _initialised
    if _initialised:
        return True

    dsn = _read_env("SENTRY_DSN")
    if not dsn:
        logger.info("Sentry disabled (SENTRY_DSN not set).")
        return False

    environment = _read_env("APP_ENV", "development")
    release = _read_env("APP_VERSION") or None
    traces_sample_rate = _read_traces_sample_rate()

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            traces_sample_rate=traces_sample_rate,
            send_default_pii=False,
            integrations=[
                FastApiIntegration(),
                StarletteIntegration(),
            ],
        )
        _initialised = True
        logger.info(
            "Sentry initialised (env=%s, release=%s, traces_sample_rate=%s).",
            environment,
            release or "unset",
            traces_sample_rate,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — never crash boot on Sentry init
        logger.error("Sentry init failed: %s", exc, exc_info=False)
        return False


def is_initialised() -> bool:
    return _initialised


def capture_test_event(message: str) -> str | None:
    """Send a synthetic event to Sentry to verify wiring.

    Returns the event id when capture succeeded, ``None`` otherwise (Sentry
    not initialised, or SDK raised). The message is plain text — callers
    must not embed secrets.
    """
    if not _initialised:
        return None
    try:
        import sentry_sdk

        return sentry_sdk.capture_message(message, level="info")
    except Exception as exc:  # noqa: BLE001
        logger.error("Sentry capture_test_event failed: %s", exc, exc_info=False)
        return None


def reset_for_tests() -> None:
    """Test-only helper: clears the init flag so tests can re-init."""
    global _initialised
    _initialised = False
