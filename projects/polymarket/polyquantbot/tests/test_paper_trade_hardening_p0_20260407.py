from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from projects.polymarket.polyquantbot.core.pipeline import trading_loop
from projects.polymarket.polyquantbot.execution.engine_router import EngineContainer
from projects.polymarket.polyquantbot.execution.paper_engine import OrderStatus
from projects.polymarket.polyquantbot.risk.risk_guard import RiskGuard


class _StubDB:
    def __init__(self) -> None:
        self.positions: list[dict[str, Any]] = []
        self.trades: list[dict[str, Any]] = []

    async def get_positions(self, _user_id: str) -> list[dict[str, Any]]:
        return self.positions

    async def upsert_position(self, pos: dict[str, Any]) -> bool:
        self.positions = [p for p in self.positions if p.get("market_id") != pos.get("market_id")]
        self.positions.append(pos)
        return True

    async def insert_trade(self, trade: dict[str, Any]) -> bool:
        self.trades.append(trade)
        return True

    async def update_trade_status(self, *_args: Any, **_kwargs: Any) -> bool:
        return True

    async def get_recent_trades(self, limit: int = 500) -> list[dict[str, Any]]:
        return self.trades[-limit:]


class _StubWallet:
    async def persist(self, _db: Any) -> None:
        return None


class _StubPositions:
    async def save_to_db(self, _db: Any) -> None:
        return None

    def get_all_open(self) -> list[Any]:
        return []

    def update_price(self, _market_id: str, _price: float) -> None:
        return None


class _StubPaperEngine:
    def __init__(self) -> None:
        self.calls = 0
        self._wallet = _StubWallet()
        self._positions = _StubPositions()

    async def execute_order(self, order: dict[str, Any]) -> Any:
        self.calls += 1
        return SimpleNamespace(
            trade_id=order["trade_id"],
            market_id=order["market_id"],
            side=order["side"],
            requested_size=order["size"],
            filled_size=order["size"],
            fill_price=order["price"],
            status=OrderStatus.FILLED,
            reason="",
        )


def _install_single_tick_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get_active_markets() -> list[dict[str, Any]]:
        return [{"market_id": "mkt-1", "p_market": 0.55}]

    async def _apply_scope(markets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return markets, {
            "selection_type": "All Markets",
            "enabled_categories": ["all"],
            "fallback_applied_count": 0,
            "all_markets_enabled": True,
        }

    async def _generate_signals(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(
                signal_id="sig-001",
                market_id="mkt-1",
                side="YES",
                p_market=0.55,
                size_usd=10.0,
                p_model=0.65,
                ev=0.05,
                extra={"strategy_id": "test", "decision_reason": "unit_test"},
            )
        ]

    monkeypatch.setattr(trading_loop, "get_active_markets", _get_active_markets)
    monkeypatch.setattr(trading_loop, "apply_market_scope", _apply_scope)
    monkeypatch.setattr(trading_loop, "ingest_markets", lambda markets: markets)
    monkeypatch.setattr(trading_loop, "generate_signals", _generate_signals)


def test_kill_switch_blocks_active_paper_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_single_tick_mocks(monkeypatch)
    db = _StubDB()
    paper_engine = _StubPaperEngine()
    guard = RiskGuard()
    guard.disabled = True

    stop_event = asyncio.Event()
    stop_event.set()
    # run one tick with stop unset after startup check
    stop_event.clear()

    async def _get_once() -> list[dict[str, Any]]:
        stop_event.set()
        return [{"market_id": "mkt-1", "p_market": 0.55}]

    monkeypatch.setattr(trading_loop, "get_active_markets", _get_once)

    asyncio.run(
        trading_loop.run_trading_loop(
            db=db,
            mode="PAPER",
            user_id="u1",
            paper_engine=paper_engine,
            risk_guard=guard,
            stop_event=stop_event,
            loop_interval_s=0.01,
        )
    )

    assert paper_engine.calls == 0


def test_allowed_paper_path_executes_when_risk_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_single_tick_mocks(monkeypatch)
    db = _StubDB()
    paper_engine = _StubPaperEngine()
    guard = RiskGuard(daily_loss_limit=-2000.0)
    stop_event = asyncio.Event()

    async def _get_once() -> list[dict[str, Any]]:
        stop_event.set()
        return [{"market_id": "mkt-1", "p_market": 0.55}]

    monkeypatch.setattr(trading_loop, "get_active_markets", _get_once)

    asyncio.run(
        trading_loop.run_trading_loop(
            db=db,
            mode="PAPER",
            user_id="u1",
            paper_engine=paper_engine,
            risk_guard=guard,
            stop_event=stop_event,
            loop_interval_s=0.01,
        )
    )

    assert paper_engine.calls == 1


def test_restore_rebinds_runtime_wallet_and_hydrates_dedup() -> None:
    container = EngineContainer()

    class _RestoreDB:
        async def load_latest_wallet_state(self) -> dict[str, float]:
            return {"cash": 7777.0, "locked": 10.0, "equity": 7787.0}

        async def load_open_paper_positions(self) -> list[dict[str, Any]]:
            return []

        async def load_ledger_entries(self, limit: int = 5000) -> list[dict[str, Any]]:
            _ = limit
            return [
                {
                    "trade_id": "persisted-dup-1",
                    "market_id": "mkt-1",
                    "action": "OPEN",
                    "price": 0.5,
                    "size": 10.0,
                    "fee": 0.0,
                    "ledger_ts": "2026-04-07T00:00:00Z",
                }
            ]

    db = _RestoreDB()
    old_wallet_ref = container.paper_engine._wallet

    asyncio.run(container.restore_from_db(db))

    assert container.paper_engine._wallet is container.wallet
    assert container.paper_engine._wallet is not old_wallet_ref
    assert container.wallet.get_state().cash == 7777.0

    result = asyncio.run(
        container.paper_engine.execute_order(
            {
                "trade_id": "persisted-dup-1",
                "market_id": "mkt-1",
                "side": "YES",
                "price": 0.5,
                "size": 10.0,
            }
        )
    )
    assert result.reason == "duplicate_trade_id"


def test_restore_failure_is_observable_and_non_fatal() -> None:
    container = EngineContainer()

    class _FailingDB:
        async def load_latest_wallet_state(self) -> dict[str, Any]:
            raise RuntimeError("wallet restore failure test")

        async def load_open_paper_positions(self) -> list[dict[str, Any]]:
            raise RuntimeError("position restore failure test")

        async def load_ledger_entries(self, limit: int = 5000) -> list[dict[str, Any]]:
            _ = limit
            raise RuntimeError("ledger restore failure test")

    asyncio.run(container.restore_from_db(_FailingDB()))
