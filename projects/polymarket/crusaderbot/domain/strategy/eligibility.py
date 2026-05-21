"""Per-strategy market eligibility filters.

Standalone module so any scan loop can consult eligibility before invoking a
strategy. Other strategies remain unaffected — eligibility is opt-in per
strategy name. The single current consumer is ConfluenceScalperStrategy,
restricted to crypto markets on a fixed asset whitelist.

Issue #1269 / WARP/webtrader-confluence-scalper.
"""
from __future__ import annotations

import re
from typing import Any

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


def eligible_market_ids_for_confluence_scalper(markets: list[dict]) -> set[str]:
    """Return the set of Gamma market ``id`` strings eligible for confluence_scalper."""
    out: set[str] = set()
    for m in markets:
        if not is_confluence_scalper_eligible(m):
            continue
        market_id = str(m.get("id") or "")
        if market_id:
            out.add(market_id)
    return out


__all__ = [
    "CONFLUENCE_SCALPER_ASSETS",
    "CONFLUENCE_SCALPER_ASSET_PATTERN",
    "is_confluence_scalper_eligible",
    "eligible_market_ids_for_confluence_scalper",
]
