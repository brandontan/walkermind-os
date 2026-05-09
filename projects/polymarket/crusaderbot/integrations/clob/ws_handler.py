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


def _normalise_fill(payload: dict) -> list[dict]:
    """Translate a user-channel ``trade`` / ``user_fill`` frame into one
    or more normalised fill events.

    Polymarket's user-channel trade frames carry separate ids for the
    taker order and each maker order:
      * ``taker_order_id`` — the incoming taker order (top-level)
      * ``maker_orders[].order_id`` — one entry per maker that
        participated, each with its own matched size (`matched_amount`
        or `size`)

    When OUR order is the maker side (e.g. a resting GTC limit), the
    bot's order id appears INSIDE ``maker_orders[]``, NOT at the top
    level — so a fallback that only reads ``taker_order_id`` would
    drop every maker fill until the polling loop reconciled it. This
    function emits one event per candidate broker order id (both maker
    side and taker side), with synthetic per-event ``fill_id`` values
    so the lifecycle's ``ON CONFLICT (fill_id) DO NOTHING`` constraint
    treats each side independently. The ``adapter.py``
    ``_trade_matches_order`` helper already follows the same maker-
    orders-vs-taker discipline for the REST trades endpoint; this
    keeps the two paths in sync.

    Returns ``[]`` when no usable order id can be extracted.
    """
    trade_id = (
        payload.get("id")
        or payload.get("fill_id")
        or payload.get("trade_id")
        or payload.get("tradeID")
    )
    if not trade_id:
        return []
    trade_id = str(trade_id)
    trade_price = _coerce_float(payload.get("price"))
    trade_size = _coerce_float(payload.get("size"))
    side = str(payload.get("side") or "").lower() or None

    out: list[dict] = []
    seen: set[str] = set()

    maker_orders = payload.get("maker_orders") or payload.get("makerOrders")
    if isinstance(maker_orders, list):
        for idx, mo in enumerate(maker_orders):
            if not isinstance(mo, dict):
                continue
            mo_id = (
                mo.get("order_id")
                or mo.get("orderID")
                or mo.get("id")
            )
            if not mo_id:
                continue
            mo_id = str(mo_id)
            mo_size = _coerce_float(
                mo.get("matched_amount")
                or mo.get("size")
                or mo.get("matched_size")
                or mo.get("filled_size")
            )
            mo_price = _coerce_float(mo.get("price")) or trade_price
            if mo_price is None or mo_size is None or mo_size <= 0:
                continue
            seen.add(mo_id)
            out.append({
                "broker_order_id": mo_id,
                "fill_id": f"{trade_id}-m-{idx}",
                "price": mo_price,
                "size": mo_size,
                "side": str(mo.get("side") or "").lower() or None,
                "raw": payload,
            })

    taker_id = (
        payload.get("taker_order_id")
        or payload.get("takerOrderID")
        or payload.get("taker_orderID")
    )
    if taker_id:
        taker_id = str(taker_id)
        if (
            taker_id not in seen
            and trade_price is not None
            and trade_size is not None
            and trade_size > 0
        ):
            out.append({
                "broker_order_id": taker_id,
                "fill_id": f"{trade_id}-t",
                "price": trade_price,
                "size": trade_size,
                "side": side,
                "raw": payload,
            })
            seen.add(taker_id)

    if out:
        return out

    # Fallback: legacy single-order shape (used by some integration
    # tests and broker variants where the order id sits at the top
    # level without maker/taker splits).
    legacy_id = (
        payload.get("order_id")
        or payload.get("orderID")
        or payload.get("maker_order_id")
    )
    if (
        legacy_id
        and trade_price is not None
        and trade_size is not None
        and trade_size > 0
    ):
        out.append({
            "broker_order_id": str(legacy_id),
            "fill_id": trade_id,
            "price": trade_price,
            "size": trade_size,
            "side": side,
            "raw": payload,
        })
    return out


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
        if not normalised:
            logger.warning("ws_handler: dropping malformed user_fill: %s", message)
            return []
        return [{"kind": EVENT_FILL, **fill} for fill in normalised]

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
