from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SmartMoneySignal:
    strength: float
    confidence: float


@dataclass(frozen=True)
class MomentumSignal:
    direction: str
    strength: float


@dataclass(frozen=True)
class FalconSignal:
    signal_type: str
    strength: float
    confidence: float
    liquidity_score: float
    external_signal_weight: float


@dataclass(frozen=True)
class FalconSignalContext:
    smart_money_signal: SmartMoneySignal
    momentum_signal: MomentumSignal
    liquidity_score: float
    falcon_signal: FalconSignal | None
    data_sufficient: bool
    insufficiency_reason: str | None


def detect_smart_money_signal(
    trades: list[dict[str, Any]],
    *,
    large_trade_threshold: float = 1_500.0,
    repeated_wallet_min_count: int = 2,
) -> SmartMoneySignal:
    if not trades:
        return SmartMoneySignal(strength=0.0, confidence=0.0)

    sizes = [max(0.0, _to_float(item.get("size") or item.get("amount"), default=0.0)) for item in trades]
    large_trade_count = sum(1 for size in sizes if size >= large_trade_threshold)
    large_trade_ratio = large_trade_count / max(len(sizes), 1)

    wallets = [str(item.get("wallet") or item.get("wallet_address") or "") for item in trades]
    wallet_counts = Counter(wallet for wallet in wallets if wallet)
    repeated_wallet_count = sum(1 for count in wallet_counts.values() if count >= repeated_wallet_min_count)
    repeated_wallet_ratio = repeated_wallet_count / max(len(wallet_counts), 1)

    strength = _clamp((0.65 * large_trade_ratio) + (0.35 * repeated_wallet_ratio), 0.0, 1.0)
    confidence = _clamp((0.60 * large_trade_ratio) + (0.40 * repeated_wallet_ratio), 0.0, 1.0)
    return SmartMoneySignal(strength=round(strength, 6), confidence=round(confidence, 6))


def detect_momentum_signal(candles: list[dict[str, Any]]) -> MomentumSignal:
    closes = [_to_float(item.get("close"), default=0.0) for item in candles if item.get("close") is not None]
    if len(closes) < 3:
        return MomentumSignal(direction="NEUTRAL", strength=0.0)

    start_price = closes[0]
    end_price = closes[-1]
    if start_price <= 0:
        return MomentumSignal(direction="NEUTRAL", strength=0.0)

    trend = (end_price - start_price) / start_price
    latest_step = closes[-1] - closes[-2]
    prev_step = closes[-2] - closes[-3]
    acceleration = latest_step - prev_step

    direction = "UP" if trend > 0 else "DOWN" if trend < 0 else "NEUTRAL"
    strength = _clamp(abs(trend) + (abs(acceleration) / max(abs(start_price), 1e-6)), 0.0, 1.0)
    return MomentumSignal(direction=direction, strength=round(strength, 6))


def compute_liquidity_score(
    orderbook: list[dict[str, Any]],
    *,
    target_depth_usd: float = 20_000.0,
    max_acceptable_spread: float = 0.05,
) -> float:
    if not orderbook:
        return 0.0

    bids = [
        _to_float(item.get("bid") if item.get("bid") is not None else item.get("price"), default=0.0)
        for item in orderbook
        if str(item.get("side", "")).lower() == "bid"
    ]
    asks = [
        _to_float(item.get("ask") if item.get("ask") is not None else item.get("price"), default=0.0)
        for item in orderbook
        if str(item.get("side", "")).lower() == "ask"
    ]

    best_bid = max(bids) if bids else 0.0
    best_ask = min(asks) if asks else 0.0
    spread = max(0.0, best_ask - best_bid) if best_bid > 0.0 and best_ask > 0.0 else max_acceptable_spread

    total_depth = sum(max(0.0, _to_float(item.get("depth") or item.get("size"), default=0.0)) for item in orderbook)
    depth_score = _clamp(total_depth / max(target_depth_usd, 1.0), 0.0, 1.0)
    spread_score = _clamp(1.0 - (spread / max(max_acceptable_spread, 1e-6)), 0.0, 1.0)
    return round(_clamp((0.65 * depth_score) + (0.35 * spread_score), 0.0, 1.0), 6)


