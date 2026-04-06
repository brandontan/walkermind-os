"""Telegram-controlled market scope state and filtering helpers."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Mapping

import structlog

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
_scope_state_loaded: bool = False
_log = structlog.get_logger(__name__)
_UNCATEGORIZED_FALLBACK_LABEL: str = "Weak-metadata markets are included as fallback while category mode is active."
_SCOPE_STATE_FILE: Path = Path(
    os.getenv(
        "POLYQUANT_MARKET_SCOPE_STATE_FILE",
        "projects/polymarket/polyquantbot/infra/market_scope_state.json",
    )
)


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


def _normalize_text_blob(value: object) -> str:
    return _as_text(value).lower()


def _metadata_tokens(market: Mapping[str, Any]) -> list[str]:
    tokens: list[str] = []
    base_keys = ("question", "title", "name", "description", "slug", "seriesSlug", "eventSlug")
    for key in base_keys:
        raw = _normalize_text_blob(market.get(key))
        if raw:
            tokens.append(raw)

    tags = market.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            value = _normalize_text_blob(tag)
            if value:
                tokens.append(value)

    events = market.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, Mapping):
                continue
            for key in ("title", "slug", "name"):
                value = _normalize_text_blob(event.get(key))
                if value:
                    tokens.append(value)

    return tokens


def _infer_category(market: Mapping[str, Any]) -> str:
    """Deterministic category inference order.

    1) explicit ``category`` field
    2) direct category name in tag list
    3) keyword scoring across title/question/description/tags/slug/event metadata
    4) tie/no-signal => uncategorized (empty string)
    """
    explicit_category = _normalize_category(_as_text(market.get("category")))
    if explicit_category:
        return explicit_category

    tags = market.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            tag_category = _normalize_category(_as_text(tag))
            if tag_category:
                return tag_category

    searchable = " ".join(_metadata_tokens(market))
    if not searchable:
        return ""

    category_scores: dict[str, int] = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in searchable)
        if hits:
            category_scores[category] = hits

    if not category_scores:
        return ""

    ranked = sorted(
        category_scores.items(),
        key=lambda item: (-item[1], MARKET_SCOPE_CATEGORIES.index(item[0])),
    )
    top_category, top_hits = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == top_hits:
        # Ambiguous metadata: leave uncategorized so fallback policy remains explicit.
        return ""
    return top_category


def _is_weak_metadata_market(market: Mapping[str, Any]) -> bool:
    explicit_signals = 0
    for key in ("category", "question", "title", "name", "description", "slug", "seriesSlug", "eventSlug"):
        if _as_text(market.get(key)):
            explicit_signals += 1
    tags = market.get("tags")
    if isinstance(tags, list) and any(_as_text(tag) for tag in tags):
        explicit_signals += 1
    return explicit_signals <= 2


def _ensure_scope_state_loaded() -> None:
    global _scope_state_loaded  # noqa: PLW0603
    if _scope_state_loaded:
        return
    _scope_state_loaded = True

    if not _SCOPE_STATE_FILE.exists():
        return

    try:
        raw = _SCOPE_STATE_FILE.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return
    except Exception as exc:  # noqa: BLE001
        _log.warning("market_scope_state_load_failed", error=str(exc), state_file=str(_SCOPE_STATE_FILE))
        return

    all_markets = payload.get("all_markets_enabled")
    categories = payload.get("enabled_categories")
    if isinstance(all_markets, bool):
        global _all_markets_enabled  # noqa: PLW0603
        _all_markets_enabled = all_markets
    if isinstance(categories, list):
        global _enabled_categories  # noqa: PLW0603
        _enabled_categories = {name for name in (_normalize_category(_as_text(item)) for item in categories) if name}

    _log.info(
        "market_scope_state_restored",
        all_markets_enabled=_all_markets_enabled,
        enabled_categories=sorted(_enabled_categories),
        state_file=str(_SCOPE_STATE_FILE),
    )


def _persist_scope_state() -> None:
    payload = {
        "all_markets_enabled": _all_markets_enabled,
        "enabled_categories": sorted(_enabled_categories),
        "selection_type": "All Markets" if _all_markets_enabled else "Categories",
    }
    try:
        _SCOPE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SCOPE_STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        _log.warning("market_scope_state_persist_failed", error=str(exc), state_file=str(_SCOPE_STATE_FILE))


def get_market_scope_snapshot() -> dict[str, Any]:
    _ensure_scope_state_loaded()

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
        "fallback_policy": _UNCATEGORIZED_FALLBACK_LABEL,
        "scope_state_file": str(_SCOPE_STATE_FILE),
    }


async def toggle_all_markets() -> dict[str, Any]:
    global _all_markets_enabled  # noqa: PLW0603
    _ensure_scope_state_loaded()

    async with _lock:
        _all_markets_enabled = not _all_markets_enabled
        _persist_scope_state()
        return get_market_scope_snapshot()


async def toggle_category(category: str) -> dict[str, Any]:
    global _all_markets_enabled  # noqa: PLW0603
    _ensure_scope_state_loaded()

    normalized = _normalize_category(category)
    if not normalized:
        return get_market_scope_snapshot()

    async with _lock:
        if normalized in _enabled_categories:
            _enabled_categories.remove(normalized)
        else:
            _enabled_categories.add(normalized)
        _all_markets_enabled = False
        _persist_scope_state()
        return get_market_scope_snapshot()


async def apply_market_scope(markets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = get_market_scope_snapshot()
    if snapshot["all_markets_enabled"]:
        return markets, snapshot

    enabled = set(snapshot["enabled_categories"])
    if not enabled:
        return [], snapshot

    filtered: list[dict[str, Any]] = []
    uncategorized_fallback_count = 0

    for market in markets:
        inferred_category = _infer_category(market)
        if inferred_category in enabled:
            filtered.append(market)
            continue
        if inferred_category:
            continue
        if _is_weak_metadata_market(market):
            filtered.append(market)
            uncategorized_fallback_count += 1

    if uncategorized_fallback_count > 0:
        snapshot = dict(snapshot)
        snapshot["fallback_applied_count"] = uncategorized_fallback_count
        snapshot["trading_scope_summary"] = (
            f"{snapshot['trading_scope_summary']} "
            f"{uncategorized_fallback_count} weak-metadata market(s) included via fallback."
        )

    return filtered, snapshot
