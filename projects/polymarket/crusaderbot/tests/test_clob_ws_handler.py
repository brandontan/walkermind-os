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


def test_user_fill_taker_only_uses_synthetic_taker_fill_id():
    out = parse_message({
        "event_type": "user_fill",
        "trade_id": "fill-99",
        "taker_order_id": "broker-99",
        "price": 0.42, "size": 5,
    })
    # Per-side synthetic fill_ids keep maker + taker fills from the
    # same trade frame distinct in the lifecycle's `fills` table.
    assert len(out) == 1
    assert out[0]["broker_order_id"] == "broker-99"
    assert out[0]["fill_id"] == "fill-99-t"


def test_user_fill_maker_orders_emits_one_event_per_maker():
    """Codex P1: when OUR order is the maker, the broker order id sits
    inside ``maker_orders[]``; reading only ``taker_order_id`` would
    drop the fill until the polling loop reconciled it. This case is
    the documented user-channel ``trade`` shape from
    docs.polymarket.com/market-data/websocket/user-channel.
    """
    out = parse_message({
        "event_type": "trade",
        "id": "trade-7",
        "price": "0.55",
        "size": "10",  # taker total, not used for maker rows
        "taker_order_id": "taker-tk",
        "maker_orders": [
            {"order_id": "mk-A", "matched_amount": "4", "price": "0.55"},
            {"order_id": "mk-B", "matched_amount": "6", "price": "0.55"},
        ],
    })
    # Two maker-side events + one taker-side event = three events.
    assert len(out) == 3
    ids = [(ev["broker_order_id"], ev["fill_id"]) for ev in out]
    assert ("mk-A", "trade-7-m-0") in ids
    assert ("mk-B", "trade-7-m-1") in ids
    assert ("taker-tk", "trade-7-t") in ids
    # Per-maker size honours matched_amount, not the trade-level total.
    by_id = {ev["broker_order_id"]: ev for ev in out}
    assert by_id["mk-A"]["size"] == pytest.approx(4.0)
    assert by_id["mk-B"]["size"] == pytest.approx(6.0)
    assert by_id["taker-tk"]["size"] == pytest.approx(10.0)


def test_user_fill_taker_dedup_against_maker_id():
    """If the same id appears in both maker_orders[] and taker_order_id
    (Polymarket has surfaced this for self-trades), do NOT emit two
    events for the same broker order.
    """
    out = parse_message({
        "event_type": "trade",
        "id": "trade-8",
        "price": "0.6",
        "size": "5",
        "taker_order_id": "same-id",
        "maker_orders": [
            {"order_id": "same-id", "matched_amount": "5"},
        ],
    })
    assert len(out) == 1
    assert out[0]["broker_order_id"] == "same-id"
    assert out[0]["fill_id"] == "trade-8-m-0"


def test_user_fill_drops_when_order_id_missing():
    out = parse_message({
        "event_type": "user_fill",
        "id": "fill-2",
        "price": "0.5", "size": "1",
    })
    assert out == []


def test_user_fill_drops_when_trade_id_missing():
    """Without a trade id we cannot synthesise a unique fills-table key.
    Drops every candidate fill rather than risking a collision.
    """
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


@pytest.mark.parametrize("non_settled_status", [
    # Failure / retry path
    "RETRYING", "FAILED", "TRADE_STATUS_FAILED", "rejected",
    "Cancelled", "TRADE_STATUS_RETRYING",
    # Pre-confirm pipeline states — MATCHED + MINED are NON-terminal
    # per Polymarket docs and can still flip to RETRYING/FAILED, so
    # they must NOT be treated as fills. Codex P1 round 4 (PR #915).
    "MATCHED", "MINED", "TRADE_STATUS_MATCHED", "TRADE_STATUS_MINED",
])
def test_trade_frame_with_non_settled_status_emits_no_fill(non_settled_status):
    """Polymarket's user channel re-emits the same trade frame as the
    on-chain settlement progresses through MATCHED -> MINED ->
    CONFIRMED (success) or -> RETRYING -> FAILED. Only CONFIRMED is a
    safe fill signal; everything else may still revert.
    """
    assert parse_message({
        "event_type": "trade",
        "id": "t-1",
        "order_id": "broker-1",
        "price": "0.5", "size": "1",
        "status": non_settled_status,
    }) == []


@pytest.mark.parametrize("settled_status", [
    "CONFIRMED", "TRADE_STATUS_CONFIRMED", "completed", "SETTLED",
])
def test_trade_frame_with_settled_status_emits_fill(settled_status):
    out = parse_message({
        "event_type": "trade",
        "id": "t-2",
        "order_id": "broker-2",
        "price": "0.5", "size": "1",
        "status": settled_status,
    })
    assert len(out) == 1
    assert out[0]["kind"] == EVENT_FILL


def test_trade_frame_without_status_field_still_emits_fill():
    """Older user-channel emissions and our hermetic tests do not always
    carry a ``status`` field; the absence must not silently drop the
    fill or every existing integration test would break.
    """
    out = parse_message({
        "event_type": "trade",
        "id": "t-3",
        "order_id": "broker-3",
        "price": "0.5", "size": "1",
    })
    assert len(out) == 1
    assert out[0]["kind"] == EVENT_FILL


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
