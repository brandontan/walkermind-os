from __future__ import annotations

from typing import Any

import structlog

from .ingestion.falcon_alpha import FalconAPIClient, fetch_external_alpha_with_fallback
from .polymarket_api import fetch_market_details

log = structlog.get_logger(__name__)
market_cache: dict[str, dict[str, Any]] = {}


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
        q = raw.get("question", "")
        name = q if isinstance(q, str) and q else f"Market #{market_id}"
        context = {
            "name": name,
            "category": raw.get("category") or "unknown",
            "resolution": raw.get("end_date_iso", raw.get("end_date", "N/A")),
        }
        market_cache[market_id] = context
        return context
    except Exception as exc:
        log.warning("market_context_api_failed", market_id=market_id, error=str(exc))
        return {
            "name": f"Market #{market_id}",
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
        "market_title": external.get("market_title") or internal.get("name", ""),
        "price": float(external.get("price", 0.0)),
        "volume": float(external.get("volume", 0.0)),
        "momentum": float(external.get("momentum", 0.0)),
        "liquidity_usd": float(external.get("liquidity", 0.0)),
        "orderbook_depth_usd": float(external.get("liquidity", 0.0)),
        "smart_money_score": float(external.get("smart_money_indicator", 0.0)),
        "volatility": float(external.get("volatility_snapshot", 0.0)),
    }
