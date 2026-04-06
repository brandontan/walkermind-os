"""Telegram-controlled market scope state and filtering helpers."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

MARKET_SCOPE_CATEGORIES: tuple[str, ...] = (
    "Breaking",
    "Politics",
    "Trump",
    "Crypto",
    "Sports",
    "Elections",
    "World",
    "Business",
    "Geopolitics",
    "Finance",
    "Tech",
    "Culture",
    "Economy",
    "Climate",
    "Bonds",
)

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Breaking": ("breaking", "urgent", "live now"),
    "Politics": ("politic", "senate", "congress", "government"),
    "Trump": ("trump",),
    "Crypto": ("crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "token"),
    "Sports": ("sport", "nba", "nfl", "mlb", "nhl", "soccer", "football", "ufc"),
    "Elections": ("election", "primary", "ballot", "vote"),
    "World": ("world", "global", "international"),
    "Business": ("business", "company", "corporate", "earnings", "ceo"),
    "Geopolitics": ("geopolit", "war", "conflict", "nato", "diplomac"),
    "Finance": ("finance", "fed", "interest rate", "stocks", "market cap", "nasdaq"),
    "Tech": ("tech", "ai", "openai", "apple", "google", "microsoft", "meta"),
    "Culture": ("culture", "movie", "music", "hollywood", "celebrity"),
    "Economy": ("economy", "gdp", "inflation", "recession", "jobs"),
    "Climate": ("climate", "weather", "temperature", "co2", "emissions"),
    "Bonds": ("bond", "treasury", "yield curve", "10y", "2y"),
}

_lock = asyncio.Lock()
_all_markets_enabled: bool = True
_enabled_categories: set[str] = set()


def _category_set() -> set[str]:
    return set(MARKET_SCOPE_CATEGORIES)


def _normalize_category(name: str) -> str:
    lowered = name.strip().lower()
    for category in MARKET_SCOPE_CATEGORIES:
        if lowered == category.lower():
            return category
    return ""


def _as_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _infer_category(market: Mapping[str, Any]) -> str:
    explicit_category = _normalize_category(_as_text(market.get("category")))
    if explicit_category:
        return explicit_category

    searchable_parts: list[str] = []
    for key in ("question", "title", "name", "description"):
        searchable_parts.append(_as_text(market.get(key)))

    tags = market.get("tags")
    if isinstance(tags, list):
        searchable_parts.extend(_as_text(tag) for tag in tags)

    searchable = " ".join(part.lower() for part in searchable_parts if part)
    if not searchable:
        return ""

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in searchable for keyword in keywords):
            return category

    return ""


def get_market_scope_snapshot() -> dict[str, Any]:
    enabled = sorted(_enabled_categories)
    selection_type = "All Markets" if _all_markets_enabled else "Categories"
    if _all_markets_enabled:
        summary = "Trading scope: all allowed markets."
        scope_label = "All Markets"
    elif enabled:
        summary = f"Trading scope: {len(enabled)} selected categories only."
        scope_label = f"Categories ({len(enabled)})"
    else:
        summary = "Trading scope: blocked — no active categories selected."
        scope_label = "No Active Categories"
    return {
        "all_markets_enabled": _all_markets_enabled,
        "enabled_categories": enabled,
        "selection_type": selection_type,
        "active_categories_count": len(enabled),
        "trading_scope_summary": summary,
        "scope_label": scope_label,
        "can_trade": _all_markets_enabled or bool(enabled),
        "supported_categories": list(MARKET_SCOPE_CATEGORIES),
    }


async def toggle_all_markets() -> dict[str, Any]:
    global _all_markets_enabled  # noqa: PLW0603
    async with _lock:
        _all_markets_enabled = not _all_markets_enabled
        return get_market_scope_snapshot()


async def toggle_category(category: str) -> dict[str, Any]:
    global _all_markets_enabled  # noqa: PLW0603
    normalized = _normalize_category(category)
    if not normalized:
        return get_market_scope_snapshot()

    async with _lock:
        if normalized in _enabled_categories:
            _enabled_categories.remove(normalized)
        else:
            _enabled_categories.add(normalized)
        _all_markets_enabled = False
        return get_market_scope_snapshot()


async def apply_market_scope(markets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = get_market_scope_snapshot()
    if snapshot["all_markets_enabled"]:
        return markets, snapshot

    enabled = set(snapshot["enabled_categories"])
    if not enabled:
        return [], snapshot

    filtered = [market for market in markets if _infer_category(market) in enabled]
    return filtered, snapshot
