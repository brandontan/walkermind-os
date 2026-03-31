"""Phase 10.6 — Critical infrastructure exceptions.

Raised when mandatory infrastructure is unavailable in LIVE mode.
These exceptions represent fail-closed conditions — execution MUST NOT
proceed when critical dependencies are absent.

Exceptions:
    CriticalExecutionError: Redis unavailable in LIVE mode.
    CriticalAuditError: PostgreSQL unavailable in LIVE mode.
    InfrastructureError: Generic infrastructure dependency failure.
"""
from __future__ import annotations


class InfrastructureError(Exception):
    """Base class for critical infrastructure failures."""


class CriticalExecutionError(InfrastructureError):
    """Raised when Redis is required but unavailable in LIVE mode.

    Redis is mandatory for order deduplication in LIVE mode.
    Without Redis, idempotency cannot be guaranteed and duplicate
    orders may be submitted to the exchange.

    Usage::

        if mode == TradingMode.LIVE and redis_client is None:
            raise CriticalExecutionError(
                "Redis is required in LIVE mode but redis_client is None. "
                "Connect Redis before enabling LIVE trading."
            )
    """


class CriticalAuditError(InfrastructureError):
    """Raised when PostgreSQL is required but unavailable in LIVE mode.

    The audit log is mandatory for LIVE mode — every execution MUST be
    persisted before and after the exchange call.  Without a DB connection,
    the immutable audit trail cannot be maintained.

    Usage::

        if mode == TradingMode.LIVE and not db_connected:
            raise CriticalAuditError(
                "PostgreSQL is required in LIVE mode but DB is not connected. "
                "Connect the database before enabling LIVE trading."
            )
    """