def aggregate_falcon_signal(
    *,
    smart_money_signal: SmartMoneySignal,
    momentum_signal: MomentumSignal,
    liquidity_score: float,
    min_signal_score: float = 0.12,
) -> FalconSignal:
    bounded_liquidity = _clamp(liquidity_score, 0.0, 1.0)

    smart_score = smart_money_signal.strength * smart_money_signal.confidence
    momentum_confidence = 0.6 if momentum_signal.direction == "NEUTRAL" else 0.75
    momentum_score = momentum_signal.strength * momentum_confidence
    if max(smart_score, momentum_score) < min_signal_score:
        return FalconSignal(
            signal_type="MOMENTUM",
            strength=0.0,
            confidence=0.0,
            liquidity_score=round(bounded_liquidity, 6),
            external_signal_weight=1.0,
        )

    if smart_score >= momentum_score:
        signal_type = "SMART_MONEY"
        base_strength = smart_money_signal.strength
        base_confidence = smart_money_signal.confidence
    else:
        signal_type = "MOMENTUM"
        base_strength = momentum_signal.strength
        base_confidence = momentum_confidence

    strength = _clamp((0.75 * base_strength) + (0.25 * bounded_liquidity), 0.0, 1.0)
    confidence = _clamp((0.70 * base_confidence) + (0.30 * bounded_liquidity), 0.0, 1.0)

    # Bounded external influence, cannot override core S1/S2/S3 strategy scores.
    external_signal_weight = round(_clamp(1.00 + (0.12 * (confidence - 0.5)) + (0.08 * (strength - 0.5)), 0.90, 1.15), 6)

    return FalconSignal(
        signal_type=signal_type,
        strength=round(strength, 6),
        confidence=round(confidence, 6),
        liquidity_score=round(bounded_liquidity, 6),
        external_signal_weight=external_signal_weight,
    )


def build_falcon_signal_context(
    *,
    trades: list[dict[str, Any]] | None,
    candles: list[dict[str, Any]] | None,
    orderbook: list[dict[str, Any]] | None,
) -> FalconSignalContext:
    safe_trades = trades or []
    safe_candles = candles or []
    safe_orderbook = orderbook or []
    data_sufficient, insufficiency_reason = _has_sufficient_falcon_data(
        trades=safe_trades,
        candles=safe_candles,
        orderbook=safe_orderbook,
    )

    smart_money = detect_smart_money_signal(safe_trades)
    momentum = detect_momentum_signal(safe_candles)
    liquidity = compute_liquidity_score(safe_orderbook)
    falcon_signal = (
        aggregate_falcon_signal(
            smart_money_signal=smart_money,
            momentum_signal=momentum,
            liquidity_score=liquidity,
        )
        if data_sufficient
        else None
    )

    return FalconSignalContext(
        smart_money_signal=smart_money,
        momentum_signal=momentum,
        liquidity_score=liquidity,
        falcon_signal=falcon_signal,
        data_sufficient=data_sufficient,
        insufficiency_reason=insufficiency_reason,
    )


def _to_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _has_sufficient_falcon_data(
    *,
    trades: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    orderbook: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    has_trade_signal = len(trades) >= 2
    close_count = sum(1 for item in candles if item.get("close") is not None)
    has_momentum_signal = close_count >= 3
    bid_count = sum(1 for item in orderbook if str(item.get("side", "")).lower() == "bid")
    ask_count = sum(1 for item in orderbook if str(item.get("side", "")).lower() == "ask")
    has_liquidity_signal = bid_count > 0 and ask_count > 0
    sufficient = has_trade_signal or has_momentum_signal or has_liquidity_signal
    if sufficient:
        return True, None
    return False, "insufficient_falcon_data"
