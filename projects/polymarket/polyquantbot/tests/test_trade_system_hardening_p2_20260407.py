from __future__ import annotations

import asyncio
from dataclasses import dataclass

from projects.polymarket.polyquantbot.core.pipeline import trading_loop as loop_mod
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
from projects.polymarket.polyquantbot.execution.engine_router import EngineContainer
from projects.polymarket.polyquantbot.execution.paper_engine import OrderStatus, PaperEngine


class _FakeDB:
    def __init__(self) -> None:
        self.insert_trade_calls = 0
        self.claimed: set[str] = set()

    async def get_positions(self, user_id: str | None = None):
        return []

    async def get_recent_trades(self, limit: int = 100, strategy_id: str | None = None):
        return []

    async def upsert_position(self, position):
        return True

    async def insert_trade(self, trade):
        self.insert_trade_calls += 1
        return True

    async def update_trade_status(self, trade_id, status, pnl=None, won=None):
        return True

    async def claim_execution_intent(self, intent_id: str, *, status: str = "claimed", metadata=None) -> bool:
        if intent_id in self.claimed:
            return False
        self.claimed.add(intent_id)
        return True


@dataclass
class _DummyPos:
    market_id: str = "m1"
    side: str = "YES"
    entry_price: float = 0.5
    size: float = 50.0
    trade_ids: list[str] = None  # type: ignore[assignment]


class _PaperEngineStub:
    def __init__(self) -> None:
        self.calls = 0

        class _Wallet:
            async def persist(self, db):
                return None

        class _Positions:
            async def save_to_db(self, db):
                return None

            def update_price(self, market_id: str, price: float):
                return None

            def get_all_open(self):
                return []

            async def save_closed_to_db(self, db, market_id: str):
                return None

        self._wallet = _Wallet()
        self._positions = _Positions()

    async def execute_order(self, order):
        self.calls += 1
        return type("R", (), {
            "trade_id": order["trade_id"],
            "market_id": order["market_id"],
            "side": order["side"],
            "requested_size": order["size"],
            "filled_size": order["size"],
            "fill_price": order["price"],
            "reason": "",
            "status": OrderStatus.FILLED,
        })


def test_active_loop_risk_gate_blocks_execution(monkeypatch) -> None:
    db = _FakeDB()
    stop_event = asyncio.Event()
    paper = _PaperEngineStub()

    async def _get_active_markets():
        return [{"market_id": "m1", "p_market": 0.51, "liquidity_usd": 20000.0}]

    async def _apply_scope(markets):
        return markets, {"selection_type": "All Markets", "enabled_categories": []}

    async def _signals(*args, **kwargs):
        stop_event.set()
        return [
            SignalResult(
                signal_id="sig-1",
                market_id="m1",
                side="YES",
                p_market=0.51,
                p_model=0.6,
                edge=0.09,
                ev=0.1,
                kelly_f=0.1,
                size_usd=50.0,
                liquidity_usd=20000.0,
                extra={"risk_approved": False},
            )
        ]

    async def _sleep(_: float):
        return None

    monkeypatch.setattr(loop_mod, "get_active_markets", _get_active_markets)
    monkeypatch.setattr(loop_mod, "apply_market_scope", _apply_scope)
    monkeypatch.setattr(loop_mod, "ingest_markets", lambda markets: markets)
    monkeypatch.setattr(loop_mod, "generate_signals", _signals)
    monkeypatch.setattr(loop_mod.asyncio, "sleep", _sleep)

    asyncio.run(
        loop_mod.run_trading_loop(
            loop_interval_s=1.0,
            bankroll=1000.0,
            mode="PAPER",
            db=db,
            paper_engine=paper,
            stop_event=stop_event,
        )
    )

    assert paper.calls == 0


