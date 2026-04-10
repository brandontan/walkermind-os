from __future__ import annotations

import asyncio
import time

from execution.engine import ExecutionEngine


def _build_market_data(*, ts: float, model_probability: float | object = 0.60, orderbook: object | None = None) -> dict[str, object]:
    resolved_orderbook = orderbook
    if resolved_orderbook is None:
        resolved_orderbook = {
            "bids": [{"price": 0.49, "size": 1000.0}],
            "asks": [{"price": 0.51, "size": 1000.0}],
        }
    return {
        "timestamp": ts,
        "model_probability": model_probability,
        "orderbook": resolved_orderbook,
    }


def _open_with_boundary_data(
    *,
    engine: ExecutionEngine,
    side: str = "YES",
    price: float = 0.51,
    size: float = 100.0,
    execution_market_data: dict[str, object] | None = None,
):
    proof = engine.build_validation_proof(
        condition_id="mkt-1",
        side=side,
        price_snapshot=0.50,
        size=size,
        market_type="normal",
        created_at=time.time(),
    )
    return asyncio.run(
        engine.open_position(
            market="mkt-1",
            market_title="market",
            side=side,
            price=price,
            size=size,
            validation_proof=proof,
            execution_market_data=execution_market_data,
        )
    )


def _snapshot(engine: ExecutionEngine):
    return asyncio.run(engine.snapshot())


def test_p17_4_missing_execution_market_data_rejected_invalid_market_data() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0)

    created = _open_with_boundary_data(engine=engine, execution_market_data=None)

    assert created is None
    rejection = engine.get_last_open_rejection() or {}
    assert rejection.get("reason") == "invalid_market_data"
    snap = _snapshot(engine)
    assert len(snap.positions) == 0
    assert snap.cash == 10_000.0


def test_p17_4_missing_model_probability_rejected_invalid_market_data() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0)

    created = _open_with_boundary_data(
        engine=engine,
        execution_market_data=_build_market_data(ts=time.time(), model_probability=None),
    )

    assert created is None
    rejection = engine.get_last_open_rejection() or {}
    assert rejection.get("reason") == "invalid_market_data"
    assert rejection.get("field") == "model_probability"
    snap = _snapshot(engine)
    assert len(snap.positions) == 0
    assert snap.cash == 10_000.0


def test_p17_4_malformed_orderbook_rejected_invalid_market_data() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0)

    created = _open_with_boundary_data(
        engine=engine,
        execution_market_data=_build_market_data(
            ts=time.time(),
            orderbook={"bids": "broken", "asks": [{"price": 0.51, "size": 1000.0}]},
        ),
    )

    assert created is None
    rejection = engine.get_last_open_rejection() or {}
    assert rejection.get("reason") == "invalid_market_data"
    assert rejection.get("field") == "orderbook"
    snap = _snapshot(engine)
    assert len(snap.positions) == 0
    assert snap.cash == 10_000.0


def test_p17_4_missing_timestamp_rejected_invalid_market_data() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0)

    created = _open_with_boundary_data(
        engine=engine,
        execution_market_data={
            "model_probability": 0.60,
            "orderbook": {
                "bids": [{"price": 0.49, "size": 1000.0}],
                "asks": [{"price": 0.51, "size": 1000.0}],
            },
        },
    )

    assert created is None
    rejection = engine.get_last_open_rejection() or {}
    assert rejection.get("reason") == "invalid_market_data"
    assert rejection.get("field") == "timestamp"
    snap = _snapshot(engine)
    assert len(snap.positions) == 0
    assert snap.cash == 10_000.0


def test_p17_4_stale_timestamp_rejected_stale_data() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0, max_market_data_age_seconds=5.0)

    created = _open_with_boundary_data(
        engine=engine,
        execution_market_data=_build_market_data(ts=time.time() - 120.0),
    )

    assert created is None
    rejection = engine.get_last_open_rejection() or {}
    assert rejection.get("reason") == "stale_data"
    assert rejection.get("age_seconds", 0.0) > rejection.get("threshold_seconds", 0.0)
    snap = _snapshot(engine)
    assert len(snap.positions) == 0
    assert snap.cash == 10_000.0


def test_p17_4_valid_fresh_market_data_allows_open() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0)

    created = _open_with_boundary_data(
        engine=engine,
        execution_market_data=_build_market_data(ts=time.time(), model_probability=0.65),
    )

    assert created is not None
    rejection = engine.get_last_open_rejection()
    assert rejection is None
    snap = _snapshot(engine)
    assert len(snap.positions) == 1
    assert snap.cash == 9_900.0


def test_p17_4_direct_engine_entry_cannot_bypass_stale_market_data_guard() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0, max_market_data_age_seconds=1.0)

    created = _open_with_boundary_data(
        engine=engine,
        execution_market_data=_build_market_data(ts=time.time() - 10.0, model_probability=0.70),
    )

    assert created is None
    rejection = engine.get_last_open_rejection() or {}
    assert rejection.get("reason") == "stale_data"
    snap = _snapshot(engine)
    assert len(snap.positions) == 0
    assert snap.cash == 10_000.0


def test_p17_4_reference_price_derived_from_orderbook_not_injected_fallback() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0)

    created = _open_with_boundary_data(
        engine=engine,
        price=0.51,
        execution_market_data={
            "timestamp": time.time(),
            "model_probability": 0.65,
            "reference_price": 0.01,
            "orderbook": {
                "bids": [{"price": 0.49, "size": 1000.0}],
                "asks": [{"price": 0.70, "size": 1000.0}],
            },
        },
    )

    assert created is None
    rejection = engine.get_last_open_rejection() or {}
    assert rejection.get("reason") == "price_deviation"
    assert rejection.get("reference_price") == 0.70
    snap = _snapshot(engine)
    assert len(snap.positions) == 0
    assert snap.cash == 10_000.0


def test_p17_4_existing_rejection_paths_still_enforced() -> None:
    # price_deviation
    deviation_engine = ExecutionEngine(starting_equity=10_000.0)
    deviation_created = _open_with_boundary_data(
        engine=deviation_engine,
        price=0.60,
        execution_market_data=_build_market_data(ts=time.time(), model_probability=0.70),
    )
    assert deviation_created is None
    assert (deviation_engine.get_last_open_rejection() or {}).get("reason") == "price_deviation"

    # ev_negative
    ev_engine = ExecutionEngine(starting_equity=10_000.0)
    ev_created = _open_with_boundary_data(
        engine=ev_engine,
        price=0.51,
        execution_market_data=_build_market_data(ts=time.time(), model_probability=0.40),
    )
    assert ev_created is None
    assert (ev_engine.get_last_open_rejection() or {}).get("reason") == "ev_negative"

    # liquidity_insufficient
    liquidity_engine = ExecutionEngine(starting_equity=10_000.0)
    liquidity_created = _open_with_boundary_data(
        engine=liquidity_engine,
        price=0.51,
        execution_market_data=_build_market_data(
            ts=time.time(),
            model_probability=0.65,
            orderbook={"bids": [{"price": 0.49, "size": 1000.0}], "asks": []},
        ),
    )
    assert liquidity_created is None
    assert (liquidity_engine.get_last_open_rejection() or {}).get("reason") == "liquidity_insufficient"
