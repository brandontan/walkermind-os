from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine


def _market_data(*, reference_price: float, model_probability: float, levels: list[tuple[float, float]]) -> dict[str, object]:
    return {
        "reference_price": reference_price,
        "model_probability": model_probability,
        "orderbook": {"asks": levels, "bids": levels},
    }


def test_p17_4_allows_small_price_deviation_within_threshold() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = ExecutionEngine(proof_registry_path=str(Path(temp_dir) / "proofs.db"))
            proof = engine.build_validation_proof(condition_id="MARKET-ALLOW", side="YES", price_snapshot=0.50, size=100.0)
            created = await engine.open_position(
                market="MARKET-ALLOW",
                market_title="Allow",
                side="YES",
                price=0.52,
                size=100.0,
                position_id="allow",
                validation_proof=proof,
                execution_market_data=_market_data(reference_price=0.52, model_probability=0.70, levels=[(0.52, 500.0)]),
            )
            assert created is not None

    asyncio.run(_run())


def test_p17_4_rejects_large_price_deviation() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = ExecutionEngine(proof_registry_path=str(Path(temp_dir) / "proofs.db"))
            proof = engine.build_validation_proof(condition_id="MARKET-DEV", side="YES", price_snapshot=0.50, size=100.0)
            created = await engine.open_position(
                market="MARKET-DEV",
                market_title="Deviation",
                side="YES",
                price=0.55,
                size=100.0,
                position_id="dev",
                validation_proof=proof,
                execution_market_data=_market_data(reference_price=0.55, model_probability=0.75, levels=[(0.55, 500.0)]),
            )
            assert created is None
            assert engine.get_last_open_rejection()["reason"] == "price_deviation"  # type: ignore[index]

    asyncio.run(_run())


def test_p17_4_rejects_when_execution_ev_non_positive() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = ExecutionEngine(proof_registry_path=str(Path(temp_dir) / "proofs.db"))
            proof = engine.build_validation_proof(condition_id="MARKET-EV", side="YES", price_snapshot=0.50, size=100.0)
            created = await engine.open_position(
                market="MARKET-EV",
                market_title="EV",
                side="YES",
                price=0.51,
                size=100.0,
                position_id="ev",
                validation_proof=proof,
                execution_market_data=_market_data(reference_price=0.60, model_probability=0.50, levels=[(0.60, 500.0)]),
            )
            assert created is None
            assert engine.get_last_open_rejection()["reason"] == "ev_negative"  # type: ignore[index]

    asyncio.run(_run())


def test_p17_4_rejects_shallow_depth() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = ExecutionEngine(proof_registry_path=str(Path(temp_dir) / "proofs.db"))
            proof = engine.build_validation_proof(condition_id="MARKET-DEPTH", side="YES", price_snapshot=0.50, size=200.0)
            created = await engine.open_position(
                market="MARKET-DEPTH",
                market_title="Depth",
                side="YES",
                price=0.50,
                size=200.0,
                position_id="depth",
                validation_proof=proof,
                execution_market_data=_market_data(reference_price=0.50, model_probability=0.70, levels=[(0.50, 50.0), (0.51, 50.0)]),
            )
            assert created is None
            assert engine.get_last_open_rejection()["reason"] == "liquidity_insufficient"  # type: ignore[index]

    asyncio.run(_run())


def test_p17_4_rejects_when_vwap_slippage_exceeds_threshold() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = ExecutionEngine(proof_registry_path=str(Path(temp_dir) / "proofs.db"))
            proof = engine.build_validation_proof(condition_id="MARKET-SLIP", side="YES", price_snapshot=0.50, size=100.0)
            created = await engine.open_position(
                market="MARKET-SLIP",
                market_title="Slip",
                side="YES",
                price=0.50,
                size=100.0,
                position_id="slip",
                validation_proof=proof,
                execution_market_data=_market_data(reference_price=0.50, model_probability=0.70, levels=[(0.55, 100.0)]),
            )
            assert created is None
            assert engine.get_last_open_rejection()["reason"] == "liquidity_insufficient"  # type: ignore[index]

    asyncio.run(_run())


def test_p17_4_direct_engine_entry_cannot_bypass_guard() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = ExecutionEngine(proof_registry_path=str(Path(temp_dir) / "proofs.db"))
            proof = engine.build_validation_proof(condition_id="MARKET-DIRECT", side="YES", price_snapshot=0.50, size=100.0)
            created = await engine.open_position(
                market="MARKET-DIRECT",
                market_title="Direct",
                side="YES",
                price=0.55,
                size=100.0,
                position_id="direct",
                validation_proof=proof,
                execution_market_data=_market_data(reference_price=0.55, model_probability=0.75, levels=[(0.55, 500.0)]),
            )
            assert created is None
            assert engine.get_last_open_rejection()["reason"] == "price_deviation"  # type: ignore[index]

    asyncio.run(_run())


def test_p17_4_zero_or_invalid_execution_price_fails_closed() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = ExecutionEngine(proof_registry_path=str(Path(temp_dir) / "proofs.db"))
            proof = engine.build_validation_proof(condition_id="MARKET-INVALID", side="YES", price_snapshot=0.50, size=100.0)
            created = await engine.open_position(
                market="MARKET-INVALID",
                market_title="Invalid",
                side="YES",
                price=0.0,
                size=100.0,
                position_id="invalid",
                validation_proof=proof,
                execution_market_data=_market_data(reference_price=0.0, model_probability=0.70, levels=[(0.50, 500.0)]),
            )
            assert created is None
            assert engine.get_last_open_rejection()["reason"] == "price_deviation"  # type: ignore[index]

    asyncio.run(_run())


def test_p17_4_proof_valid_and_drift_valid_path_succeeds() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = ExecutionEngine(proof_registry_path=str(Path(temp_dir) / "proofs.db"))
            proof = engine.build_validation_proof(condition_id="MARKET-SUCCESS", side="YES", price_snapshot=0.50, size=100.0)
            created = await engine.open_position(
                market="MARKET-SUCCESS",
                market_title="Success",
                side="YES",
                price=0.51,
                size=100.0,
                position_id="success",
                validation_proof=proof,
                execution_market_data=_market_data(reference_price=0.51, model_probability=0.72, levels=[(0.51, 500.0)]),
            )
            assert created is not None

    asyncio.run(_run())
