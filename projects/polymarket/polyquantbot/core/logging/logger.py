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


def log_alpha_injected(
    market_id: str,
    *,
    injected_edge: float,
    p_market: float,
    p_model: float,
    force_mode: bool = False,
    **extra: Any,
) -> None:
    """Emit a structured ``alpha_injected`` log event.

    Args:
        market_id:     Polymarket condition ID.
        injected_edge: The edge value that was injected (e.g. 0.01).
        p_market:      Original market-implied probability.
        p_model:       Updated model probability after injection.
        force_mode:    Whether the injection occurred in force mode.
        **extra:       Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "alpha_injected",
        market_id=market_id,
        injected_edge=round(injected_edge, 4),
        p_market=round(p_market, 4),
        p_model=round(p_model, 4),
        force_mode=force_mode,
        **extra,
    )


def log_force_trade_executed(
    trade_id: str,
    market_id: str,
    *,
    side: str,
    edge: float,
    size_usd: float,
    fill_price: float,
    **extra: Any,
) -> None:
    """Emit a structured ``force_trade_executed`` log event.

    Args:
        trade_id:   Unique trade identifier.
        market_id:  Polymarket condition ID.
        side:       Trade direction ("YES" | "NO").
        edge:       Signal edge at execution time.
        size_usd:   Filled size in USD.
        fill_price: Execution fill price.
        **extra:    Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "force_trade_executed",
        trade_id=trade_id,
        market_id=market_id,
        side=side,
        edge=round(edge, 4),
        size_usd=round(size_usd, 4),
        fill_price=round(fill_price, 6),
        **extra,
    )


def log_telegram_sent(
    trade_id: str,
    market_id: str,
    **extra: Any,
) -> None:
    """Emit a structured ``telegram_sent`` log event.

    Args:
        trade_id:  Trade identifier for correlation.
        market_id: Polymarket condition ID.
        **extra:   Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "telegram_sent",
        trade_id=trade_id,
        market_id=market_id,
        **extra,
    )


def log_telegram_failed(
    trade_id: str,
    market_id: str,
    *,
    error: str,
    **extra: Any,
) -> None:
    """Emit a structured ``telegram_failed`` log event.

    Args:
        trade_id:  Trade identifier for correlation.
        market_id: Polymarket condition ID.
        error:     Error message from the failed send attempt.
        **extra:   Additional key-value pairs forwarded to structlog.
    """
    _log.warning(
        "telegram_failed",
        trade_id=trade_id,
        market_id=market_id,
        error=error,
        **extra,
    )