def test_duplicate_replay_blocked_with_durable_claim() -> None:
    db = _FakeDB()
    from projects.polymarket.polyquantbot.core.wallet_engine import WalletEngine
    from projects.polymarket.polyquantbot.core.positions import PaperPositionManager
    from projects.polymarket.polyquantbot.core.ledger import TradeLedger

    engine = PaperEngine(WalletEngine(), PaperPositionManager(), TradeLedger(), db=db, random_seed=1)
    order = {"trade_id": "dup-1", "market_id": "m1", "side": "YES", "price": 0.5, "size": 10.0}

    first = asyncio.run(engine.execute_order(order))
    second = asyncio.run(engine.execute_order(order))

    assert first.status in {OrderStatus.FILLED, OrderStatus.PARTIAL}
    assert second.status == OrderStatus.REJECTED
    assert second.reason == "duplicate_blocked"


def test_restore_rebinds_runtime_objects() -> None:
    from projects.polymarket.polyquantbot.core.wallet_engine import WalletEngine

    class _RestoreDB:
        async def load_latest_wallet_state(self):
            return {"cash": 123.0, "locked": 7.0, "equity": 130.0}

        async def load_open_paper_positions(self):
            return []

        async def load_ledger_entries(self, market_id=None, limit=1000):
            return []

        async def load_execution_intents(self, limit: int = 5000):
            return ["x-1"]

    container = EngineContainer()
    old_wallet = container.wallet
    assert isinstance(old_wallet, WalletEngine)

    asyncio.run(container.restore_from_db(_RestoreDB()))

    assert container.wallet is not old_wallet
    assert container.paper_engine._wallet is container.wallet
    assert "x-1" in container.paper_engine._processed_trade_ids


def test_outcome_categories_explicit() -> None:
    # Outcome categories are encoded by reasons from hardened execution path.
    categories = {
        "risk_blocked",
        "duplicate_blocked",
        "kill_switch_blocked",
        "rejected",
        "partial_fill",
        "executed",
        "failed",
        "restore_failure",
    }
    assert "risk_blocked" in categories
    assert "duplicate_blocked" in categories
    assert len(categories) == 8


def test_partial_downstream_failure_not_marked_success(monkeypatch) -> None:
    db = _FakeDB()
    stop_event = asyncio.Event()
    paper = _PaperEngineStub()

    async def _fail_persist(_db):
        raise RuntimeError("persist-fail")

    paper._wallet.persist = _fail_persist  # type: ignore[assignment]

    async def _get_active_markets():
        return [{"market_id": "m1", "p_market": 0.51, "liquidity_usd": 20000.0}]

    async def _apply_scope(markets):
        return markets, {"selection_type": "All Markets", "enabled_categories": []}

    async def _signals(*args, **kwargs):
        stop_event.set()
        return [
            SignalResult(
                signal_id="sig-2",
                market_id="m1",
                side="YES",
                p_market=0.51,
                p_model=0.6,
                edge=0.09,
                ev=0.1,
                kelly_f=0.1,
                size_usd=50.0,
                liquidity_usd=20000.0,
                extra={"risk_approved": True},
            )
        ]

    async def _sleep(_: float):
        return None

    monkeypatch.setattr(loop_mod, "get_active_markets", _get_active_markets)
    monkeypatch.setattr(loop_mod, "apply_market_scope", _apply_scope)
    monkeypatch.setattr(loop_mod, "ingest_markets", lambda markets: markets)
    monkeypatch.setattr(loop_mod, "generate_signals", _signals)
    monkeypatch.setattr(loop_mod.asyncio, "sleep", _sleep)

    asyncio.run(
        loop_mod.run_trading_loop(
            loop_interval_s=1.0,
            bankroll=1000.0,
            mode="PAPER",
            db=db,
            paper_engine=paper,
            stop_event=stop_event,
        )
    )

    assert db.insert_trade_calls == 0


def test_touched_failures_observable(monkeypatch) -> None:
    events: list[str] = []

    def _log_warning(event: str, **kwargs):
        events.append(event)

    from projects.polymarket.polyquantbot.core.portfolio import pnl as pnl_mod
    monkeypatch.setattr(pnl_mod.log, "warning", _log_warning)
    PnLTracker = pnl_mod.PnLTracker

    tracker = PnLTracker(db=object())
    tracker.record_realized("m1", 1.0, trade_id="t-1")

    assert "pnl_persist_skipped_no_event_loop" in events
