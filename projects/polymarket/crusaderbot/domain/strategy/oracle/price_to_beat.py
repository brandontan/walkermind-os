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

# Matches a USD figure inside a question/description, e.g. "$104,250.50" — used
# only as a fallback when no explicit field is present. The "$" is REQUIRED so a
# bare number (year like 2026, block number, id) that happens to land inside the
# sanity band cannot be mistaken for the candle open; a missing "$" yields None
# (caller skips) rather than a fabricated baseline.
_DOLLAR_RE = re.compile(r"\$\s*([-+]?\d+[\d,]*(?:\.\d+)?)")

# Per-asset sanity bands for a USD candle-open reference. A parsed figure outside
# the band is almost certainly not the candle open (a percentage, a year, an id)
# and is rejected rather than returned as a bogus baseline. The band is
# ASSET-AWARE: the oracle is multi-asset (BTC/ETH/SOL...), and a single BTC-scaled
# band (>= $1,000) silently rejected every SOL reference (~$70) -> permanent
# no_price_to_beat for SOL. Each band is wide enough to cover realistic price
# regimes for that asset with margin.
_ASSET_BANDS: dict[str, tuple[float, float]] = {
    "btc": (1_000.0, 100_000_000.0),
    "eth": (10.0, 10_000_000.0),
    "sol": (0.5, 1_000_000.0),
}
# Fallback for any symbol not explicitly mapped: permissive but still finite, so
# garbage / NaN / inf is rejected while an unknown asset's real level passes.
_DEFAULT_BAND: tuple[float, float] = (0.0001, 100_000_000.0)


def _asset_base_from_slug(slug: Any) -> Optional[str]:
    """Lowercase base ticker from a candle slug, e.g. ``sol-updown-5m-..`` -> ``sol``.

    Only ``*-updown-*`` candle slugs yield a base; anything else returns ``None``
    so the permissive default band is used.
    """
    if not isinstance(slug, str) or "-updown-" not in slug:
        return None
    base = slug.split("-", 1)[0].strip().lower()
    return base or None


def _band_for(market: dict[str, Any]) -> tuple[float, float]:
    base = _asset_base_from_slug(market.get("slug"))
    return _ASSET_BANDS.get(base, _DEFAULT_BAND) if base else _DEFAULT_BAND


def _coerce_float(value: Any) -> Optional[float]:
    """Best-effort float coercion; returns None for unparseable / non-finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf guard
        return None
    return out


def _in_band(value: Optional[float], band: tuple[float, float]) -> Optional[float]:
    """Return value only if it is a plausible USD level for the asset, else None."""
    if value is None:
        return None
    lo, hi = band
    if lo <= value <= hi:
        return value
    return None


def _from_explicit_fields(
    market: dict[str, Any], band: tuple[float, float]
) -> Optional[float]:
    for key in _PRICE_TO_BEAT_KEYS:
        if key in market:
            hit = _in_band(_coerce_float(market.get(key)), band)
            if hit is not None:
                return hit
    return None


def _from_text(
    market: dict[str, Any], band: tuple[float, float]
) -> Optional[float]:
    for key in ("question", "title", "description"):
        text = market.get(key)
        if not isinstance(text, str):
            continue
        for raw in _DOLLAR_RE.findall(text):
            hit = _in_band(_coerce_float(raw), band)
            if hit is not None:
                return hit
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
    band = _band_for(market)
    value = _from_explicit_fields(market, band)
    if value is None:
        value = _from_text(market, band)
    if value is None:
        log.debug(
            "price_to_beat not found",
            slug=market.get("slug"),
            condition_id=market.get("conditionId") or market.get("condition_id"),
        )
    return value
