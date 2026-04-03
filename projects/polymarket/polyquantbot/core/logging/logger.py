"""core.logging.logger — Structured warning log helpers.

Provides reusable log functions with consistent event keys and field
conventions so that log aggregators can filter market-parse warnings by
a stable ``event`` field.

Usage::

    from core.logging.logger import log_invalid_market, log_market_parse_warning

    log_market_parse_warning("market_id_abc", "outcomePrices malformed")
    log_invalid_market("market_id_xyz", reason="array_too_short", field="outcomePrices")
"""
from __future__ import annotations

from typing import Any

import structlog

_log = structlog.get_logger()


def log_market_parse_warning(
    market_id: str | None,
    error: str,
    **extra: Any,
) -> None:
    """Emit a structured ``market_parse_warning`` log event.

    Args:
        market_id: Raw market identifier (may be ``None`` if extraction failed
                   before the ID could be determined).
        error:     Human-readable description of the parse failure.
        **extra:   Additional key-value pairs forwarded to structlog.
    """
    _log.warning(
        "market_parse_warning",
        market_id=market_id,
        error=error,
        **extra,
    )


def log_invalid_market(
    market_id: str | None,
    *,
    reason: str,
    field: str | None = None,
    **extra: Any,
) -> None:
    """Emit a structured ``market_invalid`` log event.

    Args:
        market_id: Raw market identifier.
        reason:    Short machine-readable reason code (e.g. ``"array_too_short"``).
        field:     Name of the offending field, if applicable.
        **extra:   Additional key-value pairs forwarded to structlog.
    """
    _log.warning(
        "market_invalid",
        market_id=market_id,
        reason=reason,
        field=field,
        **extra,
    )
