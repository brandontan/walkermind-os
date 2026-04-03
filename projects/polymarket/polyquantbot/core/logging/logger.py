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


# ── Paper trading realism log helpers ─────────────────────────────────────────


def log_trade_executed_realistic(
    trade_id: str,
    market_id: str,
    *,
    side: str,
    fill_price: float,
    filled_size_usd: float,
    slippage_pct: float,
    partial_fill: bool,
    latency_ms: float,
    mode: str = "PAPER",
    **extra: Any,
) -> None:
    """Emit a structured ``trade_executed_realistic`` log event.

    Args:
        trade_id:        Unique trade identifier.
        market_id:       Polymarket condition ID.
        side:            Trade direction ("YES" | "NO").
        fill_price:      Execution fill price after slippage.
        filled_size_usd: USD amount actually filled.
        slippage_pct:    Slippage applied as a fraction (e.g. 0.008 = 0.8 %).
        partial_fill:    True when only a fraction of requested size was filled.
        latency_ms:      Simulated execution latency in milliseconds.
        mode:            Execution mode ("PAPER" | "LIVE").
        **extra:         Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "trade_executed_realistic",
        trade_id=trade_id,
        market_id=market_id,
        side=side,
        fill_price=round(fill_price, 6),
        filled_size_usd=round(filled_size_usd, 4),
        slippage_pct=round(slippage_pct, 6),
        partial_fill=partial_fill,
        latency_ms=round(latency_ms, 2),
        mode=mode,
        **extra,
    )


def log_partial_fill(
    trade_id: str,
    market_id: str,
    *,
    requested_size_usd: float,
    filled_size_usd: float,
    fill_fraction: float,
    **extra: Any,
) -> None:
    """Emit a structured ``partial_fill`` log event.

    Args:
        trade_id:           Unique trade identifier.
        market_id:          Polymarket condition ID.
        requested_size_usd: Original requested size in USD.
        filled_size_usd:    Actual filled size in USD.
        fill_fraction:      Fraction filled (0.0–1.0).
        **extra:            Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "partial_fill",
        trade_id=trade_id,
        market_id=market_id,
        requested_size_usd=round(requested_size_usd, 4),
        filled_size_usd=round(filled_size_usd, 4),
        fill_fraction=round(fill_fraction, 4),
        **extra,
    )


def log_slippage_applied(
    trade_id: str,
    market_id: str,
    *,
    base_price: float,
    fill_price: float,
    slippage_pct: float,
    side: str,
    **extra: Any,
) -> None:
    """Emit a structured ``slippage_applied`` log event.

    Args:
        trade_id:     Unique trade identifier.
        market_id:    Polymarket condition ID.
        base_price:   Original mid price before slippage.
        fill_price:   Execution price after slippage.
        slippage_pct: Slippage applied as a fraction.
        side:         Trade direction ("YES" | "NO").
        **extra:      Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "slippage_applied",
        trade_id=trade_id,
        market_id=market_id,
        base_price=round(base_price, 6),
        fill_price=round(fill_price, 6),
        slippage_pct=round(slippage_pct, 6),
        side=side,
        **extra,
    )


def log_pnl_realized(
    market_id: str,
    *,
    trade_id: str,
    pnl_usd: float,
    cumulative_realized: float,
    **extra: Any,
) -> None:
    """Emit a structured ``pnl_realized`` log event.

    Args:
        market_id:            Polymarket condition ID.
        trade_id:             Unique trade identifier.
        pnl_usd:              Realized PnL for this trade in USD.
        cumulative_realized:  Total realized PnL across all trades for this market.
        **extra:              Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "pnl_realized",
        market_id=market_id,
        trade_id=trade_id,
        pnl_usd=round(pnl_usd, 4),
        cumulative_realized=round(cumulative_realized, 4),
        **extra,
    )


