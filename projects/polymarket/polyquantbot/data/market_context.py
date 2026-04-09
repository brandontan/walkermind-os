from __future__ import annotations

from typing import Any

import structlog

from .ingestion.falcon_alpha import (
    FalconAPIClient,
    fetch_external_alpha_with_fallback,
    get_cached_market_title,
)
from .polymarket_api import fetch_market_details

log = structlog.get_logger(__name__)
market_cache: dict[str, dict[str, Any]] = {}
market_title_cache: dict[str, str] = {}


async def get_market_context(market_id: str) -> dict[str, Any]:
    """Fetch market context from Polymarket API with in-memory cache.

    Returns:
        {
            "name": str,
            "category": str,
            "resolution": str,
        }
    Never returns None — falls back to safe defaults on API failure.
    Fallback responses are NOT cached so recovery is possible on retry.
    """
    if market_id in market_cache:
        return market_cache[market_id]

    try:
        raw = await fetch_market_details(market_id) or {}
        resolved_title = _resolve_market_title(raw) or market_title_cache.get(market_id, "")
        if resolved_title:
            market_title_cache[market_id] = resolved_title
        context = {
            "name": resolved_title,
            "category": raw.get("category") or "unknown",
            "resolution": raw.get("end_date_iso", raw.get("end_date", "N/A")),
        }
        market_cache[market_id] = context
        return context
    except Exception as exc:
        log.warning("market_context_api_failed", market_id=market_id, error=str(exc))
        cached_title = market_title_cache.get(market_id) or get_cached_market_title(market_id)
        return {
            "name": cached_title or f"Market {market_id}",
            "category": "unknown",
            "resolution": "N/A",
        }


async def get_market_context_with_external_alpha(
    *,
    market_id: str,
    token_id: str,
    falcon_client: FalconAPIClient | None = None,
) -> dict[str, Any]:
    """Merge internal market context with external Falcon alpha.

    Integration is data-layer only; strategy logic is unchanged. The returned fields
    are shaped to be consumed by existing S2/S3/S5 strategy inputs.
    """
    internal = await get_market_context(market_id)
    client = falcon_client or FalconAPIClient()
    external = await fetch_external_alpha_with_fallback(client, market_id=market_id, token_id=token_id)

    return {
        **internal,
        "market_id": market_id,
        "market_title": external.get("market_title") or internal.get("name", "") or market_title_cache.get(market_id, ""),
        "price": float(external.get("price", 0.0)),
        "volume": float(external.get("volume", 0.0)),
        "momentum": float(external.get("momentum", 0.0)),
        "liquidity_usd": float(external.get("liquidity", 0.0)),
        "orderbook_depth_usd": float(external.get("liquidity", 0.0)),
        "smart_money_score": float(external.get("smart_money_indicator", 0.0)),
        "volatility": float(external.get("volatility_snapshot", 0.0)),
    }


def _resolve_market_title(raw_market: dict[str, Any]) -> str:
    for key in ("question", "market_title", "title", "name"):
        value = raw_market.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
