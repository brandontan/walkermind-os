from __future__ import annotations

from execution.drift_guard import ExecutionDriftGuard


def _orderbook(*, best_bid: float, best_ask: float, bid_size: float, ask_size: float) -> dict[str, object]:
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bids": [[best_bid, bid_size]],
        "asks": [[best_ask, ask_size]],
    }


def test_p17_4_price_deviation_breach_rejected() -> None:
    guard = ExecutionDriftGuard(max_price_deviation_ratio=0.02, max_slippage_ratio=0.02)
    result = guard.validate(
        validated_price=0.50,
        current_orderbook=_orderbook(best_bid=0.53, best_ask=0.54, bid_size=50_000.0, ask_size=50_000.0),
        model_probability=0.65,
        order_size=100.0,
        side="YES",
    )
    assert result.approved is False
    assert result.reason == "price_deviation"


def test_p17_4_ev_flips_negative_rejected() -> None:
    guard = ExecutionDriftGuard(max_price_deviation_ratio=0.50, max_slippage_ratio=0.02)
    result = guard.validate(
        validated_price=0.50,
        current_orderbook=_orderbook(best_bid=0.69, best_ask=0.70, bid_size=100_000.0, ask_size=100_000.0),
        model_probability=0.40,
        order_size=150.0,
        side="YES",
    )
    assert result.approved is False
    assert result.reason == "ev_negative"
    assert float(result.details["ev_new"]) <= 0.0


def test_p17_4_insufficient_liquidity_rejected() -> None:
    guard = ExecutionDriftGuard(max_price_deviation_ratio=0.05, max_slippage_ratio=0.02)
    result = guard.validate(
        validated_price=0.50,
        current_orderbook=_orderbook(best_bid=0.49, best_ask=0.50, bid_size=20.0, ask_size=20.0),
        model_probability=0.65,
        order_size=200.0,
        side="YES",
    )
    assert result.approved is False
    assert result.reason == "liquidity_insufficient"
    assert result.details["sufficient_depth"] is False


def test_p17_4_acceptable_drift_approved() -> None:
    guard = ExecutionDriftGuard(max_price_deviation_ratio=0.03, max_slippage_ratio=0.02)
    result = guard.validate(
        validated_price=0.50,
        current_orderbook={
            "best_bid": 0.499,
            "best_ask": 0.501,
            "bids": [[0.499, 5_000.0], [0.498, 5_000.0]],
            "asks": [[0.501, 5_000.0], [0.502, 5_000.0]],
        },
        model_probability=0.62,
        order_size=250.0,
        side="YES",
    )
    assert result.approved is True
    assert result.reason is None


def test_p17_4_price_deviation_boundary_approved_at_threshold_edge() -> None:
    guard = ExecutionDriftGuard(max_price_deviation_ratio=0.02, max_slippage_ratio=0.02)
    result = guard.validate(
        validated_price=0.50,
        current_orderbook=_orderbook(best_bid=0.509, best_ask=0.51, bid_size=50_000.0, ask_size=50_000.0),
        model_probability=0.70,
        order_size=100.0,
        side="YES",
    )
    assert result.approved is True
