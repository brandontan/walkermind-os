from __future__ import annotations

import asyncio
import time

from execution.drift_guard import compute_dynamic_drift_threshold
from execution.engine import ExecutionEngine
from execution.utils import compute_execution_size, simulate_vwap_execution


def _book(*, bids: list[dict[str, float]] | None = None, asks: list[dict[str, float]] | None = None) -> dict[str, list[dict[str, float]]]:
    return {
        "bids": bids if bids is not None else [{"price": 0.49, "size": 400.0}, {"price": 0.48, "size": 600.0}],
        "asks": asks if asks is not None else [{"price": 0.51, "size": 500.0}, {"price": 0.52, "size": 600.0}],
    }


def _market_data(*, model_probability: float = 0.70, orderbook: dict[str, list[dict[str, float]]] | None = None) -> dict[str, object]:
    return {
        "timestamp": time.time(),
        "model_probability": model_probability,
        "orderbook": orderbook if orderbook is not None else _book(),
    }


def test_p18_slippage_aware_sizing_reduces_size_under_thin_liquidity() -> None:
    orderbook = _book(
        asks=[
            {"price": 0.51, "size": 20.0},
            {"price": 0.55, "size": 40.0},
            {"price": 0.60, "size": 100.0},
        ]
    )
    result = compute_execution_size(orderbook, 100.0, 0.02, side="YES")
    assert result.allowed is True
    assert result.filled_size == 20.0
    assert result.remaining_size == 80.0
    assert result.vwap_price == 0.51


def test_p18_vwap_execution_multi_level_book() -> None:
    orderbook = _book(
        asks=[
            {"price": 0.51, "size": 40.0},
            {"price": 0.52, "size": 60.0},
            {"price": 0.54, "size": 100.0},
        ]
    )
    result = simulate_vwap_execution(orderbook, 100.0, "YES")
    assert result.allowed is True
    assert result.filled_size == 100.0
    assert result.remaining_size == 0.0
    assert abs((result.vwap_price or 0.0) - 0.516) < 1e-9


def test_p18_dynamic_drift_threshold_adjusts_with_spread_and_depth() -> None:
    base = 0.02
    balanced = _book(
        bids=[{"price": 0.499, "size": 800.0}, {"price": 0.498, "size": 800.0}],
        asks=[{"price": 0.501, "size": 800.0}, {"price": 0.502, "size": 800.0}],
    )
    stressed = _book(
        bids=[{"price": 0.45, "size": 80.0}, {"price": 0.44, "size": 50.0}],
        asks=[{"price": 0.55, "size": 900.0}, {"price": 0.56, "size": 900.0}],
    )
    threshold_balanced = compute_dynamic_drift_threshold(orderbook=balanced, base_threshold=base)
    threshold_stressed = compute_dynamic_drift_threshold(orderbook=stressed, base_threshold=base)
    assert threshold_balanced >= threshold_stressed
    assert threshold_balanced <= (base * 1.25)
    assert threshold_stressed >= (base * 0.60)


def test_p18_engine_partial_fill_size_adjustment_is_applied() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0)
    proof = engine.build_validation_proof(
        condition_id="mkt-1",
        side="YES",
        price_snapshot=0.51,
        size=100.0,
        created_at=time.time(),
    )
    # Crossing deeper levels breaches slippage tolerance, so sizing is reduced.
    thin_orderbook = _book(
        asks=[{"price": 0.51, "size": 20.0}, {"price": 0.60, "size": 500.0}],
        bids=[{"price": 0.49, "size": 500.0}],
    )
    opened = asyncio.run(
        engine.open_position(
            market="mkt-1",
            market_title="market",
            side="YES",
            price=0.51,
            size=100.0,
            validation_proof=proof,
            execution_market_data=_market_data(orderbook=thin_orderbook, model_probability=0.8),
        )
    )
    assert opened is not None
    assert opened.size == 20.0
    assert opened.entry_price == 0.51


def test_p18_engine_keeps_fail_closed_rejections_for_invalid_stale_and_ev_negative() -> None:
    # invalid market data
    invalid_engine = ExecutionEngine(starting_equity=10_000.0)
    invalid_proof = invalid_engine.build_validation_proof(
        condition_id="mkt-invalid",
        side="YES",
        price_snapshot=0.50,
        size=100.0,
        created_at=time.time(),
    )
    invalid_opened = asyncio.run(
        invalid_engine.open_position(
            market="mkt-invalid",
            market_title="market",
            side="YES",
            price=0.51,
            size=100.0,
            validation_proof=invalid_proof,
            execution_market_data=None,
        )
    )
    assert invalid_opened is None
    assert (invalid_engine.get_last_open_rejection() or {}).get("reason") == "invalid_market_data"

    # stale data
    stale_engine = ExecutionEngine(starting_equity=10_000.0, max_market_data_age_seconds=1.0)
    stale_proof = stale_engine.build_validation_proof(
        condition_id="mkt-stale",
        side="YES",
        price_snapshot=0.50,
        size=100.0,
        created_at=time.time(),
    )
    stale_opened = asyncio.run(
        stale_engine.open_position(
            market="mkt-stale",
            market_title="market",
            side="YES",
            price=0.51,
            size=100.0,
            validation_proof=stale_proof,
            execution_market_data={
                "timestamp": time.time() - 100.0,
                "model_probability": 0.70,
                "orderbook": _book(),
            },
        )
    )
    assert stale_opened is None
    assert (stale_engine.get_last_open_rejection() or {}).get("reason") == "stale_data"

    # EV negative after vwap pricing
    ev_engine = ExecutionEngine(starting_equity=10_000.0)
    ev_proof = ev_engine.build_validation_proof(
        condition_id="mkt-ev",
        side="YES",
        price_snapshot=0.50,
        size=100.0,
        created_at=time.time(),
    )
    ev_opened = asyncio.run(
        ev_engine.open_position(
            market="mkt-ev",
            market_title="market",
            side="YES",
            price=0.51,
            size=100.0,
            validation_proof=ev_proof,
            execution_market_data=_market_data(model_probability=0.40),
        )
    )
    assert ev_opened is None
    assert (ev_engine.get_last_open_rejection() or {}).get("reason") == "ev_negative"
