"""Sentry SDK bootstrap.

Init is gated on ``SENTRY_DSN`` being set — when unset (local / CI), this
module is a no-op so test runs and local development don't ship events to
the production project. The init helper never raises: a misconfigured DSN
must NOT block FastAPI startup.

Production sets ``SENTRY_DSN`` as a Fly.io secret. ``APP_VERSION`` (git
short SHA) is propagated as the release tag so triage can pin events to a
build, and the app environment (``APP_ENV``) is propagated as the
environment tag.
"""
from __future__ import annotations

import logging

from ..config import get_settings

logger = logging.getLogger(__name__)

_initialised: bool = False


def init_sentry() -> bool:
    """Initialise the Sentry SDK if a DSN is configured.

    Returns ``True`` when Sentry is now active (DSN present + SDK init
    succeeded), ``False`` otherwise. Idempotent — safe to call from the
    lifespan hook on every cold start; subsequent calls are a no-op.
    """
    global _initialised
    if _initialised:
        return True

    settings = get_settings()
    dsn = (settings.SENTRY_DSN or "").strip()
    if not dsn:
        logger.info("Sentry disabled (SENTRY_DSN not set).")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=settings.APP_ENV,
            release=settings.APP_VERSION or None,
            traces_sample_rate=float(settings.SENTRY_TRACES_SAMPLE_RATE or 0.0),
            send_default_pii=False,
            integrations=[
                FastApiIntegration(),
                StarletteIntegration(),
            ],
        )
        _initialised = True
        logger.info(
            "Sentry initialised (env=%s, release=%s, traces_sample_rate=%s).",
            settings.APP_ENV,
            settings.APP_VERSION or "unset",
            settings.SENTRY_TRACES_SAMPLE_RATE,
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
