from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.execution_isolation import (
    ExecutionIsolationGateway,
    get_execution_isolation_gateway,
)
from projects.polymarket.polyquantbot.execution.proof_lifecycle import new_validation_proof
from projects.polymarket.polyquantbot.execution.strategy_trigger import StrategyConfig, StrategyTrigger


def _valid_market_data(reference_price: float = 0.41) -> dict[str, object]:
    return {
        "timestamp": time.time(),
        "model_probability": 0.62,
        "orderbook": {
            "asks": [[reference_price, 500.0], [reference_price + 0.01, 500.0]],
            "bids": [[reference_price - 0.01, 500.0]],
        },
        "volatility": 0.1,
    }


def test_phase3_resolver_bridge_startup_paths_remain_read_only() -> None:
    resolver_source = Path("projects/polymarket/polyquantbot/platform/context/resolver.py").read_text(encoding="utf-8")
    bridge_source = Path("projects/polymarket/polyquantbot/legacy/adapters/context_bridge.py").read_text(encoding="utf-8")
    main_source = Path("projects/polymarket/polyquantbot/main.py").read_text(encoding="utf-8")

    assert "resolve_user_account(" in resolver_source
    assert "ensure_user_account(" not in resolver_source
    assert "AuditEventRecord" not in bridge_source
    assert "platform_context_bridge_audit_suppressed" in bridge_source
    assert "engine_container.restore_from_db" in main_source


def test_phase3_autonomous_and_manual_paths_route_through_isolation_gateway() -> None:
    trigger_source = Path("projects/polymarket/polyquantbot/execution/strategy_trigger.py").read_text(encoding="utf-8")
    command_source = Path("projects/polymarket/polyquantbot/telegram/command_handler.py").read_text(encoding="utf-8")

    assert "self._execution_gateway.open_position(" in trigger_source
    assert "self._execution_gateway.close_position(" in trigger_source
    assert "self._engine.open_position(" not in trigger_source
    assert "self._engine.close_position(" not in trigger_source
    assert "execution_gateway.close_position(" in command_source
    assert "execution_gateway=execution_gateway" in command_source
    assert "execution.command_handler.trade_open.manual" in command_source
    assert "execution.strategy_trigger.autonomous" in trigger_source


def test_phase3_open_source_default_and_manual_are_distinct() -> None:
    trigger = StrategyTrigger(
        engine=ExecutionEngine(starting_equity=10_000.0),
        config=StrategyConfig(market_id="m-source"),
    )
    assert trigger._resolve_open_source(None) == "execution.strategy_trigger.autonomous"  # noqa: SLF001
    assert (
        trigger._resolve_open_source({"open_source": "execution.command_handler.trade_open.manual"})  # noqa: SLF001
        == "execution.command_handler.trade_open.manual"
    )


def test_phase3_open_rejection_payload_is_flat_and_keeps_sibling_metadata() -> None:
    trigger = StrategyTrigger(
        engine=ExecutionEngine(starting_equity=10_000.0),
        config=StrategyConfig(market_id="m-rejection"),
    )
    normalized = trigger._normalize_open_rejection_payload(  # noqa: SLF001
        {
            "engine_rejection": {"reason": "max_position_size_exceeded", "limit": 100.0},
            "source_path": "execution.command_handler.trade_open.manual",
            "attempt_id": "attempt-1",
        },
        fallback_reason="execution_open_position_rejected",
    )
    assert normalized["reason"] == "max_position_size_exceeded"
    assert normalized["limit"] == 100.0
    assert normalized["source_path"] == "execution.command_handler.trade_open.manual"
    assert normalized["attempt_id"] == "attempt-1"


def test_phase3_isolation_boundary_rejects_bypass_without_risk_or_proof() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        gateway = get_execution_isolation_gateway(engine)

        blocked = await gateway.open_position(
            source_path="tests.direct_bypass",
            market="m-bypass",
            market_title="Bypass",
            side="YES",
            price=0.41,
            size=100.0,
            position_id="bypass-1",
            position_context={"strategy_source": "TEST"},
            execution_market_data=_valid_market_data(),
            validation_proof=None,
            risk_decision="ALLOW",
            risk_reason="ok",
        )
        assert blocked.allowed is False
        assert blocked.reason == "validation_proof_required"

        snapshot = await engine.snapshot()
        assert len(snapshot.positions) == 0

    asyncio.run(_run())


