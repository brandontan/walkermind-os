from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from projects.polymarket.polyquantbot.core.pipeline.trading_loop import run_trading_loop
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
from projects.polymarket.polyquantbot.execution.engine_router import EngineContainer
from projects.polymarket.polyquantbot.execution.paper_engine import OrderStatus
from projects.polymarket.polyquantbot.risk.risk_guard import RiskGuard


class _FakeDB:
    def __init__(self) -> None:
        self._trades: list[dict] = []

    async def get_positions(self, _user_id: str):
        return []

    async def get_recent_trades(self, limit: int = 500):
        return self._trades[:limit]

    async def upsert_position(self, _position: dict):
        return True

    async def insert_trade(self, trade: dict):
        self._trades.append(trade)
        return True

    async def update_trade_status(self, *_args, **_kwargs):
        return True


class _AllowRiskGuard(RiskGuard):
    async def check_daily_loss(self, current_pnl: float) -> None:
        return None

    async def check_drawdown(self, peak_balance: float, current_balance: float) -> None:
        return None


class _BlockRiskGuard(RiskGuard):
    async def check_daily_loss(self, current_pnl: float) -> None:
        await self.trigger_kill_switch("test_block")


def test_risk_guard_blocks_active_paper_loop_execution(monkeypatch) -> None:
    stop_event = asyncio.Event()
    db = _FakeDB()
    paper_engine = SimpleNamespace(
        execute_order=AsyncMock(),
        _wallet=SimpleNamespace(get_state=lambda: SimpleNamespace(equity=10_000.0)),
        _positions=SimpleNamespace(update_price=lambda *_args, **_kwargs: None, get_all_open=lambda: []),
    )

    signal = SignalResult(
        signal_id="sig-risk-block",
        market_id="m1",
        side="YES",
        p_market=0.45,
        p_model=0.60,
        edge=0.15,
        ev=0.1,
        kelly_f=0.1,
        size_usd=10.0,
        liquidity_usd=20_000.0,
    )

    async def _stop_sleep(_seconds: float) -> None:
        stop_event.set()

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
        AsyncMock(return_value=[{"id": "m1"}]),
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.apply_market_scope",
        AsyncMock(return_value=([{"id": "m1"}], {"enabled_categories": [], "selection_type": "All"})),
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.ingest_markets",
        lambda _markets: [{"market_id": "m1", "p_market": 0.45}],
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
        AsyncMock(return_value=[signal]),
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
        _stop_sleep,
    )

    asyncio.run(
        run_trading_loop(
            mode="PAPER",
            db=db,
            stop_event=stop_event,
            paper_engine=paper_engine,
            risk_guard=_BlockRiskGuard(),
        )
    )

    paper_engine.execute_order.assert_not_called()


def test_allowed_path_still_executes_in_paper_mode(monkeypatch) -> None:
    stop_event = asyncio.Event()
    db = _FakeDB()

    async def _exec_order(_order: dict):
        return SimpleNamespace(
            status=OrderStatus.FILLED,
            trade_id="t-allowed",
            market_id="m-allowed",
            side="YES",
            requested_size=10.0,
            filled_size=10.0,
            fill_price=0.5,
            reason="ok",
        )

    paper_engine = SimpleNamespace(
        execute_order=AsyncMock(side_effect=_exec_order),
        _wallet=SimpleNamespace(
            get_state=lambda: SimpleNamespace(equity=10_000.0),
            persist=AsyncMock(),
        ),
        _positions=SimpleNamespace(
            update_price=lambda *_args, **_kwargs: None,
            get_all_open=lambda: [],
            save_to_db=AsyncMock(),
        ),
    )

    signal = SignalResult(
        signal_id="sig-allowed",
        market_id="m-allowed",
        side="YES",
        p_market=0.45,
        p_model=0.60,
        edge=0.15,
        ev=0.1,
        kelly_f=0.1,
        size_usd=10.0,
        liquidity_usd=20_000.0,
    )

    async def _stop_sleep(_seconds: float) -> None:
        stop_event.set()

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.get_active_markets",
        AsyncMock(return_value=[{"id": "m-allowed"}]),
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.apply_market_scope",
        AsyncMock(return_value=([{"id": "m-allowed"}], {"enabled_categories": [], "selection_type": "All"})),
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.ingest_markets",
        lambda _markets: [{"market_id": "m-allowed", "p_market": 0.45}],
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.generate_signals",
        AsyncMock(return_value=[signal]),
    )
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.pipeline.trading_loop.asyncio.sleep",
        _stop_sleep,
    )

    asyncio.run(
        run_trading_loop(
            mode="PAPER",
            db=db,
            stop_event=stop_event,
            paper_engine=paper_engine,
            risk_guard=_AllowRiskGuard(),
        )
    )

    paper_engine.execute_order.assert_called_once()


def test_wallet_restore_rebinds_runtime_wallet_and_dedup_seed() -> None:
    container = EngineContainer()

    restored_wallet = SimpleNamespace(marker="restored")

    async def _restore(_cls, _db):
        return restored_wallet

    db = SimpleNamespace(
        load_processed_trade_ids=AsyncMock(return_value=["persisted-trade-id"]),
        load_open_paper_positions=AsyncMock(return_value=[]),
        load_ledger_entries=AsyncMock(return_value=[]),
    )

    from projects.polymarket.polyquantbot.execution import engine_router as router_module

    original_restore = router_module.WalletEngine.restore_from_db
    router_module.WalletEngine.restore_from_db = classmethod(_restore)  # type: ignore[assignment]
    try:
        asyncio.run(container.restore_from_db(db))
    finally:
        router_module.WalletEngine.restore_from_db = original_restore  # type: ignore[assignment]

    assert container.wallet is restored_wallet
    assert container.paper_engine._wallet is restored_wallet
    duplicate = asyncio.run(
        container.paper_engine.execute_order(
            {
                "trade_id": "persisted-trade-id",
                "market_id": "m1",
                "side": "YES",
                "price": 0.5,
                "size": 10.0,
            }
        )
    )
    assert duplicate.reason == "duplicate_trade_id"


def test_trading_loop_no_silent_exception_swallow_for_close_alerts() -> None:
    from pathlib import Path

    source = Path(
        "/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py"
    ).read_text(encoding="utf-8")

    assert "except Exception:\n                                            pass" not in source