def log_pnl_unrealized(
    market_id: str,
    *,
    unrealized_pnl_usd: float,
    mark_price: float,
    **extra: Any,
) -> None:
    """Emit a structured ``pnl_unrealized`` log event.

    Args:
        market_id:          Polymarket condition ID.
        unrealized_pnl_usd: Current unrealized PnL in USD.
        mark_price:         Mid price used for mark-to-market.
        **extra:            Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "pnl_unrealized",
        market_id=market_id,
        unrealized_pnl_usd=round(unrealized_pnl_usd, 4),
        mark_price=round(mark_price, 6),
        **extra,
    )


def log_market_metadata_used(
    market_id: str,
    *,
    question: str,
    outcomes: list,
    source: str = "cache",
    **extra: Any,
) -> None:
    """Emit a structured ``market_metadata_used`` log event.

    Args:
        market_id: Polymarket condition ID.
        question:  Human-readable market question resolved from cache.
        outcomes:  List of outcome labels for this market.
        source:    Where the metadata was sourced from (e.g. "cache", "fallback").
        **extra:   Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "market_metadata_used",
        market_id=market_id,
        question=question,
        outcomes=outcomes,
        source=source,
        **extra,
    )


def log_position_updated(
    market_id: str,
    *,
    side: str,
    avg_price: float,
    size: float,
    trade_id: str = "",
    **extra: Any,
) -> None:
    """Emit a structured ``position_updated`` log event.

    Args:
        market_id:  Polymarket condition ID.
        side:       Trade direction ("YES" | "NO").
        avg_price:  Weighted average entry price after update.
        size:       Total position size in USD after update.
        trade_id:   Trade identifier that triggered the update.
        **extra:    Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "position_updated",
        market_id=market_id,
        side=side,
        avg_price=round(avg_price, 6),
        size=round(size, 4),
        trade_id=trade_id or "n/a",
        **extra,
    )


def log_pnl_updated(
    market_id: str,
    *,
    realized: float,
    unrealized: float,
    total: float,
    **extra: Any,
) -> None:
    """Emit a structured ``pnl_updated`` log event.

    Args:
        market_id:   Polymarket condition ID.
        realized:    Current realized PnL for this market in USD.
        unrealized:  Current unrealized PnL for this market in USD.
        total:       realized + unrealized.
        **extra:     Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "pnl_updated",
        market_id=market_id,
        realized=round(realized, 4),
        unrealized=round(unrealized, 4),
        total=round(total, 4),
        **extra,
    )


def log_telegram_trade_detailed(
    trade_id: str,
    market_id: str,
    *,
    market_question: str,
    side: str,
    price: float,
    size: float,
    slippage_pct: float,
    partial_fill: bool,
    filled_size: float,
    realized_pnl: float,
    unrealized_pnl: float,
    **extra: Any,
) -> None:
    """Emit a structured ``telegram_trade_detailed`` log event.

    Args:
        trade_id:        Unique trade identifier.
        market_id:       Polymarket condition ID.
        market_question: Human-readable market question (or market_id as fallback).
        side:            Trade direction ("YES" | "NO").
        price:           Execution fill price.
        size:            Requested trade size in USD.
        slippage_pct:    Slippage applied as a fraction.
        partial_fill:    Whether the fill was partial.
        filled_size:     Actual filled size in USD.
        realized_pnl:    Cumulative realized PnL for this market.
        unrealized_pnl:  Current unrealized PnL for this market.
        **extra:         Additional key-value pairs forwarded to structlog.
    """
    _log.info(
        "telegram_trade_detailed",
        trade_id=trade_id,
        market_id=market_id,
        market_question=market_question,
        side=side,
        price=round(price, 6),
        size=round(size, 4),
        slippage_pct=round(slippage_pct, 6),
        partial_fill=partial_fill,
        filled_size=round(filled_size, 4),
        realized_pnl=round(realized_pnl, 4),
        unrealized_pnl=round(unrealized_pnl, 4),
        **extra,
    )
