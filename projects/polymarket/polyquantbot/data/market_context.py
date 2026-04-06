from typing import Dict
import structlog
from .polymarket_api import fetch_market_details

log = structlog.get_logger(__name__)
market_cache: Dict[str, dict] = {}


async def get_market_context(market_id: str) -> dict:
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
    except Exception as e:
        log.warning("market_context_api_failed", market_id=market_id, error=str(e))
        return {
            "name": f"Market #{market_id}",
            "category": "unknown",
            "resolution": "N/A",
        }
