"""Phase 10.7 — StartupChecks: Infrastructure enforcement helpers.

Performs mandatory infrastructure validation at system startup.
These checks MUST run before any LIVE execution is permitted.

Rules:
    LIVE mode requires Redis  → CriticalExecutionError if not connected.
    LIVE mode requires DB     → CriticalAuditError if not connected.

Design:
    - Fail-closed: missing infrastructure in LIVE mode always raises.
    - PAPER mode: warnings logged, no exceptions raised.
    - Idempotent: safe to call multiple times.
    - Structured logging on every check.

Usage::

    from projects.polymarket.polyquantbot.monitoring.startup_checks import run_startup_checks
    from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

    run_startup_checks(
        mode=TradingMode.LIVE,
        redis_client=redis,
        audit_logger=audit,
    )
"""
from __future__ import annotations

from typing import Optional

import structlog

from ..core.exceptions import CriticalAuditError, CriticalExecutionError

log = structlog.get_logger()


# ── Public API ────────────────────────────────────────────────────────────────


def enforce_redis_for_live(
    mode: object,
    redis_client: Optional[object],
) -> None:
    """Enforce Redis connectivity for LIVE mode.

    In LIVE mode Redis is mandatory — it provides order deduplication via
    correlation_id.  Without Redis idempotency cannot be guaranteed and
    duplicate orders may reach the exchange.

    In PAPER mode, a warning is logged but no exception is raised.

    Args:
        mode: TradingMode enum value.  Compared by ``.value`` attribute or
              string equality to "LIVE".
        redis_client: Redis client instance, or None if not connected.

    Raises:
        CriticalExecutionError: When mode is LIVE and redis_client is None.
    """
    is_live = _is_live_mode(mode)

    if redis_client is not None:
        log.info("startup_check_redis_ok", mode=str(mode))
        return

    if is_live:
        msg = (
            "Redis is required in LIVE mode but redis_client is None. "
            "Connect Redis before enabling LIVE trading."
        )
        log.error("startup_check_redis_missing_live", mode=str(mode))
        raise CriticalExecutionError(msg)

    log.warning(
        "startup_check_redis_missing_paper",
        mode=str(mode),
        note="Redis is recommended for dedup even in PAPER mode",
    )


def enforce_db_for_live(
    mode: object,
    audit_logger: Optional[object],
) -> None:
    """Enforce PostgreSQL connectivity for LIVE mode.

    In LIVE mode PostgreSQL is mandatory — every execution MUST be persisted
    before and after the exchange call.  Without a DB connection the immutable
    audit trail cannot be maintained.

    In PAPER mode, a warning is logged but no exception is raised.

    Args:
        mode: TradingMode enum value.
        audit_logger: LiveAuditLogger instance with ``is_db_connected()``
                      method, or None if not configured.

    Raises:
        CriticalAuditError: When mode is LIVE and DB is not connected.
    """
    is_live = _is_live_mode(mode)

    db_connected = _check_db_connected(audit_logger)

    if db_connected:
        log.info("startup_check_db_ok", mode=str(mode))
        return

    if is_live:
        msg = (
            "PostgreSQL is required in LIVE mode but DB is not connected. "
            "Connect the database before enabling LIVE trading."
        )
        log.error("startup_check_db_missing_live", mode=str(mode))
        raise CriticalAuditError(msg)

    log.warning(
        "startup_check_db_missing_paper",
        mode=str(mode),
        note="Audit logging unavailable — recommended for full observability",
    )


def run_startup_checks(
    mode: object,
    redis_client: Optional[object] = None,
    audit_logger: Optional[object] = None,
) -> None:
    """Run all mandatory startup infrastructure checks.

    This is a convenience wrapper that calls both :func:`enforce_redis_for_live`
    and :func:`enforce_db_for_live` in order.

    Args:
        mode: TradingMode enum value.
        redis_client: Redis client instance or None.
        audit_logger: LiveAuditLogger instance or None.

    Raises:
        CriticalExecutionError: When LIVE and Redis not connected.
        CriticalAuditError: When LIVE and DB not connected.
    """
    log.info("startup_checks_begin", mode=str(mode))
    enforce_redis_for_live(mode=mode, redis_client=redis_client)
    enforce_db_for_live(mode=mode, audit_logger=audit_logger)
    log.info("startup_checks_passed", mode=str(mode))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_live_mode(mode: object) -> bool:
    """Return True when mode represents LIVE trading."""
    # Support TradingMode enum and plain strings
    mode_val = getattr(mode, "value", str(mode)).upper()
    return mode_val == "LIVE"


def _check_db_connected(audit_logger: Optional[object]) -> bool:
    """Return True if audit_logger reports a connected DB."""
    if audit_logger is None:
        return False
    fn = getattr(audit_logger, "is_db_connected", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001
            return False
    return False
