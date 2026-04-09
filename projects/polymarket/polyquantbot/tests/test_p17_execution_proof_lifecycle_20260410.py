from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine


def test_p17_replay_attempt_fails_single_use_proof() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "proofs.db")
            engine = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
            proof = engine.build_validation_proof(
                condition_id="MARKET-1",
                side="YES",
                price_snapshot=0.45,
                size=100.0,
                market_type="normal",
            )
            first = await engine.open_position(
                market="MARKET-1",
                market_title="M1",
                side="YES",
                price=0.45,
                size=100.0,
                position_id="first",
                validation_proof=proof,
            )
            assert first is not None

            second = await engine.open_position(
                market="MARKET-1",
                market_title="M1",
                side="YES",
                price=0.45,
                size=100.0,
                position_id="second",
                validation_proof=proof,
            )
            assert second is None
            rejection = engine.get_last_open_rejection()
            assert rejection is not None
            assert rejection["reason"] == "validation_proof_status_consumed"

    asyncio.run(_run())


def test_p17_expired_proof_is_rejected() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "proofs.db")
            engine = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
            stale_proof = engine.build_validation_proof(
                condition_id="MARKET-2",
                side="YES",
                price_snapshot=0.44,
                size=80.0,
                market_type="normal",
                created_at=1.0,
            )
            created = await engine.open_position(
                market="MARKET-2",
                market_title="M2",
                side="YES",
                price=0.44,
                size=80.0,
                position_id="expired",
                validation_proof=stale_proof,
            )
            assert created is None
            rejection = engine.get_last_open_rejection()
            assert rejection is not None
            assert rejection["reason"] == "validation_proof_expired"

    asyncio.run(_run())


def test_p17_modified_context_fails_verification() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "proofs.db")
            engine = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
            proof = engine.build_validation_proof(
                condition_id="MARKET-3",
                side="YES",
                price_snapshot=0.52,
                size=90.0,
                market_type="normal",
            )
            created = await engine.open_position(
                market="MARKET-3",
                market_title="M3",
                side="YES",
                price=0.52,
                size=120.0,
                position_id="mismatch",
                validation_proof=proof,
            )
            assert created is None
            rejection = engine.get_last_open_rejection()
            assert rejection is not None
            assert rejection["reason"] == "validation_proof_context_mismatch"

    asyncio.run(_run())


def test_p17_proof_survives_restart_and_enforces_status() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "proofs.db")
            engine_a = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
            proof = engine_a.build_validation_proof(
                condition_id="MARKET-4",
                side="YES",
                price_snapshot=0.48,
                size=100.0,
                market_type="normal",
            )

            engine_b = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
            opened = await engine_b.open_position(
                market="MARKET-4",
                market_title="M4",
                side="YES",
                price=0.48,
                size=100.0,
                position_id="restart-ok",
                validation_proof=proof,
            )
            assert opened is not None

            replay = await engine_b.open_position(
                market="MARKET-4",
                market_title="M4",
                side="YES",
                price=0.48,
                size=100.0,
                position_id="restart-replay",
                validation_proof=proof,
            )
            assert replay is None
            rejection = engine_b.get_last_open_rejection()
            assert rejection is not None
            assert rejection["reason"] == "validation_proof_status_consumed"

    asyncio.run(_run())


def test_p17_race_condition_allows_only_one_consumer() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "proofs.db")
            producer = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
            proof = producer.build_validation_proof(
                condition_id="MARKET-RACE",
                side="YES",
                price_snapshot=0.51,
                size=100.0,
                market_type="normal",
            )
            engine_a = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
            engine_b = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)

            first, second = await asyncio.gather(
                engine_a.open_position(
                    market="MARKET-RACE",
                    market_title="Race",
                    side="YES",
                    price=0.51,
                    size=100.0,
                    position_id="race-a",
                    validation_proof=proof,
                ),
                engine_b.open_position(
                    market="MARKET-RACE",
                    market_title="Race",
                    side="YES",
                    price=0.51,
                    size=100.0,
                    position_id="race-b",
                    validation_proof=proof,
                ),
            )
            success_count = int(first is not None) + int(second is not None)
            assert success_count == 1

    asyncio.run(_run())


def test_p17_no_execution_path_bypasses_proof_verifier() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "proofs.db")
            engine = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
            opened = await engine.open_position(
                market="MARKET-NO-PROOF",
                market_title="No Proof",
                side="YES",
                price=0.49,
                size=100.0,
                position_id="no-proof",
            )
            assert opened is None
            rejection = engine.get_last_open_rejection()
            assert rejection is not None
            assert rejection["reason"] == "validation_proof_required_or_invalid"

    asyncio.run(_run())


def test_p17_ttl_resolver_respects_fast_and_normal_ranges() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "proofs.db")
        engine = ExecutionEngine(starting_equity=10_000.0, proof_registry_path=db_path)
        fast = engine.build_validation_proof(
            condition_id="MARKET-FAST",
            side="YES",
            price_snapshot=0.4,
            size=50.0,
            market_type="fast",
            created_at=100.0,
        )
        normal = engine.build_validation_proof(
            condition_id="MARKET-NORMAL",
            side="YES",
            price_snapshot=0.4,
            size=50.0,
            market_type="normal",
            created_at=100.0,
        )
        assert 5 <= fast.ttl_seconds <= 10
        assert 15 <= normal.ttl_seconds <= 30
