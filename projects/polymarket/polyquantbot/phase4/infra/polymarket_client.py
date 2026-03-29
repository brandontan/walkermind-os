"""Polymarket Gamma API client with retry logic."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

GAMMA_API = "https://gamma-api.polymarket.com/markets"
MAX_RETRIES = 3
TIMEOUT_S = 10


@dataclass
class MarketData:
    """Parsed market snapshot from Gamma API."""

    market_id: str
    question: str
    best_ask: float
    best_bid: float
    volume: float
    active: bool


class PolymarketClient:
    """Fetches live market data from Polymarket Gamma API."""

    async def fetch_markets(self, limit: int = 20) -> list[MarketData]:
        """Fetch and parse markets with up to MAX_RETRIES retries."""
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                    resp = await client.get(
                        GAMMA_API,
                        params={"limit": limit, "active": "true", "closed": "false"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    markets = [self._parse_market(m) for m in data]
                    return [m for m in markets if m is not None]  # type: ignore[misc]
            except Exception as exc:
                wait = 2 ** attempt
                log.warning(
                    "gamma_api_retry",
                    attempt=attempt + 1,
                    wait_seconds=wait,
                    error=str(exc),
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
        return []

    def _parse_market(self, raw: dict[str, Any]) -> MarketData | None:
        """Parse a raw API response dict into MarketData."""
        try:
            outcome_prices = raw.get("outcomePrices", [])
            if isinstance(outcome_prices, str):
                import json
                outcome_prices = json.loads(outcome_prices)
            if not outcome_prices or len(outcome_prices) < 1:
                return None
            best_ask = float(outcome_prices[0])
            best_bid = 1.0 - best_ask
            return MarketData(
                market_id=str(raw.get("id", raw.get("conditionId", ""))),
                question=str(raw.get("question", "")),
                best_ask=best_ask,
                best_bid=best_bid,
                volume=float(raw.get("volume", 0.0)),
                active=bool(raw.get("active", True)),
            )
        except Exception as exc:
            log.warning("market_parse_error", error=str(exc))
            return None
