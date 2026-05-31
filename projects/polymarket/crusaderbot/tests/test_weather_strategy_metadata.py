"""Hermetic tests for the weather strategy_metadata persistence chain.

Wiring under test (migration 076 + execution thread):
  * TradeSignal carries an opaque ``strategy_metadata`` dict (default None).
  * registry._loads_jsonb coerces a JSONB column (str / dict / None / garbage).
  * registry._row_to_open_position maps the column onto OpenPositionForExit.
  * exit_watcher.registry_strategy_evaluator spreads the persisted metadata
    into the weather strategy's evaluate_exit payload (so Exit 4 adaptive
    forecast-shift gets city / bucket bounds / entry forecast mean).
  * paper.execute INSERTs the column json.dumps()'d with a $N::jsonb cast.

No DB, no broker, no network.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from projects.polymarket.crusaderbot.domain.execution import exit_watcher, paper
from projects.polymarket.crusaderbot.domain.positions import registry
from projects.polymarket.crusaderbot.domain.positions.registry import (
    OpenPositionForExit,
)
from projects.polymarket.crusaderbot.domain.strategy.base import BaseStrategy
from projects.polymarket.crusaderbot.domain.strategy.types import ExitDecision
from projects.polymarket.crusaderbot.services.trade_engine.engine import TradeSignal


def _run(coro):
    return asyncio.run(coro)


def _make_position(**overrides) -> OpenPositionForExit:
    base = dict(
        id=uuid4(),
        user_id=uuid4(),
        telegram_user_id=12345,
        market_id="MKT-WX",
        market_question="High temp in NYC?",
        side="yes",
        entry_price=0.40,
        size_usdc=10.0,
        mode="paper",
        status="open",
        applied_tp_pct=0.20,
        applied_sl_pct=0.10,
        force_close_intent=False,
        close_failure_count=0,
        yes_price=0.40,
        no_price=0.60,
        market_resolved=False,
        resolution_at=datetime.now(timezone.utc) + timedelta(hours=12),
        risk_profile="balanced",
        strategy_type="weather",
    )
    base.update(overrides)
    return OpenPositionForExit(**base)


# ---------------------------------------------------------------------------
# TradeSignal field
# ---------------------------------------------------------------------------


def test_trade_signal_strategy_metadata_defaults_none():
    fields = {f.name for f in __import__("dataclasses").fields(TradeSignal)}
    assert "strategy_metadata" in fields


def test_trade_signal_strategy_metadata_roundtrips():
    from decimal import Decimal

    sig = TradeSignal(
        user_id=uuid4(), telegram_user_id=1, role="user", auto_trade_on=True,
        paused=False, market_id="M", market_question="q",
        yes_token_id=None, no_token_id=None, side="yes",
        proposed_size_usdc=Decimal("1"), price=0.5, market_liquidity=1000.0,
        market_status="open", idempotency_key="k", strategy_type="weather",
        risk_profile="balanced", trading_mode="paper",
        strategy_metadata={"city": "NYC", "bucket_low": 70.0, "bucket_high": 75.0},
    )
    assert sig.strategy_metadata["city"] == "NYC"

    sig2 = TradeSignal(
        user_id=uuid4(), telegram_user_id=1, role="user", auto_trade_on=True,
        paused=False, market_id="M", market_question="q",
        yes_token_id=None, no_token_id=None, side="yes",
        proposed_size_usdc=Decimal("1"), price=0.5, market_liquidity=1000.0,
        market_status="open", idempotency_key="k", strategy_type="signal_following",
        risk_profile="balanced", trading_mode="paper",
    )
    assert sig2.strategy_metadata is None


# ---------------------------------------------------------------------------
# registry._loads_jsonb
# ---------------------------------------------------------------------------


def test_loads_jsonb_none_returns_none():
    assert registry._loads_jsonb(None) is None


def test_loads_jsonb_passes_dict_through():
    d = {"city": "Chicago"}
    assert registry._loads_jsonb(d) is d


def test_loads_jsonb_decodes_json_string():
    assert registry._loads_jsonb('{"city": "Denver", "bucket_low": 50}') == {
        "city": "Denver", "bucket_low": 50,
    }


def test_loads_jsonb_decodes_bytes():
    assert registry._loads_jsonb(b'{"k": 1}') == {"k": 1}


def test_loads_jsonb_malformed_returns_none():
    assert registry._loads_jsonb("{not valid json") is None


def test_loads_jsonb_non_dict_json_returns_none():
    # A JSON array / scalar is valid JSON but not a metadata dict.
    assert registry._loads_jsonb("[1, 2, 3]") is None
    assert registry._loads_jsonb('"just a string"') is None


# ---------------------------------------------------------------------------
# registry._row_to_open_position
# ---------------------------------------------------------------------------


def _row(**overrides) -> dict:
    base = dict(
        id=uuid4(), user_id=uuid4(), telegram_user_id=7,
        market_id="MKT-WX", side="yes", entry_price=0.4, size_usdc=10.0,
        mode="paper", status="open", applied_tp_pct=0.2, applied_sl_pct=0.1,
        force_close_intent=False, close_failure_count=0,
        strategy_type="weather", market_question="q",
        yes_price=0.4, no_price=0.6, market_resolved=False,
        resolution_at=None, yes_token_id=None, no_token_id=None,
        risk_profile="balanced", active_preset="weather_monitor",
        selected_timeframe=None,
        strategy_metadata='{"city": "NYC", "bucket_low": 70, "bucket_high": 75}',
    )
    base.update(overrides)
    return base


def test_row_to_open_position_decodes_metadata():
    pos = registry._row_to_open_position(_row())
    assert pos.strategy_metadata == {"city": "NYC", "bucket_low": 70, "bucket_high": 75}


def test_row_to_open_position_null_metadata():
    pos = registry._row_to_open_position(_row(strategy_metadata=None))
    assert pos.strategy_metadata is None


def test_row_to_open_position_missing_column_is_none():
    r = _row()
    del r["strategy_metadata"]
    pos = registry._row_to_open_position(r)
    assert pos.strategy_metadata is None


# ---------------------------------------------------------------------------
# exit_watcher.registry_strategy_evaluator — weather payload enrichment
# ---------------------------------------------------------------------------


class _CaptureWeatherStrategy(BaseStrategy):
    name = "weather"
    version = "1.0.0"
    risk_profile_compatibility = ["conservative", "balanced", "aggressive"]

    def __init__(self):
        self.captured: dict | None = None

    async def scan(self, market_filters, user_context):  # pragma: no cover
        return []

    async def evaluate_exit(self, position):
        self.captured = dict(position)
        return ExitDecision(should_exit=False, reason="hold")

    def default_tp_sl(self):
        return (0.25, 0.20)


def _with_fake_weather(fn):
    from projects.polymarket.crusaderbot.domain.strategy import StrategyRegistry

    StrategyRegistry._reset_for_tests()
    try:
        strat = _CaptureWeatherStrategy()
        StrategyRegistry.instance().register(strat)
        return fn(strat)
    finally:
        StrategyRegistry._reset_for_tests()


def test_evaluator_spreads_strategy_metadata_into_weather_payload():
    def run(strat):
        meta = {
            "city": "New York City",
            "bucket_low": 70.0,
            "bucket_high": 75.0,
            "mean_tmax_f": 72.5,
        }
        pos = _make_position(strategy_metadata=meta)
        _run(exit_watcher.registry_strategy_evaluator(pos, current_price=0.42))
        assert strat.captured is not None
        # metadata keys spread at top level for the hook to read
        assert strat.captured["city"] == "New York City"
        assert strat.captured["bucket_low"] == 70.0
        assert strat.captured["bucket_high"] == 75.0
        assert strat.captured["mean_tmax_f"] == 72.5
        # base payload keys still present
        assert strat.captured["current_price"] == 0.42
        assert strat.captured["entry_price"] == pos.entry_price

    _with_fake_weather(run)


def test_evaluator_end_date_wins_over_metadata_end_date():
    def run(strat):
        res_at = datetime.now(timezone.utc) + timedelta(hours=6)
        # metadata carries a stale end_date; resolution_at must win.
        meta = {"city": "NYC", "end_date": "1999-01-01T00:00:00+00:00"}
        pos = _make_position(strategy_metadata=meta, resolution_at=res_at)
        _run(exit_watcher.registry_strategy_evaluator(pos, current_price=0.42))
        assert strat.captured["end_date"] == res_at.isoformat()

    _with_fake_weather(run)


def test_evaluator_metadata_cannot_clobber_authoritative_payload_keys():
    """A stale metadata value must never overwrite a live base payload key."""
    def run(strat):
        # Hostile metadata: collides with every authoritative base key. The
        # live current_price + entry_price + side must survive untouched.
        meta = {
            "current_price": 0.99,      # stale — live is 0.42
            "entry_price": 0.01,        # stale — position entry is 0.40
            "side": "no",               # wrong — position side is yes
            "market_id": "WRONG",
            "strategy_type": "spoofed",
            "city": "NYC",              # legit metadata key, must pass through
        }
        pos = _make_position(strategy_metadata=meta, side="yes", entry_price=0.40)
        _run(exit_watcher.registry_strategy_evaluator(pos, current_price=0.42))
        assert strat.captured["current_price"] == 0.42
        assert strat.captured["entry_price"] == 0.40
        assert strat.captured["side"] == "yes"
        assert strat.captured["market_id"] == pos.market_id
        assert strat.captured["strategy_type"] == "weather"
        # non-colliding metadata still flows through
        assert strat.captured["city"] == "NYC"

    _with_fake_weather(run)


def test_evaluator_no_metadata_still_dispatches():
    def run(strat):
        pos = _make_position(strategy_metadata=None)
        _run(exit_watcher.registry_strategy_evaluator(pos, current_price=0.42))
        assert strat.captured is not None
        assert "city" not in strat.captured
        # end_date still set from resolution_at
        assert "end_date" in strat.captured

    _with_fake_weather(run)


# ---------------------------------------------------------------------------
# paper.execute INSERT — source pin (the SQL must persist the column)
# ---------------------------------------------------------------------------


def test_paper_execute_insert_persists_strategy_metadata():
    src = inspect.getsource(paper.execute)
    assert "strategy_metadata" in src
    assert "$12::jsonb" in src
    assert "json.dumps(strategy_metadata)" in src


def test_paper_execute_signature_accepts_strategy_metadata():
    params = inspect.signature(paper.execute).parameters
    assert "strategy_metadata" in params
    assert params["strategy_metadata"].default is None
