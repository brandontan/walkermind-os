"""
Polymarket API client — fetches top N markets.
Endpoint: GET https://gamma-api.polymarket.com/markets
Timeout: 10s, Retry: 3
"""

import asyncio
import json as _json
import structlog
from dataclasses import dataclass
from typing import Any
import aiohttp

log = structlog.get_logger()

POLYMARKET_API = "https://gamma-api.polymarket.com/markets"


@dataclass
class MarketData:
    market_id: str
    question: str
    p_market: float
    volume: float
    spread: float


async def _parse_market(raw: dict[str, Any]) -> MarketData | None:
    """
    Parse raw Gamma API market object.
    Returns None if required fields are missing or invalid.

    Gamma API field reference:
      conditionId   → unique market ID
      question      → human-readable market title
      outcomePrices → JSON string array e.g. '["0.72","0.28"]'
      volumeNum     → total volume in USD (float)
      spread        → bid-ask spread (float, may be absent)
      active        → bool, must be true
      closed        → bool, must be false
    """
    try:
        market_id: str = raw.get("conditionId") or raw.get("id") or ""
        question: str = raw.get("question", "")

        if not market_id or not question:
            return None

        if not raw.get("active", True) or raw.get("closed", False):
            return None

        outcome_prices_raw = raw.get("outcomePrices", "[]")
        if isinstance(outcome_prices_raw, str):
            prices = _json.loads(outcome_prices_raw)
        else:
            prices = outcome_prices_raw

        if not prices or len(prices) < 1:
            return None

        p_market = float(prices[0])
        if not (0.0 < p_market < 1.0):
            return None

        volume = float(raw.get("volumeNum", 0.0))
        spread = float(raw.get("spread", 0.0))

        return MarketData(
            market_id=market_id,
            question=question,
            p_market=p_market,
            volume=volume,
            spread=spread,
        )
    except Exception as exc:
        log.warning("market_parse_failed", error=str(exc))
        return None


async def fetch_markets(limit: int = 10) -> list[MarketData]:
    """Fetch top `limit` active markets from Gamma API with retry."""
    params = {
        "limit": limit,
        "active": "true",
        "closed": "false",
        "order": "volumeNum",
        "ascending": "false",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    last_exc: Exception | None = None

    for attempt in range(1, 4):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(POLYMARKET_API, params=params) as resp:
                    resp.raise_for_status()
                    raw_list: list[dict[str, Any]] = await resp.json()

            markets: list[MarketData] = []
            for raw in raw_list:
                m = await _parse_market(raw)
                if m is not None:
                    markets.append(m)

            log.info("markets_fetched", count=len(markets), attempt=attempt)
            return markets

        except Exception as exc:
            last_exc = exc
            log.warning("fetch_markets_retry", attempt=attempt, error=str(exc))
            await asyncio.sleep(2 ** attempt)

    log.error("fetch_markets_failed", error=str(last_exc))
    return []
