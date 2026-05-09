"""Unit tests for the CLOB WebSocket message parser (Phase 4D).

Pure-function tests over already-decoded JSON dicts. No transport, no
sockets, no async. Every malformed-frame branch must be exercised so a
broker schema change cannot crash the live read loop.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.integrations.clob import ws_handler
from projects.polymarket.crusaderbot.integrations.clob.ws_handler import (
    EVENT_FILL,
    EVENT_ORDER_UPDATE,
    normalise_status,
    parse_message,
)


# ---------------------------------------------------------------------------
# Status normalisation
# ---------------------------------------------------------------------------


def test_normalise_status_known_aliases():
    assert normalise_status("MATCHED") == "filled"
    assert normalise_status("filled") == "filled"
    assert normalise_status("Canceled") == "cancelled"
    assert normalise_status("cancelled") == "cancelled"
    assert normalise_status("expired") == "expired"
    assert normalise_status("live") == "open"
    assert normalise_status("delayed") == "open"


def test_normalise_status_strips_order_status_prefix():
    assert normalise_status("ORDER_STATUS_MATCHED") == "filled"
    assert normalise_status("ORDER_STATUS_CANCELED_MARKET_RESOLVED") == "cancelled"


def test_normalise_status_unknown_falls_back_to_open():
    assert normalise_status(None) == "open"
    assert normalise_status("") == "open"
    assert normalise_status("resting") == "open"


# ---------------------------------------------------------------------------
# user_fill routing
# ---------------------------------------------------------------------------


def test_user_fill_minimal_dispatches_fill_event():
    out = parse_message({
        "event_type": "user_fill",
        "id": "fill-1",
        "order_id": "broker-1",
        "price": "0.55",
        "size": "100",
        "side": "BUY",
    })
    assert len(out) == 1
    ev = out[0]
    assert ev["kind"] == EVENT_FILL
    assert ev["broker_order_id"] == "broker-1"
    assert ev["fill_id"] == "fill-1"
    assert ev["price"] == pytest.approx(0.55)
    assert ev["size"] == pytest.approx(100.0)
    assert ev["side"] == "buy"


def test_user_fill_accepts_alternate_id_keys():
    out = parse_message({
        "event_type": "user_fill",
        "trade_id": "fill-99",
        "taker_order_id": "broker-99",
        "price": 0.42, "size": 5,
    })
    assert len(out) == 1
    assert out[0]["broker_order_id"] == "broker-99"
    assert out[0]["fill_id"] == "fill-99"


def test_user_fill_drops_when_order_id_missing():
    out = parse_message({
        "event_type": "user_fill",
        "id": "fill-2",
        "price": "0.5", "size": "1",
    })
    assert out == []


def test_user_fill_drops_when_fill_id_missing():
    out = parse_message({
        "event_type": "user_fill",
        "order_id": "broker-3",
        "price": "0.5", "size": "1",
    })
    assert out == []


def test_user_fill_drops_when_size_zero_or_negative():
    out = parse_message({
        "event_type": "user_fill",
        "id": "fill-z",
        "order_id": "broker-z",
        "price": "0.5", "size": "0",
    })
    assert out == []


def test_user_fill_drops_when_price_unparseable():
    out = parse_message({
        "event_type": "user_fill",
        "id": "fill-x",
        "order_id": "broker-x",
        "price": "not-a-number", "size": "1",
    })
    assert out == []


# ---------------------------------------------------------------------------
# user_order routing
# ---------------------------------------------------------------------------


def test_user_order_filled_routes_to_order_update():
    out = parse_message({
        "event_type": "user_order",
        "order_id": "broker-1",
        "status": "MATCHED",
        "size_matched": "10",
        "price": "0.7",
    })
    assert len(out) == 1
    ev = out[0]
    assert ev["kind"] == EVENT_ORDER_UPDATE
    assert ev["broker_order_id"] == "broker-1"
    assert ev["status"] == "filled"
    assert ev["size_matched"] == pytest.approx(10.0)
    assert ev["price"] == pytest.approx(0.7)


def test_user_order_cancelled_routes_to_order_update():
    out = parse_message({
        "event_type": "user_order",
        "order_id": "broker-2",
        "status": "ORDER_STATUS_CANCELED",
    })
    assert out[0]["status"] == "cancelled"


def test_user_order_drops_when_order_id_missing():
    assert parse_message({
        "event_type": "user_order", "status": "matched",
    }) == []


# ---------------------------------------------------------------------------
# Ignore + unknown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", [
    "last_trade_price", "book", "price_change", "tick_size_change",
    "pong", "subscribed",
])
def test_known_ignored_events_emit_nothing(event_type):
    assert parse_message({"event_type": event_type, "data": {}}) == []


def test_unknown_event_type_emits_nothing_and_does_not_raise():
    # No exception, no event — exactly what the read loop needs so a
    # schema rollout cannot crash anything.
    assert parse_message({"event_type": "totally_new_kind"}) == []


def test_non_dict_message_drops_silently():
    assert parse_message("hello") == []
    assert parse_message(42) == []
    assert parse_message(None) == []


def test_batched_array_payload_returns_each_event():
    # Polymarket sometimes batches frames into a JSON array.
    out = parse_message([
        {"event_type": "last_trade_price"},
        {
            "event_type": "user_fill", "id": "f1",
            "order_id": "o1", "price": "0.5", "size": "1",
        },
        {
            "event_type": "user_order", "order_id": "o1", "status": "live",
        },
    ])
    kinds = [ev["kind"] for ev in out]
    assert kinds == [EVENT_FILL, EVENT_ORDER_UPDATE]


def test_module_exports_event_kind_constants():
    assert ws_handler.EVENT_FILL == "fill"
    assert ws_handler.EVENT_ORDER_UPDATE == "order_update"
