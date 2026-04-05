from typing import Dict, Optional
import structlog
from data.polymarket_api import fetch_market_details  # Assume this exists

log = structlog.get_logger(__name__)
market_cache: Dict[str, dict] = {}

async def get_market_context(market_id: str) -> dict:
    """
    Fetch market context from Polymarket API.
    Returns:
        {
            "name": str,
            "category": str,
            "resolution": str,
        }
    """
    if market_id in market_cache:
        return market_cache[market_id]

    try:
        market_data = await fetch_market_details(market_id)
        context = {
            "name": market_data.get("question", {}).get("title", f"Market #{market_id}"),
            "category": market_data.get("category", "Unknown"),
            "resolution": market_data.get("end_date", "N/A"),
        }
        market_cache[market_id] = context
        return context
    except Exception as e:
        log.warning(f"API failed for {market_id}: {e}")
        fallback = {
            "name": f"Market #{market_id}",
            "category": "Unknown",
            "resolution": "N/A",
        }
        market_cache[market_id] = fallback
        return fallback
