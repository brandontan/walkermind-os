import asyncio

import pytest

from projects.polymarket.polyquantbot.core.execution.executor import execute_trade, reset_state
from projects.polymarket.polyquantbot.core.pipeline import trading_loop
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
from projects.polymarket.polyquantbot.execution.event_logger import emit_event


class _FakeDb:
    async def get_positions(self, _user_id):
        return []

    async def upsert_position(self, _payload):
        return None

    async def insert_trade(self, _payload):
        return None

    async def update_trade_status(self, *_args, **_kwargs):
        return None

    async def get_recent_trades(self, limit=500):
        return []


def test_runtime_path_emits_trace_events(monkeypatch):
    reset_state()

    captured_events = []
    original_emit = emit_event
    stop_event = asyncio.Event()

    def _capture_emit(*, trace_id, event_type, component, outcome, payload=None):
        event = original_emit(
            trace_id=trace_id,
            event_type=event_type,
            component=component,
            outcome=outcome,
            payload=payload,
        )
        captured_events.append(event)
        return event

    async def _fake_get_active_markets():
        stop_event.set()
        return [{"market_id": "m1", "p_market": 0.55}]

    async def _fake_apply_market_scope(markets):
        return markets, {
            "selection_type": "All Markets",
            "enabled_categories": [],
            "fallback_applied_count": 0,
            "all_markets_enabled": True,
        }

    def _fake_ingest_markets(_markets):
        return [{"market_id": "m1", "p_market": 0.55}]

    async def _fake_generate_signals(*args, **kwargs):
        return [
            SignalResult(
                signal_id="s1",
                market_id="m1",
                side="YES",
                p_market=0.55,
                p_model=0.60,
                edge=0.05,
                ev=0.10,
                kelly_f=0.10,
                size_usd=50.0,
                liquidity_usd=20_000.0,
                force_mode=False,
                extra={},
            )
        ]

    monkeypatch.setattr(trading_loop, "emit_event", _capture_emit)
    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.execution.executor.emit_event",
        _capture_emit,
    )
    monkeypatch.setattr(trading_loop, "get_active_markets", _fake_get_active_markets)
    monkeypatch.setattr(trading_loop, "apply_market_scope", _fake_apply_market_scope)
    monkeypatch.setattr(trading_loop, "ingest_markets", _fake_ingest_markets)
    monkeypatch.setattr(trading_loop, "generate_signals", _fake_generate_signals)

    asyncio.run(trading_loop.run_trading_loop(
        mode="PAPER",
        db=_FakeDb(),
        stop_event=stop_event,
        loop_interval_s=0.01,
        bankroll=1_000.0,
    ))

    trade_start_events = [e for e in captured_events if e["event_type"] == "trade_start"]
    execution_attempt_events = [
        e for e in captured_events if e["event_type"] == "execution_attempt"
    ]
    execution_result_events = [
        e for e in captured_events if e["event_type"] == "execution_result"
    ]

    assert trade_start_events
    assert execution_attempt_events
    assert execution_result_events

    trace_id = trade_start_events[0]["trace_id"]
    assert trace_id
    assert execution_attempt_events[0]["trace_id"] == trace_id
    assert execution_result_events[0]["trace_id"] == trace_id


@pytest.mark.parametrize(
    ("trace_id", "event_type", "component", "outcome"),
    [
        (None, "execution_attempt", "executor", "started"),
        ("", "execution_attempt", "executor", "started"),
        ("t1", None, "executor", "started"),
        ("t1", "", "executor", "started"),
        ("t1", "execution_attempt", None, "started"),
        ("t1", "execution_attempt", "", "started"),
        ("t1", "execution_attempt", "executor", None),
        ("t1", "execution_attempt", "executor", ""),
    ],
)
def test_emit_event_contract_raises_value_error(trace_id, event_type, component, outcome):
    with pytest.raises(ValueError):
        emit_event(
            trace_id=trace_id,
            event_type=event_type,
            component=component,
            outcome=outcome,
        )


def test_execute_trade_normalizes_non_string_trace_id(monkeypatch):
    reset_state()
    captured_events = []

    def _capture_emit(*, trace_id, event_type, component, outcome, payload=None):
        captured_events.append(
            {
                "trace_id": trace_id,
                "event_type": event_type,
                "component": component,
                "outcome": outcome,
                "payload": payload,
            }
        )
        return {
            "trace_id": trace_id,
            "event_type": event_type,
            "component": component,
            "outcome": outcome,
            "payload": payload or {},
        }

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.core.execution.executor.emit_event",
        _capture_emit,
    )

    signal = SignalResult(
        signal_id="s-trace-int",
        market_id="m-trace-int",
        side="YES",
        p_market=0.40,
        p_model=0.55,
        edge=0.15,
        ev=0.10,
        kelly_f=0.10,
        size_usd=25.0,
        liquidity_usd=20_000.0,
        force_mode=False,
        extra={},
    )

    result = asyncio.run(execute_trade(signal, mode="PAPER", trace_id=12345))

    assert result.success is True
    assert captured_events
    assert captured_events[0]["event_type"] == "execution_attempt"
    assert captured_events[0]["trace_id"] == "12345"
