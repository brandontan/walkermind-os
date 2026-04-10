from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DriftCheckResult:
    """Result of execution price drift boundary validation."""

    allowed: bool
    drift_ratio: float
    max_drift_ratio: float


@dataclass(frozen=True)
class MarketDataValidationResult:
    """Validation outcome for execution-boundary market data."""

    allowed: bool
    reason: str | None
    details: dict[str, Any]
    reference_price: float | None
    model_probability: float | None


def evaluate_execution_price_drift(
    *,
    expected_price: float,
    execution_price: float,
    max_drift_ratio: float,
) -> DriftCheckResult:
    """Evaluate execution drift ratio using absolute deviation from expected price.

    This helper is intentionally narrow: it only computes and classifies drift.
    Enforcement and order lifecycle decisions are handled in engine/runtime callers.
    """
    if expected_price <= 0.0:
        raise ValueError("expected_price must be > 0")
    if max_drift_ratio < 0.0:
        raise ValueError("max_drift_ratio must be >= 0")

    drift_ratio = abs(float(execution_price) - float(expected_price)) / float(expected_price)
    return DriftCheckResult(
        allowed=drift_ratio <= float(max_drift_ratio),
        drift_ratio=drift_ratio,
        max_drift_ratio=float(max_drift_ratio),
    )


def compute_dynamic_drift_threshold(
    *,
    orderbook: dict[str, Any],
    base_threshold: float,
    volatility_proxy: float | None = None,
) -> float:
    """Compute conservative, context-aware drift threshold from orderbook conditions."""
    if base_threshold <= 0.0:
        raise ValueError("base_threshold must be > 0")
    if not isinstance(orderbook, dict):
        raise ValueError("orderbook must be a dict")

    bids = _normalize_levels(orderbook.get("bids"))
    asks = _normalize_levels(orderbook.get("asks"))
    if bids is None or asks is None or not bids or not asks:
        raise ValueError("orderbook must contain valid bids and asks")

    best_bid = _best_bid_price(bids)
    best_ask = _best_ask_price(asks)
    if best_bid is None or best_ask is None or best_ask <= best_bid:
        raise ValueError("orderbook spread is invalid")

    mid_price = (best_bid + best_ask) / 2.0
    spread_ratio = (best_ask - best_bid) / mid_price
    top_bid_depth = sum(size for _, size in sorted(bids, key=lambda x: x[0], reverse=True)[:3])
    top_ask_depth = sum(size for _, size in sorted(asks, key=lambda x: x[0])[:3])
    total_top_depth = top_bid_depth + top_ask_depth
    if total_top_depth <= 0.0:
        raise ValueError("orderbook top depth must be > 0")
    depth_imbalance = abs(top_bid_depth - top_ask_depth) / total_top_depth

    stress_multiplier = 1.0
    stress_multiplier += min(spread_ratio * 2.0, 0.5)
    stress_multiplier += min(depth_imbalance * 0.6, 0.3)
    if volatility_proxy is not None:
        if volatility_proxy < 0.0:
            raise ValueError("volatility_proxy must be >= 0")
        stress_multiplier += min(float(volatility_proxy), 0.4)

    relaxed_multiplier = 1.0
    if spread_ratio < 0.01 and depth_imbalance < 0.20:
        relaxed_multiplier = 1.10

    conservative_threshold = base_threshold * relaxed_multiplier / stress_multiplier
    min_threshold = base_threshold * 0.60
    max_threshold = base_threshold * 1.25
    return max(min_threshold, min(max_threshold, conservative_threshold))


def validate_execution_market_data(
    *,
    execution_market_data: dict[str, Any] | None,
    side: str,
    now_ts: float,
    max_age_seconds: float,
) -> MarketDataValidationResult:
    """Validate execution market data and derive authoritative reference price."""
    if execution_market_data is None:
        return MarketDataValidationResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "execution_market_data", "issue": "missing"},
            reference_price=None,
            model_probability=None,
        )
    if not isinstance(execution_market_data, dict):
        return MarketDataValidationResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "execution_market_data", "issue": "not_dict"},
            reference_price=None,
            model_probability=None,
        )

    snapshot_ts_raw = execution_market_data.get("timestamp")
    snapshot_ts = _parse_timestamp(snapshot_ts_raw)
    if snapshot_ts is None:
        return MarketDataValidationResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "timestamp", "value": snapshot_ts_raw, "issue": "invalid_or_missing"},
            reference_price=None,
            model_probability=None,
        )
    age_seconds = float(now_ts) - snapshot_ts
    if age_seconds < 0.0:
        return MarketDataValidationResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "timestamp", "issue": "future_timestamp", "age_seconds": age_seconds},
            reference_price=None,
            model_probability=None,
        )
    if age_seconds > float(max_age_seconds):
        return MarketDataValidationResult(
            allowed=False,
            reason="stale_data",
            details={
                "snapshot_timestamp": snapshot_ts,
                "current_timestamp": float(now_ts),
                "age_seconds": age_seconds,
                "threshold_seconds": float(max_age_seconds),
            },
            reference_price=None,
            model_probability=None,
        )

    model_probability_raw = execution_market_data.get("model_probability")
    model_probability = _parse_probability(model_probability_raw)
    if model_probability is None:
        return MarketDataValidationResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "model_probability", "value": model_probability_raw, "issue": "invalid_or_missing"},
            reference_price=None,
            model_probability=None,
        )

    orderbook = execution_market_data.get("orderbook")
    if not isinstance(orderbook, dict):
        return MarketDataValidationResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "orderbook", "issue": "missing_or_not_dict"},
            reference_price=None,
            model_probability=model_probability,
        )

    bids = _normalize_levels(orderbook.get("bids"))
    asks = _normalize_levels(orderbook.get("asks"))
    if bids is None or asks is None:
        return MarketDataValidationResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "orderbook", "issue": "malformed_levels"},
            reference_price=None,
            model_probability=model_probability,
        )

    normalized_side = str(side).strip().upper()
    if normalized_side in {"YES", "BUY", "LONG"}:
        reference_price = _best_ask_price(asks)
    elif normalized_side in {"NO", "SELL", "SHORT"}:
        reference_price = _best_bid_price(bids)
    else:
        return MarketDataValidationResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "side", "issue": "unsupported_value", "value": side},
            reference_price=None,
            model_probability=model_probability,
        )
    if reference_price is None:
        return MarketDataValidationResult(
            allowed=False,
            reason="liquidity_insufficient",
            details={"field": "orderbook", "issue": "no_executable_levels", "side": normalized_side},
            reference_price=None,
            model_probability=model_probability,
        )

    return MarketDataValidationResult(
        allowed=True,
        reason=None,
        details={
            "snapshot_timestamp": snapshot_ts,
            "current_timestamp": float(now_ts),
            "age_seconds": age_seconds,
            "threshold_seconds": float(max_age_seconds),
        },
        reference_price=reference_price,
        model_probability=model_probability,
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


def _best_ask_price(asks: list[tuple[float, float]]) -> float | None:
    if not asks:
        return None
    return min(price for price, _ in asks)


def _best_bid_price(bids: list[tuple[float, float]]) -> float | None:
    if not bids:
        return None
    return max(price for price, _ in bids)


def _parse_probability(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0.0 or parsed > 1.0:
        return None
    return parsed


def _parse_timestamp(raw_value: Any) -> float | None:
    if isinstance(raw_value, (int, float)):
        timestamp = float(raw_value)
        return timestamp if timestamp > 0.0 else None
    if isinstance(raw_value, str):
        candidate = raw_value.strip()
        if not candidate:
            return None
        try:
            return float(candidate)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
    return None
