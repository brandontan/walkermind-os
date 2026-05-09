"""Polymarket CLOB WebSocket message parser + dispatcher (Phase 4D).

Pure functions over already-decoded JSON payloads. The transport layer
(``ws.py``) owns socket I/O, reconnect, and heartbeat; this module only
turns CLOB frames into normalised events the lifecycle manager can
consume. Parse errors NEVER raise to the transport layer — the contract
with ``ClobWebSocketClient`` is "every message returns a list of zero
or more events".

CLOB WebSocket message shapes (per docs.polymarket.com /ws-api):

  ``user_fill``           — push event for a fill on one of the user's orders.
                            Carries ``id`` (fill id), ``order_id``, ``price``,
                            ``size``, ``side``, ``timestamp``.
  ``user_order``          — order status transition. Carries ``id``,
                            ``order_id``, ``status`` (matched / canceled /
                            expired / live), ``size_matched``, etc.
  ``last_trade_price``    — market-channel ticker; ignored by the lifecycle.
  ``book``                — orderbook snapshot; ignored.
  ``price_change``        — orderbook delta; ignored.
  ``tick_size_change``    — market metadata; ignored.

Anything we do not recognise is logged and dropped. The transport must
NEVER crash on a schema change the broker rolls out without warning.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Event kinds emitted by ``parse_message`` for the lifecycle dispatcher.
EVENT_FILL = "fill"
EVENT_ORDER_UPDATE = "order_update"

# Order status strings used by Polymarket's user channel. Mapped to the
# normalised statuses ``OrderLifecycleManager`` already understands so the
# WebSocket and polling paths land in the exact same handlers.
_STATUS_MAP = {
    "matched": "filled",
    "filled": "filled",
    "complete": "filled",
    "completed": "filled",
    "closed": "filled",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "expired": "expired",
    "live": "open",
    "open": "open",
    "unmatched": "open",
    "delayed": "open",
}


def normalise_status(raw: Any) -> str:
    """Map a broker status string to the lifecycle's four buckets.

    Same prefix-stripping rules as ``lifecycle._broker_status`` so a
    rolled-out enum like ``ORDER_STATUS_CANCELED_MARKET_RESOLVED`` lands
    in ``cancelled`` rather than the silent ``open`` bucket.
    """
    s = str(raw or "").strip().lower()
    if s.startswith("order_status_"):
        s = s[len("order_status_"):]
    if s in _STATUS_MAP:
        return _STATUS_MAP[s]
    if s.startswith("cancel"):
        return "cancelled"
    if s in {"matched", "filled", "closed", "complete", "completed"}:
        return "filled"
    return "open"


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_fill(payload: dict) -> Optional[dict]:
    """Pull (broker_order_id, fill_id, price, size, side) from a user_fill
    frame. Returns ``None`` when any required field is missing — the
    lifecycle cannot route a fill without an order id and a fill id.
    """
    broker_order_id = (
        payload.get("order_id")
        or payload.get("orderID")
        or payload.get("taker_order_id")
        or payload.get("maker_order_id")
    )
    fill_id = (
        payload.get("id")
        or payload.get("fill_id")
        or payload.get("trade_id")
        or payload.get("tradeID")
    )
    if not broker_order_id or not fill_id:
        return None
    price = _coerce_float(payload.get("price"))
    size = _coerce_float(payload.get("size"))
    if price is None or size is None or size <= 0:
        return None
    side = str(payload.get("side") or "").lower() or None
    return {
        "broker_order_id": str(broker_order_id),
        "fill_id": str(fill_id),
        "price": price,
        "size": size,
        "side": side,
        "raw": payload,
    }


def _normalise_order_update(payload: dict) -> Optional[dict]:
    """Pull (broker_order_id, status) plus optional fill aggregates from a
    user_order frame. Returns ``None`` when the frame has no order id —
    we cannot reconcile against ``orders.polymarket_order_id`` without it.
    """
    broker_order_id = (
        payload.get("order_id")
        or payload.get("orderID")
        or payload.get("id")
    )
    if not broker_order_id:
        return None
    status = normalise_status(
        payload.get("status")
        or payload.get("type")
        or payload.get("event_type")
    )
    return {
        "broker_order_id": str(broker_order_id),
        "status": status,
        "size_matched": _coerce_float(
            payload.get("size_matched") or payload.get("sizeMatched")
        ),
        "price": _coerce_float(payload.get("price")),
        "raw": payload,
    }


def parse_message(message: Any) -> list[dict]:
    """Translate a single decoded CLOB WebSocket payload into events.

    Polymarket sometimes batches frames into a JSON array; both the
    array and single-object shapes are accepted. Unknown event types
    are logged at DEBUG and dropped — the WS loop must never crash on
    a schema rollout.
    """
    if message is None:
        return []
    if isinstance(message, list):
        out: list[dict] = []
        for item in message:
            out.extend(parse_message(item))
        return out
    if not isinstance(message, dict):
        logger.debug("ws_handler: dropping non-dict message: %r", message)
        return []

    event_type = str(
        message.get("event_type")
        or message.get("type")
        or ""
    ).lower()

    if event_type == "user_fill" or event_type == "trade":
        normalised = _normalise_fill(message)
        if normalised is None:
            logger.warning("ws_handler: dropping malformed user_fill: %s", message)
            return []
        return [{"kind": EVENT_FILL, **normalised}]

    if event_type == "user_order" or event_type == "order":
        normalised = _normalise_order_update(message)
        if normalised is None:
            logger.warning("ws_handler: dropping malformed user_order: %s", message)
            return []
        return [{"kind": EVENT_ORDER_UPDATE, **normalised}]

    # Channel chatter we explicitly ignore. Logged at DEBUG only; do NOT
    # raise / warn — these arrive at every market tick.
    if event_type in {
        "last_trade_price", "book", "price_change",
        "tick_size_change", "pong", "subscribed",
    }:
        return []

    logger.debug("ws_handler: ignoring unknown event_type=%r", event_type)
    return []
