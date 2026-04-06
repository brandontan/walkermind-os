from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from projects.polymarket.polyquantbot.core.pipeline.trading_loop import run_trading_loop
from projects.polymarket.polyquantbot.execution.engine_router import EngineContainer
from projects.polymarket.polyquantbot.execution.paper_engine import PaperEngine
from projects.polymarket.polyquantbot.core.wallet_engine import WalletEngine
from projects.polymarket.polyquantbot.core.positions import PaperPositionManager
from projects.polymarket.polyquantbot.core.ledger import TradeLedger
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult


class _RiskGuardStub:
    def __init__(self, *, disabled: bool = False, disable_on_check: bool = False) -> None:
        self.disabled = disabled
        self._disable_on_check = disable_on_check

    async def check_daily_loss(self, current_pnl: float) -> None:
        if self._disable_on_check:
            self.disabled = True

    async def check_drawdown(self, peak_balance: float, current_balance: float) -> None:
        return None

    async def check_exposure(self, total_exposure: float, balance: float) -> None:
        return None


class _DBMock:
    def __init__(self) -> None:
        self.upsert_position = AsyncMock(return_value=True)
        self.insert_trade = AsyncMock(return_value=True)
        self.update_trade_status = AsyncMock(return_value=True)
        self.get_positions = AsyncMock(return_value=[])
        self.get_recent_trades = AsyncMock(return_value=[])
        self.reserve_trade_intent = AsyncMock(return_value=True)
        self.update_trade_intent_status = AsyncMock(return_value=True)


def _signal() -> SignalResult:
    return SignalResult(
        signal_id="sig-hardening-1",
        market_id="mkt-hardening-1",
        side="YES",
        p_market=0.40,
        p_model=0.65,
        edge=0.25,
        ev=0.40,
        kelly_f=0.25,
        size_usd=50.0,
        liquidity_usd=100_000.0,
    )


def test_risk_guard_block_prevents_execution_mutation() -> None:
    stop = asyncio.Event()

    async def fake_sleep(_: float) -> None:
        stop.set()

    db = _DBMock()
    risk_guard = _RiskGuardStub(disabled=True)
    execute_mock = AsyncMock()
    paper_engine = SimpleNamespace(execute_order=AsyncMock())

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[{"market_id": "mkt-hardening-1", "p_market": 0.4}]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[_signal()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.execute_trade",
            new=execute_mock,
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        asyncio.run(run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
            db=db,
            paper_engine=paper_engine,
            risk_guard=risk_guard,
        ))

    paper_engine.execute_order.assert_not_awaited()
    execute_mock.assert_not_awaited()
    db.upsert_position.assert_not_awaited()
    db.insert_trade.assert_not_awaited()


def test_kill_switch_flip_during_risk_check_blocks_execution() -> None:
    stop = asyncio.Event()

    async def fake_sleep(_: float) -> None:
        stop.set()

    db = _DBMock()
    risk_guard = _RiskGuardStub(disable_on_check=True)
    paper_engine = SimpleNamespace(execute_order=AsyncMock())

    with (
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
            new=AsyncMock(return_value=[{"market_id": "mkt-hardening-1", "p_market": 0.4}]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
            new=AsyncMock(return_value=[_signal()]),
        ),
        patch(
            "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
            new=fake_sleep,
        ),
    ):
        asyncio.run(run_trading_loop(
            loop_interval_s=0,
            bankroll=1000.0,
            mode="PAPER",
            stop_event=stop,
            db=db,
            paper_engine=paper_engine,
            risk_guard=risk_guard,
        ))

    paper_engine.execute_order.assert_not_awaited()
    db.update_trade_intent_status.assert_awaited()


def test_engine_container_restore_assigns_restored_wallet() -> None:
    container = EngineContainer()
    restored_wallet = WalletEngine(initial_balance=2222.0)
    db = object()

    with (
        patch(
            "projects.polymarket.polyquantbot.execution.engine_router.WalletEngine.restore_from_db",
            new=AsyncMock(return_value=restored_wallet),
        ),
        patch.object(container.positions, "load_from_db", new=AsyncMock(return_value=None)),
        patch.object(container.ledger, "load_from_db", new=AsyncMock(return_value=None)),
        patch.object(PaperEngine, "hydrate_processed_trade_ids", new=AsyncMock(return_value=None)),
    ):
        asyncio.run(container.restore_from_db(db))

    assert container.wallet is restored_wallet
    assert container.paper_engine._wallet is restored_wallet


def test_paper_engine_hydrates_dedup_ids_and_blocks_replay() -> None:
    wallet = WalletEngine(initial_balance=5000.0)
    positions = PaperPositionManager()
    ledger = TradeLedger()
    engine = PaperEngine(wallet=wallet, positions=positions, ledger=ledger, random_seed=1)

    class _DedupDB:
        async def load_reserved_trade_ids(self, limit: int = 5000) -> list[str]:
            return ["dup-intent-1"]

    asyncio.run(engine.hydrate_processed_trade_ids(_DedupDB()))
    result = asyncio.run(engine.execute_order(
        {
            "trade_id": "dup-intent-1",
            "market_id": "mkt-dup",
            "side": "YES",
            "price": 0.5,
            "size": 10.0,
        }
    ))

    assert result.reason == "duplicate_trade_id"


def test_no_silent_exception_swallow_in_close_alert_paths() -> None:
    target_file = "projects/polymarket/polyquantbot/core/pipeline/trading_loop.py"
    with open(target_file, encoding="utf-8") as handle:
        content = handle.read()
    assert "except Exception:\n                                            pass" not in content
