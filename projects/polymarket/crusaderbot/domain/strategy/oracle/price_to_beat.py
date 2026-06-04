"""Capture the candle open reference price (Polymarket "Price to Beat").

The BTC up/down candle markets resolve UP/DOWN relative to the candle open —
Polymarket surfaces this as the market's **"Price to Beat"**. Chunk 3 needs it
as the ``price_to_beat`` baseline for the ``delta = (chainlink_now -
price_to_beat) / price_to_beat`` edge calc; this module only *captures* it.

Pure, network-free, side-effect-free: it extracts the value from a Polymarket
market metadata dict (Gamma shape). Honest by construction — when no reference
is present it returns ``None`` rather than guessing, so a missing baseline can
never be traded as if it were real.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import structlog

log = structlog.get_logger(__name__)

# Explicit numeric fields that may carry the candle-open reference directly.
# Checked before any text parsing. Ordered most- to least-specific.
_PRICE_TO_BEAT_KEYS: tuple[str, ...] = (
    "priceToBeat",
    "price_to_beat",
    "openPrice",
    "open_price",
    "strikePrice",
    "strike_price",
    "strike",
)

# Matches a USD figure inside a question/description, e.g. "$104,250.50" or
# "104250" — used only as a fallback when no explicit field is present.
_DOLLAR_RE = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")

# Sanity band for a BTC/USD reference. A parsed figure outside this range is
# almost certainly not the candle open (e.g. a percentage, a year, an id) and is
# rejected rather than returned as a bogus baseline.
_MIN_BTC_USD = 1_000.0
_MAX_BTC_USD = 100_000_000.0


def _coerce_float(value: Any) -> Optional[float]:
    """Best-effort float coercion; returns None for unparseable / non-finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf guard
        return None
    return out


def _in_band(value: Optional[float]) -> Optional[float]:
    """Return value only if it is a plausible BTC/USD level, else None."""
    if value is None:
        return None
    if _MIN_BTC_USD <= value <= _MAX_BTC_USD:
        return value
    return None


def _from_explicit_fields(market: dict[str, Any]) -> Optional[float]:
    for key in _PRICE_TO_BEAT_KEYS:
        if key in market:
            band = _in_band(_coerce_float(market.get(key)))
            if band is not None:
                return band
    return None


def _from_text(market: dict[str, Any]) -> Optional[float]:
    for key in ("question", "title", "description"):
        text = market.get(key)
        if not isinstance(text, str):
            continue
        for raw in _DOLLAR_RE.findall(text):
            band = _in_band(_coerce_float(raw))
            if band is not None:
                return band
    return None


def get_price_to_beat(market: dict[str, Any]) -> Optional[float]:
    """Extract the candle-open "Price to Beat" from a Polymarket market dict.

    Resolution order: explicit numeric fields first, then a sanity-banded USD
    figure parsed from the question/title/description. Returns ``None`` when no
    plausible reference exists — callers MUST treat ``None`` as "no baseline"
    and skip, never substitute a placeholder.
    """
    if not isinstance(market, dict):
        return None
    value = _from_explicit_fields(market)
    if value is None:
        value = _from_text(market)
    if value is None:
        log.debug(
            "price_to_beat not found",
            slug=market.get("slug"),
            condition_id=market.get("conditionId") or market.get("condition_id"),
        )
    return value
