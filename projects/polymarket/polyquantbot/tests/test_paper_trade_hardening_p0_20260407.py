from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.core.pipeline import trading_loop
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
from projects.polymarket.polyquantbot.execution.engine_router import EngineContainer
from projects.polymarket.polyquantbot.execution.paper_engine import PaperEngine, OrderStatus
from projects.polymarket.polyquantbot.risk.risk_guard import RiskGuard


class _FakeDB:
    def __init__(self) -> None:
        self.trades: list[dict] = []
        self.positions: list[dict] = []

    async def get_positions(self, user_id: str | None = None):
        return list(self.positions)

    async def get_recent_trades(self, limit: int = 500):
        return list(self.trades)

    async def upsert_position(self, position: dict):
        self.positions.append(position)
        return True

    async def insert_trade(self, trade: dict):
        self.trades.append(trade)
        return True

    async def update_trade_status(self, trade_id: str, status: str, pnl: float | None = None, won: bool | None = None):
        return True

    async def load_latest_wallet_state(self):
        return {"cash": 777.0, "locked": 123.0, "equity": 900.0}

    async def load_open_paper_positions(self):
        return []

    async def load_ledger_entries(self, market_id: str | None = None, limit: int = 1000):
        return []

    async def load_recent_trade_ids(self, limit: int = 5000):
        return ["dup-1"]


class _PaperEngineStub:
    def __init__(self) -> None:
        self.calls = 0
        self._wallet = type(
            "Wallet",
            (),
            {
                "get_state": lambda _self: type("State", (), {"equity": 1000.0})(),
                "persist": lambda _self, db: asyncio.sleep(0),
            },
        )()
        self._positions = type(
            "Positions",
            (),
            {
                "update_price": lambda _self, market_id, price: None,
                "get_all_open": lambda _self: [],
                "save_closed_to_db": lambda _self, db, market_id: asyncio.sleep(0),
            },
        )()

    async def execute_order(self, order: dict):
        self.calls += 1
        return type("Order", (), {
            "trade_id": order["trade_id"],
            "market_id": order["market_id"],
            "side": order["side"],
            "requested_size": order["size"],
            "filled_size": order["size"],
            "fill_price": order["price"],
            "reason": "filled",
            "status": OrderStatus.FILLED,
        })()


def _signal() -> SignalResult:
    return SignalResult(
        signal_id="sig-1",
        market_id="mkt-1",
        side="YES",
        p_market=0.45,
        p_model=0.55,
        edge=0.10,
        ev=0.12,
        kelly_f=0.2,
        size_usd=20.0,
        liquidity_usd=20_000.0,
        extra={"strategy_id": "test"},
    )


def _patch_single_tick(monkeypatch, stop_event: asyncio.Event) -> None:
    async def _sleep(_: float):
        stop_event.set()

    async def _markets():
        return [{"condition_id": "mkt-1", "question": "q", "outcomes": ["YES", "NO"], "best_ask": 0.45, "liquidity": 20000}]

    async def _scope(markets):
        return markets, {"selection_type": "All", "enabled_categories": [], "all_markets_enabled": True, "fallback_applied_count": 0}

    def _ingest(markets):
        return [{"market_id": "mkt-1", "p_market": 0.45, "liquidity_usd": 20000.0}]

    async def _signals(*args, **kwargs):
        return [_signal()]

    monkeypatch.setattr(trading_loop, "get_active_markets", _markets)
    monkeypatch.setattr(trading_loop, "apply_market_scope", _scope)
    monkeypatch.setattr(trading_loop, "ingest_markets", _ingest)
    monkeypatch.setattr(trading_loop, "generate_signals", _signals)
    monkeypatch.setattr(trading_loop.asyncio, "sleep", _sleep)


def test_risk_guard_blocks_active_loop_execution(monkeypatch):
    async def _run() -> None:
        stop_event = asyncio.Event()
        db = _FakeDB()
        paper = _PaperEngineStub()
        risk = RiskGuard()
        await risk.trigger_kill_switch("test")
        _patch_single_tick(monkeypatch, stop_event)

        await trading_loop.run_trading_loop(
            loop_interval_s=0.01,
            mode="PAPER",
            db=db,
            stop_event=stop_event,
            paper_engine=paper,
            risk_guard=risk,
        )
        assert paper.calls == 0

    asyncio.run(_run())


def test_allowed_path_runs_in_paper_mode(monkeypatch):
    async def _run() -> None:
        stop_event = asyncio.Event()
        db = _FakeDB()
        paper = _PaperEngineStub()
        risk = RiskGuard()
        _patch_single_tick(monkeypatch, stop_event)

        await trading_loop.run_trading_loop(
            loop_interval_s=0.01,
            mode="PAPER",
            db=db,
            stop_event=stop_event,
            paper_engine=paper,
            risk_guard=risk,
        )
        assert paper.calls == 1

    asyncio.run(_run())


def test_wallet_restore_updates_active_runtime_wallet_and_dedup():
    async def _run() -> None:
        db = _FakeDB()
        container = EngineContainer()
        old_wallet = container.wallet
        await container.restore_from_db(db)

        assert container.wallet is not old_wallet
        assert container.paper_engine._wallet is container.wallet
        assert container.wallet.get_state().cash == 777.0

    asyncio.run(_run())


def test_duplicate_replay_blocked_after_restart_rehydrate(monkeypatch):
    async def _run() -> None:
        db = _FakeDB()
        container = EngineContainer()
        engine = PaperEngine(
            wallet=container.wallet,
            positions=container.positions,
            ledger=container.ledger,
            random_seed=42,
        )

        async def _sleep(_: float):
            return None

        monkeypatch.setattr("projects.polymarket.polyquantbot.execution.paper_engine.asyncio.sleep", _sleep)
        await engine.restore_dedup_state(db)
        result = await engine.execute_order(
            {"trade_id": "dup-1", "market_id": "mkt-1", "side": "YES", "price": 0.5, "size": 10.0}
        )
        assert result.reason == "duplicate_trade_id"

    asyncio.run(_run())


def test_audited_silent_failure_path_removed():
    content = open(
        "projects/polymarket/polyquantbot/core/pipeline/trading_loop.py",
        "r",
        encoding="utf-8",
    ).read()
    assert "except Exception:\n                                            pass" not in content
