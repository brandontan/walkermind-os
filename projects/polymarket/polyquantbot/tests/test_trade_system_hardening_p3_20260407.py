from __future__ import annotations

import asyncio
import datetime

from projects.polymarket.polyquantbot.core.ledger import LedgerAction, LedgerEntry
from projects.polymarket.polyquantbot.execution import engine_router
from projects.polymarket.polyquantbot.execution.capital_guard import GuardrailConfig
from projects.polymarket.polyquantbot.execution.paper_engine import OrderStatus


def _build_container_with_guard(config: GuardrailConfig) -> engine_router.EngineContainer:
    container = engine_router.EngineContainer()
    container.capital_guard = engine_router.CapitalGuard(
        wallet=container.wallet,
        positions=container.positions,
        ledger=container.ledger,
        config=config,
    )
    container._wire_execution_guardrails()
    return container


def test_guardrail_blocks_insufficient_capital() -> None:
    container = _build_container_with_guard(
        GuardrailConfig(
            max_position_size_per_trade_pct=0.10,
            max_total_exposure_pct=0.90,
            max_open_positions=5,
            daily_loss_limit_pct=0.50,
        )
    )

    result = asyncio.run(
        container.paper_engine.execute_order(
            {
                "trade_id": "t-insufficient",
                "market_id": "m-1",
                "side": "YES",
                "price": 0.55,
                "size": 2000.0,
            }
        )
    )

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "capital_insufficient"
    assert container.ledger.count() == 0


def test_guardrail_blocks_exposure_overflow() -> None:
    container = _build_container_with_guard(
        GuardrailConfig(
            max_position_size_per_trade_pct=0.50,
            max_total_exposure_pct=0.30,
            max_open_positions=5,
            daily_loss_limit_pct=0.50,
        )
    )

    container.positions.open_position(
        market_id="m-existing",
        side="YES",
        size=2500.0,
        entry_price=0.5,
        trade_id="existing-open",
    )

    result = asyncio.run(
        container.paper_engine.execute_order(
            {
                "trade_id": "t-exposure",
                "market_id": "m-2",
                "side": "YES",
                "price": 0.61,
                "size": 1000.0,
            }
        )
    )

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "exposure_limit"
    assert container.ledger.count() == 0


def test_guardrail_blocks_max_positions_reached() -> None:
    container = _build_container_with_guard(
        GuardrailConfig(
            max_position_size_per_trade_pct=0.80,
            max_total_exposure_pct=0.95,
            max_open_positions=1,
            daily_loss_limit_pct=0.50,
        )
    )

    container.positions.open_position(
        market_id="m-open",
        side="YES",
        size=500.0,
        entry_price=0.4,
        trade_id="existing-position",
    )

    result = asyncio.run(
        container.paper_engine.execute_order(
            {
                "trade_id": "t-max-pos",
                "market_id": "m-next",
                "side": "NO",
                "price": 0.4,
                "size": 200.0,
            }
        )
    )

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "max_positions_reached"
    assert container.ledger.count() == 0


def test_guardrail_blocks_drawdown_limit() -> None:
    container = _build_container_with_guard(
        GuardrailConfig(
            max_position_size_per_trade_pct=0.80,
            max_total_exposure_pct=0.95,
            max_open_positions=5,
            daily_loss_limit_pct=0.05,
        )
    )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    container.ledger.record(
        LedgerEntry(
            trade_id="close-loss-1",
            market_id="m-loss",
            action=LedgerAction.CLOSE,
            price=0.3,
            size=1000.0,
            fee=1.0,
            timestamp=now_iso,
            realized_pnl=-600.0,
        )
    )

    result = asyncio.run(
        container.paper_engine.execute_order(
            {
                "trade_id": "t-dd",
                "market_id": "m-new",
                "side": "YES",
                "price": 0.5,
                "size": 100.0,
            }
        )
    )

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "drawdown_limit"
    assert container.ledger.count() == 1
