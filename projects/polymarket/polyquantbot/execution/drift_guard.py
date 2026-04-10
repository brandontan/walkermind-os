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


@dataclass(frozen=True)
class ExecutionPriceEstimateResult:
    """Execution-price estimation outcome from orderbook levels."""

    allowed: bool
    reason: str | None
    details: dict[str, Any]
    estimated_execution_price: float | None
    executable_size: float


@dataclass(frozen=True)
class DynamicDriftThresholdResult:
    """Dynamic drift-threshold computation outcome."""

    allowed: bool
    reason: str | None
    details: dict[str, Any]
    max_drift_ratio: float | None


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


def estimate_execution_price_from_orderbook(
    *,
    orderbook: dict[str, Any],
    side: str,
    requested_size: float,
) -> ExecutionPriceEstimateResult:
    """Estimate executable VWAP from orderbook depth for the requested side."""
    if requested_size <= 0.0:
        return ExecutionPriceEstimateResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "size", "issue": "non_positive", "value": requested_size},
            estimated_execution_price=None,
            executable_size=0.0,
        )
    if not isinstance(orderbook, dict):
        return ExecutionPriceEstimateResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "orderbook", "issue": "missing_or_not_dict"},
            estimated_execution_price=None,
            executable_size=0.0,
        )
    bids = _normalize_levels(orderbook.get("bids"))
    asks = _normalize_levels(orderbook.get("asks"))
    if bids is None or asks is None:
        return ExecutionPriceEstimateResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "orderbook", "issue": "malformed_levels"},
            estimated_execution_price=None,
            executable_size=0.0,
        )

    normalized_side = str(side).strip().upper()
    if normalized_side in {"YES", "BUY", "LONG"}:
        book_levels = sorted(asks, key=lambda level: level[0])
    elif normalized_side in {"NO", "SELL", "SHORT"}:
        book_levels = sorted(bids, key=lambda level: level[0], reverse=True)
    else:
        return ExecutionPriceEstimateResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "side", "issue": "unsupported_value", "value": side},
            estimated_execution_price=None,
            executable_size=0.0,
        )
    if not book_levels:
        return ExecutionPriceEstimateResult(
            allowed=False,
            reason="liquidity_insufficient",
            details={"field": "orderbook", "issue": "no_executable_levels", "side": normalized_side},
            estimated_execution_price=None,
            executable_size=0.0,
        )

    remaining = float(requested_size)
    filled_size = 0.0
    total_notional = 0.0
    for level_price, level_size in book_levels:
        if remaining <= 0.0:
            break
        take_size = min(level_size, remaining)
        if take_size <= 0.0:
            continue
        total_notional += float(level_price) * take_size
        filled_size += take_size
        remaining -= take_size
    if filled_size <= 0.0:
        return ExecutionPriceEstimateResult(
            allowed=False,
            reason="liquidity_insufficient",
            details={"field": "orderbook", "issue": "no_fillable_size", "side": normalized_side},
            estimated_execution_price=None,
            executable_size=0.0,
        )
    if filled_size + 1e-9 < float(requested_size):
        return ExecutionPriceEstimateResult(
            allowed=False,
            reason="liquidity_insufficient",
            details={
                "field": "orderbook",
                "issue": "insufficient_depth",
                "side": normalized_side,
                "requested_size": float(requested_size),
                "fillable_size": filled_size,
            },
            estimated_execution_price=None,
            executable_size=filled_size,
        )

    return ExecutionPriceEstimateResult(
        allowed=True,
        reason=None,
        details={"side": normalized_side, "requested_size": float(requested_size)},
        estimated_execution_price=(total_notional / filled_size),
        executable_size=filled_size,
    )


def compute_dynamic_drift_threshold(
    *,
    orderbook: dict[str, Any],
    side: str,
    base_max_drift_ratio: float,
    volatility: float | None = None,
) -> DynamicDriftThresholdResult:
    """Compute dynamic drift threshold from spread/depth stress and volatility."""
    if base_max_drift_ratio <= 0.0:
        return DynamicDriftThresholdResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "base_max_drift_ratio", "issue": "non_positive", "value": base_max_drift_ratio},
            max_drift_ratio=None,
        )
    if volatility is not None and (volatility < 0.0 or volatility > 1.0):
        return DynamicDriftThresholdResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "volatility", "issue": "out_of_range", "value": volatility},
            max_drift_ratio=None,
        )
    if not isinstance(orderbook, dict):
        return DynamicDriftThresholdResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "orderbook", "issue": "missing_or_not_dict"},
            max_drift_ratio=None,
        )
    bids = _normalize_levels(orderbook.get("bids"))
    asks = _normalize_levels(orderbook.get("asks"))
    if bids is None or asks is None or not bids or not asks:
        return DynamicDriftThresholdResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "orderbook", "issue": "invalid_depth_levels"},
            max_drift_ratio=None,
        )

    best_bid = _best_bid_price(bids)
    best_ask = _best_ask_price(asks)
    if best_bid is None or best_ask is None or best_ask <= 0.0 or best_bid <= 0.0 or best_ask <= best_bid:
        return DynamicDriftThresholdResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "spread", "issue": "invalid_or_non_positive"},
            max_drift_ratio=None,
        )

    normalized_side = str(side).strip().upper()
    if normalized_side in {"YES", "BUY", "LONG"}:
        same_side_depth = sum(size for _, size in asks)
        opposite_side_depth = sum(size for _, size in bids)
    elif normalized_side in {"NO", "SELL", "SHORT"}:
        same_side_depth = sum(size for _, size in bids)
        opposite_side_depth = sum(size for _, size in asks)
    else:
        return DynamicDriftThresholdResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "side", "issue": "unsupported_value", "value": side},
            max_drift_ratio=None,
        )
    if same_side_depth <= 0.0 or opposite_side_depth <= 0.0:
        return DynamicDriftThresholdResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "depth", "issue": "non_positive"},
            max_drift_ratio=None,
        )

    midpoint = (best_bid + best_ask) / 2.0
    if midpoint <= 0.0:
        return DynamicDriftThresholdResult(
            allowed=False,
            reason="invalid_market_data",
            details={"field": "spread", "issue": "invalid_midpoint"},
            max_drift_ratio=None,
        )
    spread_ratio = (best_ask - best_bid) / midpoint
    depth_imbalance = abs(same_side_depth - opposite_side_depth) / (same_side_depth + opposite_side_depth)
    volatility_factor = float(volatility) if volatility is not None else 0.0
    stress_score = min(1.0, (spread_ratio * 8.0) + (depth_imbalance * 0.7) + (volatility_factor * 0.8))

    floor_ratio = float(base_max_drift_ratio) * 0.15
    dynamic_ratio = max(floor_ratio, float(base_max_drift_ratio) * (1.0 - (0.90 * stress_score)))
    dynamic_ratio = min(float(base_max_drift_ratio), dynamic_ratio)

    return DynamicDriftThresholdResult(
        allowed=True,
        reason=None,
        details={
            "spread_ratio": spread_ratio,
            "depth_imbalance": depth_imbalance,
            "volatility": volatility_factor,
            "stress_score": stress_score,
            "floor_ratio": floor_ratio,
        },
        max_drift_ratio=dynamic_ratio,
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
