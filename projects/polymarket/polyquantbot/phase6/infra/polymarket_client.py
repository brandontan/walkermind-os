"""Polymarket Gamma API client — Phase 6. Unchanged from Phase 5."""
from __future__ import annotations

import asyncio
import json
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
    p_market: float
    volume: float
    active: bool
    spread: float = 0.01


async def fetch_markets(limit: int = 20) -> list[MarketData]:
    """Fetch and parse active markets from Polymarket Gamma API.

    Retries up to MAX_RETRIES times with exponential backoff.
    Returns empty list on total failure.
    """
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                resp = await client.get(
                    GAMMA_API,
                    params={"limit": limit, "active": "true", "closed": "false"},
                )
                resp.raise_for_status()
                data = resp.json()
                markets = [_parse_market(m) for m in data]
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


def _parse_market(raw: dict[str, Any]) -> MarketData | None:
    """Parse a raw API response dict into MarketData."""
    try:
        outcome_prices = raw.get("outcomePrices", [])
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)
        if not outcome_prices or len(outcome_prices) < 1:
            return None
        best_ask = float(outcome_prices[0])
        best_bid = 1.0 - best_ask
        spread = max(abs(best_ask - best_bid) * 0.05, 0.005)
        return MarketData(
            market_id=str(raw.get("id", raw.get("conditionId", ""))),
            question=str(raw.get("question", "")),
            p_market=best_ask,
            volume=float(raw.get("volume", 0.0)),
            active=bool(raw.get("active", True)),
            spread=round(spread, 6),
        )
    except Exception as exc:
        log.warning("market_parse_error", error=str(exc))
        return None
