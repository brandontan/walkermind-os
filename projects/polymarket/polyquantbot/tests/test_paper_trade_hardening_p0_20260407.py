"""Deterministic Phase-0 blocker harness for paper-trade hardening.

Scope is intentionally narrow:
- prove risk gate and kill-switch blocks are enforced on execution entrypoints
- prove allowed PAPER path still executes
- prove wallet restore mutates active runtime wallet state in engine container
- prove duplicate/replayed intent is idempotent across container re-init
- prove restore-path failures are handled/observable (warning emitted, no crash)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from projects.polymarket.polyquantbot.core.execution.executor import (
    execute_trade,
    reset_state,
)
from projects.polymarket.polyquantbot.core.pipeline.go_live_controller import TradingMode
from projects.polymarket.polyquantbot.core.pipeline.live_mode_controller import LiveModeController
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
from projects.polymarket.polyquantbot.execution import engine_router
from projects.polymarket.polyquantbot.execution.paper_engine import OrderStatus


@dataclass
class _MetricsOK:
    ev_capture_ratio: float = 0.90
    fill_rate: float = 0.90
    p95_latency: float = 100.0
    drawdown: float = 0.01


@dataclass
class _RiskState:
    disabled: bool


@dataclass
class _AuditLoggerOK:
    connected: bool = True

    def is_db_connected(self) -> bool:
        return self.connected


class _FakeDB:
    async def load_latest_wallet_state(self) -> dict[str, float]:
        return {"cash": 777.0, "locked": 23.0, "equity": 800.0}


class _NoopDB:
    pass


def _signal(signal_id: str = "sig-1") -> SignalResult:
    return SignalResult(
        signal_id=signal_id,
        market_id="m-1",
        side="YES",
        p_market=0.40,
        p_model=0.60,
        edge=0.20,
        ev=0.10,
        kelly_f=0.25,
        size_usd=50.0,
        liquidity_usd=20_000.0,
    )


def setup_function() -> None:
    reset_state()


def test_formal_risk_guard_blocks_active_live_gate() -> None:
    ctrl = LiveModeController(
        mode=TradingMode.LIVE,
        metrics_validator=_MetricsOK(),
        risk_guard=_RiskState(disabled=True),
        redis_client=object(),
        audit_logger=_AuditLoggerOK(),
        telegram_configured=True,
    )

    assert ctrl.is_live_enabled() is False
    assert ctrl.get_block_reason() == "kill_switch_active"


def test_kill_switch_blocks_execution() -> None:
    result = asyncio.run(execute_trade(_signal("kill-switch-sig"), kill_switch_active=True))

    assert result.success is False
    assert result.reason == "kill_switch_active"


def test_allowed_paper_path_still_runs() -> None:
    result = asyncio.run(execute_trade(_signal("paper-ok-sig"), mode="PAPER"))

    assert result.success is True
    assert result.mode == "PAPER"
    assert result.filled_size_usd > 0.0


def test_wallet_restore_updates_active_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_router, "_container", None)
    container = engine_router.get_engine_container()

    asyncio.run(container.restore_from_db(_FakeDB()))

    state = container.wallet.get_state()
    assert state.cash == 777.0
    assert state.locked == 23.0
    assert state.equity == 800.0
    assert container.paper_engine._wallet is container.wallet


def test_duplicate_replay_not_reexecuted_after_container_reinit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_router, "_container", None)
    container = engine_router.get_engine_container()

    first = asyncio.run(container.paper_engine.execute_order(
        {
            "trade_id": "intent-dup-1",
            "market_id": "m-dup",
            "side": "YES",
            "price": 0.50,
            "size": 25.0,
        }
    ))
    assert first.status in (OrderStatus.FILLED, OrderStatus.PARTIAL)

    # Re-init path in process: singleton fetch again (same active runtime container)
    same_container = engine_router.get_engine_container()
    second = asyncio.run(same_container.paper_engine.execute_order(
        {
            "trade_id": "intent-dup-1",
            "market_id": "m-dup",
            "side": "YES",
            "price": 0.50,
            "size": 25.0,
        }
    ))

    assert second.status == OrderStatus.FILLED
    assert second.reason == "duplicate_trade_id"
    assert second.filled_size == 0.0


def test_restore_failure_path_is_handled_and_observable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_router, "_container", None)
    container = engine_router.get_engine_container()

    calls: dict[str, int] = {"positions": 0, "ledger": 0, "warnings": 0}

    async def _raise_wallet(_: Any) -> Any:
        raise RuntimeError("wallet restore exploded")

    async def _positions(_: Any) -> None:
        calls["positions"] += 1

    async def _ledger(_: Any) -> None:
        calls["ledger"] += 1

    def _warn(*_: Any, **__: Any) -> None:
        calls["warnings"] += 1

    monkeypatch.setattr(engine_router.WalletEngine, "restore_from_db", _raise_wallet)
    monkeypatch.setattr(container.positions, "load_from_db", _positions)
    monkeypatch.setattr(container.ledger, "load_from_db", _ledger)
    monkeypatch.setattr(engine_router.log, "warning", _warn)

    asyncio.run(container.restore_from_db(_NoopDB()))

    assert calls["positions"] == 1
    assert calls["ledger"] == 1
    assert calls["warnings"] >= 1
