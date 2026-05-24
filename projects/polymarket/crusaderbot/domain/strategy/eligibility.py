"""Per-strategy market eligibility filters.

Standalone module so any scan loop can consult eligibility before invoking a
strategy. Other strategies remain unaffected — eligibility is opt-in per
strategy name. The single current consumer is ConfluenceScalperStrategy,
restricted to crypto markets on a fixed asset whitelist.

Issue #1269 / WARP/webtrader-confluence-scalper.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, Literal

# Whitelisted assets for ConfluenceScalperStrategy. Ticker symbols + full
# names are both accepted so question text like "Bitcoin all time high" and
# "BTC > $200k" both match. Word boundaries on the compiled pattern below
# prevent substring false positives such as "hyperventilate" matching HYPE
# or "doge-style" matching DOGE.
CONFLUENCE_SCALPER_ASSETS: tuple[str, ...] = (
    "btc", "bitcoin",
    "eth", "ethereum",
    "sol", "solana",
    "xrp", "ripple",
    "doge", "dogecoin",
    "bnb", "binance coin",
    "hype", "hyperliquid",
)

CONFLUENCE_SCALPER_ASSET_PATTERN: re.Pattern[str] = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in CONFLUENCE_SCALPER_ASSETS) + r")\b",
    re.IGNORECASE,
)


def is_confluence_scalper_eligible(market: Any) -> bool:
    """Return True if a Gamma market dict qualifies for the confluence scalper.

    Two gates must both pass:
      - category resolves to ``Crypto`` (case-insensitive match on Gamma's
        ``category``, ``groupItemTitle``, or ``slug`` fields).
      - market title/question references one of the whitelisted assets
        (BTC, ETH, SOL, XRP, DOGE, BNB, HYPE), matched with word boundaries
        so "hyperventilate" or "doge-style" do not produce false positives.

    Non-crypto markets and crypto markets outside the asset whitelist are
    skipped so existing strategies remain unaffected.
    """
    if not isinstance(market, dict):
        return False
    cat = (
        market.get("category")
        or market.get("groupItemTitle")
        or market.get("slug")
        or ""
    )
    if "crypto" not in str(cat).lower():
        return False
    haystack = " ".join(
        str(market.get(field) or "")
        for field in ("question", "title", "slug", "groupItemTitle")
    )
    return bool(CONFLUENCE_SCALPER_ASSET_PATTERN.search(haystack))


def eligible_market_ids_for_confluence_scalper(
    markets: Iterable[Mapping[str, Any]],
) -> set[str]:
    """Return the set of Gamma market ``id`` strings eligible for confluence_scalper.

    Pre-filter helper for any caller that wants to derive a market-id allowlist
    in one pass. The production scan path applies ``is_confluence_scalper_eligible``
    inline inside ``ConfluenceScalperStrategy.scan`` instead — this helper is
    retained for callers that need a set of IDs up front (e.g. tooling, tests).
    """
    out: set[str] = set()
    for m in markets:
        if not is_confluence_scalper_eligible(m):
            continue
        market_id = str(m.get("id") or "")
        if market_id:
            out.add(market_id)
    return out


# ── Short-duration crypto timeframe classification (5m / 15m) ────────────────
# Polymarket Gamma markets carry no structured candle-interval field, so the
# timeframe must be inferred from the market's text (slug / question /
# groupItemTitle) with a corroborating duration fallback. Detection is
# FAIL-CLOSED: an unclassifiable market returns None and is skipped by callers,
# so a renamed slug degrades to "no trade" rather than a wrong-timeframe trade.

CryptoTimeframe = Literal["5m", "15m"]

# 15m checked BEFORE 5m (longest-first) so "5 min" never matches inside the
# "15 min" / "15-minute" forms.
_TF_15M_PATTERN: re.Pattern[str] = re.compile(
    r"\b15[\s-]?(?:m|min|mins|minute|minutes)\b", re.IGNORECASE
)
_TF_5M_PATTERN: re.Pattern[str] = re.compile(
    r"\b5[\s-]?(?:m|min|mins|minute|minutes)\b", re.IGNORECASE
)

# Duration fallback buckets in seconds: (timeframe, lower_bound, upper_bound).
# Tolerant windows around 5 and 15 minutes; corroborative only.
_TF_DURATION_BUCKETS: tuple[tuple[CryptoTimeframe, float, float], ...] = (
    ("5m", 4 * 60, 10 * 60),    # 4–10 min  -> 5m
    ("15m", 10 * 60, 25 * 60),  # 10–25 min -> 15m
)


def _parse_iso(value: Any) -> datetime | None:
    """Parse a Gamma ISO timestamp into an aware datetime, or None on failure."""
    if not value:
        return None
    try:
        clean = str(value).replace("Z", "+00:00")
        if "T" not in clean:
            return None
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def classify_crypto_timeframe(market: Any) -> CryptoTimeframe | None:
    """Return '5m' | '15m' | None for a Gamma market dict.

    Detection order (fail-closed):
      1. Keyword match on question + slug + groupItemTitle (authoritative;
         15m checked before 5m to avoid substring collisions).
      2. Duration fallback: (endDate - startDate) bucketed to ~5 or ~15 min.
      3. None — unclassifiable; the caller must skip the market.

    Does NOT check crypto-ness; compose with ``is_confluence_scalper_eligible``
    via ``is_short_crypto_market``.
    """
    if not isinstance(market, dict):
        return None

    haystack = " ".join(
        str(market.get(field) or "")
        for field in ("question", "title", "slug", "groupItemTitle")
    )
    if _TF_15M_PATTERN.search(haystack):
        return "15m"
    if _TF_5M_PATTERN.search(haystack):
        return "5m"

    start = _parse_iso(market.get("startDate") or market.get("start_date_iso"))
    end = _parse_iso(
        market.get("endDate")
        or market.get("endDateIso")
        or market.get("end_date_iso")
    )
    if start is not None and end is not None:
        duration_s = (end - start).total_seconds()
        if duration_s > 0:
            for tf, lo, hi in _TF_DURATION_BUCKETS:
                if lo <= duration_s < hi:
                    return tf
    return None


def is_short_crypto_market(market: Any, timeframe: str | None) -> bool:
    """True iff ``market`` is a whitelisted crypto market AND its classified
    timeframe matches ``timeframe``.

    ``timeframe=None`` means "any 5m or 15m crypto market" (classification must
    still resolve to a non-None bucket). Non-crypto markets and markets that
    cannot be classified are rejected (fail-closed).
    """
    if not is_confluence_scalper_eligible(market):
        return False
    tf = classify_crypto_timeframe(market)
    if tf is None:
        return False
    if timeframe is None:
        return True
    return tf == timeframe


__all__ = [
    "CONFLUENCE_SCALPER_ASSETS",
    "CONFLUENCE_SCALPER_ASSET_PATTERN",
    "is_confluence_scalper_eligible",
    "eligible_market_ids_for_confluence_scalper",
    "CryptoTimeframe",
    "classify_crypto_timeframe",
    "is_short_crypto_market",
]
