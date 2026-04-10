from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VWAPExecutionResult:
    """Result for simulated orderbook execution using VWAP."""

    allowed: bool
    reason: str | None
    vwap_price: float | None
    filled_size: float
    remaining_size: float
    best_reference_price: float | None


def simulate_vwap_execution(orderbook: dict[str, Any], size: float, side: str) -> VWAPExecutionResult:
    """Walk orderbook levels and estimate execution VWAP for a side/size."""
    target_size = float(size)
    if target_size <= 0.0:
        return VWAPExecutionResult(
            allowed=False,
            reason="size_non_positive",
            vwap_price=None,
            filled_size=0.0,
            remaining_size=target_size,
            best_reference_price=None,
        )
    if not isinstance(orderbook, dict):
        return VWAPExecutionResult(
            allowed=False,
            reason="invalid_orderbook",
            vwap_price=None,
            filled_size=0.0,
            remaining_size=target_size,
            best_reference_price=None,
        )

    normalized_side = str(side).strip().upper()
    levels: list[tuple[float, float]]
    if normalized_side in {"YES", "BUY", "LONG"}:
        ask_levels = _normalize_levels(orderbook.get("asks"))
        if ask_levels is None:
            return _invalid_book_result(target_size)
        levels = sorted(ask_levels, key=lambda level: level[0])
    elif normalized_side in {"NO", "SELL", "SHORT"}:
        bid_levels = _normalize_levels(orderbook.get("bids"))
        if bid_levels is None:
            return _invalid_book_result(target_size)
        levels = sorted(bid_levels, key=lambda level: level[0], reverse=True)
    else:
        return VWAPExecutionResult(
            allowed=False,
            reason="unsupported_side",
            vwap_price=None,
            filled_size=0.0,
            remaining_size=target_size,
            best_reference_price=None,
        )

    if not levels:
        return VWAPExecutionResult(
            allowed=False,
            reason="liquidity_insufficient",
            vwap_price=None,
            filled_size=0.0,
            remaining_size=target_size,
            best_reference_price=None,
        )

    best_reference_price = levels[0][0]
    remaining = target_size
    filled = 0.0
    total_cost = 0.0

    for level_price, level_size in levels:
        if remaining <= 0.0:
            break
        fill_here = min(level_size, remaining)
        if fill_here <= 0.0:
            continue
        total_cost += fill_here * level_price
        filled += fill_here
        remaining -= fill_here

    if filled <= 0.0:
        return VWAPExecutionResult(
            allowed=False,
            reason="liquidity_insufficient",
            vwap_price=None,
            filled_size=0.0,
            remaining_size=target_size,
            best_reference_price=best_reference_price,
        )
    vwap_price = total_cost / filled
    return VWAPExecutionResult(
        allowed=True,
        reason=None,
        vwap_price=vwap_price,
        filled_size=filled,
        remaining_size=max(remaining, 0.0),
        best_reference_price=best_reference_price,
    )


def compute_execution_size(
    orderbook: dict[str, Any],
    target_size: float,
    max_slippage: float,
    *,
    side: str = "YES",
) -> VWAPExecutionResult:
    """Compute slippage-aware executable size under a slippage tolerance."""
    if max_slippage < 0.0:
        return VWAPExecutionResult(
            allowed=False,
            reason="invalid_max_slippage",
            vwap_price=None,
            filled_size=0.0,
            remaining_size=float(target_size),
            best_reference_price=None,
        )

    candidate = simulate_vwap_execution(orderbook, target_size, side)
    if not candidate.allowed or candidate.vwap_price is None or candidate.best_reference_price is None:
        return candidate

    reference = candidate.best_reference_price
    if reference <= 0.0:
        return VWAPExecutionResult(
            allowed=False,
            reason="invalid_reference_price",
            vwap_price=None,
            filled_size=0.0,
            remaining_size=float(target_size),
            best_reference_price=None,
        )

    allowed_size = 0.0
    allowed_vwap: float | None = None
    consumed_cost = 0.0
    remaining = float(target_size)

    normalized_side = str(side).strip().upper()
    if normalized_side in {"YES", "BUY", "LONG"}:
        raw_levels = _normalize_levels(orderbook.get("asks")) if isinstance(orderbook, dict) else None
        if raw_levels is None:
            return _invalid_book_result(float(target_size))
        levels = sorted(raw_levels, key=lambda level: level[0])
    elif normalized_side in {"NO", "SELL", "SHORT"}:
        raw_levels = _normalize_levels(orderbook.get("bids")) if isinstance(orderbook, dict) else None
        if raw_levels is None:
            return _invalid_book_result(float(target_size))
        levels = sorted(raw_levels, key=lambda level: level[0], reverse=True)
    else:
        return VWAPExecutionResult(
            allowed=False,
            reason="unsupported_side",
            vwap_price=None,
            filled_size=0.0,
            remaining_size=float(target_size),
            best_reference_price=None,
        )

    for level_price, level_size in levels:
        if remaining <= 0.0:
            break
        fill_here = min(level_size, remaining)
        if fill_here <= 0.0:
            continue
        next_size = allowed_size + fill_here
        next_cost = consumed_cost + (fill_here * level_price)
        next_vwap = next_cost / next_size
        slippage = abs(next_vwap - reference) / reference
        if slippage > max_slippage:
            break
        allowed_size = next_size
        consumed_cost = next_cost
        remaining -= fill_here
        allowed_vwap = next_vwap

    return VWAPExecutionResult(
        allowed=allowed_size > 0.0,
        reason=None if allowed_size > 0.0 else "slippage_tolerance_exceeded",
        vwap_price=allowed_vwap,
        filled_size=allowed_size,
        remaining_size=max(float(target_size) - allowed_size, 0.0),
        best_reference_price=reference,
    )


def _normalize_levels(raw_levels: Any) -> list[tuple[float, float]] | None:
    if not isinstance(raw_levels, list):
        return None
    normalized: list[tuple[float, float]] = []
    for item in raw_levels:
        if isinstance(item, dict):
            price_raw = item.get("price")
            size_raw = item.get("size")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            price_raw = item[0]
            size_raw = item[1]
        else:
            return None
        try:
            price = float(price_raw)
            size = float(size_raw)
        except (TypeError, ValueError):
            return None
        if price <= 0.0 or price >= 1.0:
            continue
        if size <= 0.0:
            continue
        normalized.append((price, size))
    return normalized


def _invalid_book_result(target_size: float) -> VWAPExecutionResult:
    return VWAPExecutionResult(
        allowed=False,
        reason="invalid_orderbook",
        vwap_price=None,
        filled_size=0.0,
        remaining_size=target_size,
        best_reference_price=None,
    )
