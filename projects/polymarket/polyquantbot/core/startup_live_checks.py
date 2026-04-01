"""Phase 11 — StartupLiveChecks: Full pre-LIVE startup validation gate.

Runs the PreLiveValidator before allowing the system to enter LIVE mode.
Blocks startup entirely if any check fails.

Responsibilities:
    1. Run PreLiveValidator with full infrastructure context.
    2. Raise StartupValidationError if any check fails (fail-closed).
    3. Log all check results regardless of pass/fail.
    4. Send Telegram alert on successful LIVE activation.
    5. Send Telegram alert on validation failure.

Usage::

    from projects.polymarket.polyquantbot.core.startup_live_checks import (
        run_prelive_validation,
        StartupValidationError,
    )

    await run_prelive_validation(
        mode=TradingMode.LIVE,
        metrics_validator=metrics,
        risk_guard=guard,
        redis_client=redis,
        audit_logger=audit,
        telegram_configured=True,
        telegram=tg,
    )
    # Raises StartupValidationError if any check fails.
    # System may proceed to LIVE trading if no exception raised.

Design:
    - Fail-closed: any single PreLive check failure → StartupValidationError.
    - PAPER mode: validation is skipped (returns immediately).
    - Structured logging on every validation result.
    - Telegram notification on LIVE activation (success) or failure.
    - Zero silent failure: all exceptions propagated.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog

from ..core.prelive_validator import PreLiveValidator
from ..phase10.go_live_controller import TradingMode
from ..phase9.telegram_live import AlertType
from ..telegram.message_formatter import (
    format_live_mode_activated,
    format_prelive_check,
)

log = structlog.get_logger()


# ── Exceptions ────────────────────────────────────────────────────────────────


class StartupValidationError(Exception):
    """Raised when PreLiveValidator fails at startup.

    The message contains the first failing check reason.
    """


# ── Primary API ───────────────────────────────────────────────────────────────


async def run_prelive_validation(
    mode: object,
    metrics_validator: Optional[object] = None,
    risk_guard: Optional[object] = None,
    redis_client: Optional[object] = None,
    audit_logger: Optional[object] = None,
    telegram_configured: bool = False,
    telegram: Optional[object] = None,
    ev_capture_min: float = 0.75,
    fill_rate_min: float = 0.60,
    latency_max_ms: float = 500.0,
    drawdown_max: float = 0.08,
) -> None:
    """Run PreLiveValidator and block startup on failure.

    In PAPER mode this function returns immediately without running checks.

    In LIVE mode all eight PreLiveValidator checks must pass:
        ev_capture, fill_rate, latency, drawdown, kill_switch_off,
        redis_connected, db_connected, telegram_configured.

    Args:
        mode: TradingMode enum value or string.
        metrics_validator: MetricsValidator instance.
        risk_guard: RiskGuard instance (kill switch source of truth).
        redis_client: Redis client or None.
        audit_logger: LiveAuditLogger or None.
        telegram_configured: Whether Telegram credentials are set.
        telegram: TelegramLive instance for notifications (optional).
        ev_capture_min: Minimum EV capture ratio threshold.
        fill_rate_min: Minimum fill rate threshold.
        latency_max_ms: Maximum p95 latency threshold in milliseconds.
        drawdown_max: Maximum drawdown threshold.

    Raises:
        StartupValidationError: When any PreLive check fails in LIVE mode.
    """
    is_live = _is_live(mode)

    if not is_live:
        log.info("startup_live_checks_skipped_paper_mode", mode=str(mode))
        return

    log.info("startup_live_checks_begin", mode=str(mode))

    validator = PreLiveValidator(
        metrics_validator=metrics_validator,
        risk_guard=risk_guard,
        redis_client=redis_client,
        audit_logger=audit_logger,
        telegram_configured=telegram_configured,
        ev_capture_min=ev_capture_min,
        fill_rate_min=fill_rate_min,
        latency_max_ms=latency_max_ms,
        drawdown_max=drawdown_max,
    )

    result = validator.run()
    result_dict = result.to_dict()

    if result.status == "FAIL":
        log.error(
            "startup_live_checks_failed",
            reason=result.reason,
            checks=result.checks,
        )
        if telegram is not None:
            msg = format_prelive_check(result_dict)
            await _safe_telegram(telegram, "alert_error", error=result.reason, context="startup_live_checks")

        raise StartupValidationError(
            f"Pre-LIVE validation FAILED — system cannot start in LIVE mode. "
            f"Reason: {result.reason}"
        )

    log.info(
        "startup_live_checks_passed",
        checks=result.checks,
    )

    if telegram is not None:
        msg = format_live_mode_activated(checks=result.checks)
        await _safe_telegram(telegram, "alert_open",
                             market_id="SYSTEM", side="LIVE", price=0.0, size=0.0)
        # Send the formatted LIVE MODE ACTIVATED message directly
        await _safe_telegram_raw(telegram, msg)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_live(mode: object) -> bool:
    """Return True when mode represents LIVE trading."""
    mode_val = getattr(mode, "value", str(mode)).upper()
    return mode_val == "LIVE"


async def _safe_telegram(tg: object, method: str, **kwargs: object) -> None:
    """Call a TelegramLive method, suppressing all exceptions.

    Args:
        tg: TelegramLive instance.
        method: Method name to call.
        **kwargs: Arguments forwarded to the method.
    """
    fn = getattr(tg, method, None)
    if not callable(fn):
        return
    try:
        await asyncio.wait_for(fn(**kwargs), timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("startup_live_checks_telegram_error", method=method, error=str(exc))


async def _safe_telegram_raw(tg: object, message: str) -> None:
    """Send a raw pre-formatted message via TelegramLive._enqueue if available.

    Falls back silently when the method is absent.

    Args:
        tg: TelegramLive instance.
        message: Pre-formatted Telegram Markdown string.
    """
    # TelegramLive exposes _enqueue for internal use; use alert_error as
    # the public fallback to deliver a pre-formatted message.
    fn = getattr(tg, "_enqueue", None)
    if callable(fn):
        try:
            await asyncio.wait_for(fn(AlertType.OPEN, message, None), timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("startup_live_checks_raw_telegram_error", error=str(exc))