def test_phase3_isolation_boundary_enforces_risk_then_preserves_execution_truth() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        gateway = get_execution_isolation_gateway(engine)

        blocked_risk = await gateway.open_position(
            source_path="tests.risk_block",
            market="m-risk",
            market_title="Risk Block",
            side="YES",
            price=0.41,
            size=100.0,
            position_id="risk-1",
            position_context={"strategy_source": "TEST"},
            execution_market_data=_valid_market_data(),
            validation_proof=None,
            risk_decision="BLOCK",
            risk_reason="pre_trade_validator_block",
        )
        assert blocked_risk.allowed is False
        assert blocked_risk.reason == "risk_decision_not_allow"

        proof = engine.build_validation_proof(
            condition_id="m-success",
            side="YES",
            price_snapshot=0.41,
            size=100.0,
            market_type="normal",
            volatility_proxy=0.1,
        )
        opened = await gateway.open_position(
            source_path="tests.allow",
            market="m-success",
            market_title="Success",
            side="YES",
            price=0.41,
            size=100.0,
            position_id="allow-1",
            position_context={"strategy_source": "TEST", "trade_id": "allow-1"},
            execution_market_data=_valid_market_data(),
            validation_proof=proof,
            risk_decision="ALLOW",
            risk_reason="ok",
        )
        assert opened.allowed is True
        assert opened.position is not None

        close_blocked = await gateway.close_position(
            source_path="tests.close_block",
            position=opened.position,
            close_price=0.5,
            close_context={},
            terminal_reason="",
        )
        assert close_blocked.allowed is False
        assert close_blocked.reason == "terminal_reason_required"

        closed = await gateway.close_position(
            source_path="tests.close_allow",
            position=opened.position,
            close_price=0.5,
            close_context={"exit_reason": "take_profit"},
            terminal_reason="take_profit",
        )
        assert closed.allowed is True
        assert isinstance(closed.realized_pnl, float)

        assert len(engine._closed_trades) == 1  # noqa: SLF001
        assert engine._closed_trades[0]["position_id"] == "allow-1"  # noqa: SLF001
        assert engine._closed_trades[0]["exit_reason"] == "take_profit"  # noqa: SLF001

    asyncio.run(_run())


def test_phase3_isolation_open_lock_keeps_rejection_reason_per_call() -> None:
    class _RaceEngine:
        def __init__(self) -> None:
            self._last_open_rejection: dict[str, object] | None = None

        async def open_position(self, **kwargs: object) -> None:
            position_id = str(kwargs.get("position_id", "unknown"))
            self._last_open_rejection = {"reason": f"reject_{position_id}"}
            await asyncio.sleep(0.01)
            return None

        def get_last_open_rejection(self) -> dict[str, object] | None:
            return dict(self._last_open_rejection or {})

    async def _run() -> None:
        gateway = ExecutionIsolationGateway(engine=_RaceEngine())  # type: ignore[arg-type]
        proof_a = new_validation_proof(
            condition_id="m-lock-a",
            side="YES",
            price_snapshot=0.41,
            size=10.0,
            ttl_seconds=30,
        )
        proof_b = new_validation_proof(
            condition_id="m-lock-b",
            side="YES",
            price_snapshot=0.41,
            size=10.0,
            ttl_seconds=30,
        )

        outcome_a, outcome_b = await asyncio.gather(
            gateway.open_position(
                source_path="tests.lock.a",
                market="m-lock-a",
                market_title="Lock A",
                side="YES",
                price=0.41,
                size=10.0,
                position_id="A",
                position_context={},
                execution_market_data=_valid_market_data(),
                validation_proof=proof_a,
                risk_decision="ALLOW",
                risk_reason="ok",
            ),
            gateway.open_position(
                source_path="tests.lock.b",
                market="m-lock-b",
                market_title="Lock B",
                side="YES",
                price=0.41,
                size=10.0,
                position_id="B",
                position_context={},
                execution_market_data=_valid_market_data(),
                validation_proof=proof_b,
                risk_decision="ALLOW",
                risk_reason="ok",
            ),
        )

        assert outcome_a.allowed is False
        assert outcome_b.allowed is False
        assert outcome_a.reason == "reject_A"
        assert outcome_b.reason == "reject_B"

    asyncio.run(_run())
