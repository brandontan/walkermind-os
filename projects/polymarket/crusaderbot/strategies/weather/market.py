"""Polymarket Gamma API integration for weather markets."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_TIMEOUT = httpx.Timeout(15.0, connect=8.0)

_WEATHER_KEYWORDS = (
    "temperature", "high temp", "max temp", "degrees", "fahrenheit",
    "celsius", "weather", "hottest", "coldest",
)


@dataclass
class WeatherMarket:
    market_id: str
    condition_id: str
    question: str
    city: str
    yes_price: float
    no_price: float
    volume_24h: float
    spread: float
    end_date_iso: str
    bucket_low: float | None = None
    bucket_high: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _is_weather_market(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _WEATHER_KEYWORDS)


def _extract_bucket(question: str) -> tuple[float | None, float | None]:
    """Parse temperature bucket bounds from market question text.

    Handles patterns like "above 95°F", "80° or above", "between 80 and 85",
    "85-90°F", etc. Returns (low, high) in °F — converts °C when detected.
    Returns (None, None) when not parseable.
    """
    q = question.lower()
    low: float | None = None
    high: float | None = None

    # Pattern: "above X" / "over X" / "X or above" / "X° or above"
    m = re.search(
        r"(?:above|over)\s+([\d.]+)|([\d.]+)\s*(?:°[fc]|°|f|degrees)?\s*(?:or\s+)?(?:above|over)", q
    )
    if m:
        val = float(m.group(1) or m.group(2))
        low, high = val, float("inf")

    # Pattern: "below X" / "under X" / "X or below" / "X° or below"
    if low is None:
        m = re.search(
            r"(?:below|under)\s+([\d.]+)|([\d.]+)\s*(?:°[fc]|°|f|degrees)?\s*(?:or\s+)?(?:below|under)", q
        )
        if m:
            val = float(m.group(1) or m.group(2))
            low, high = float("-inf"), val

    # Pattern: "between X and Y" / "X-Y" / "X to Y"
    if low is None:
        m = re.search(
            r"between\s+([\d.]+)\s+and\s+([\d.]+)|([\d.]+)\s*(?:-|to)\s*([\d.]+)", q
        )
        if m:
            val_low = float(m.group(1) or m.group(3))
            val_high = float(m.group(2) or m.group(4))
            # Reject date-like collisions ("June 1 and 2" → 1.0, 2.0) by requiring
            # realistic temperature values (>15 handles both °F and °C minimums).
            if val_low > 15.0 and val_high > val_low:
                low, high = val_low, val_high

    if low is None and high is None:
        return None, None

    # Convert Celsius to Fahrenheit when question is denominated in °C
    if "celsius" in q or "°c" in q:
        if low is not None and low != float("-inf"):
            low = round(low * 9.0 / 5.0 + 32.0, 1)
        if high is not None and high != float("inf"):
            high = round(high * 9.0 / 5.0 + 32.0, 1)

    return low, high


async def fetch_weather_markets(
    city: str | None = None,
    limit: int = 100,
) -> list[WeatherMarket]:
    """Query Gamma API for active weather prediction markets.

    Optionally filters by city name. Returns structured WeatherMarket objects.
    """
    params: dict[str, Any] = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "volume24hr",
        "ascending": "false",
    }
    if city:
        params["tag_slug"] = "weather"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_GAMMA_BASE}/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("gamma markets fetch failed", extra={"err": str(exc)})
        return []

    markets: list[WeatherMarket] = []
    for m in (data if isinstance(data, list) else data.get("markets", [])):
        question = m.get("question") or ""
        if not _is_weather_market(question):
            continue
        if city and city.lower() not in question.lower():
            continue

        outcomes = m.get("outcomePrices") or m.get("outcome_prices") or ["0.5", "0.5"]
        if isinstance(outcomes, str):
            import json as _json
            try:
                outcomes = _json.loads(outcomes)
            except Exception:
                outcomes = ["0.5", "0.5"]

        try:
            yes_p = float(outcomes[0]) if len(outcomes) > 0 and outcomes[0] is not None else 0.5
            no_p = float(outcomes[1]) if len(outcomes) > 1 and outcomes[1] is not None else 0.5
        except (ValueError, TypeError, IndexError):
            yes_p, no_p = 0.5, 0.5

        spread = abs(yes_p + no_p - 1.0)
        vol_24h = float(m.get("volume24hr") or m.get("volume_24hr") or 0)
        end_date = m.get("endDate") or m.get("end_date") or ""
        market_id = str(m.get("id") or "")
        condition_id = str(m.get("conditionId") or m.get("condition_id") or market_id)

        bucket_low, bucket_high = _extract_bucket(question)

        wm = WeatherMarket(
            market_id=market_id,
            condition_id=condition_id,
            question=question,
            city=city or "",
            yes_price=yes_p,
            no_price=no_p,
            volume_24h=vol_24h,
            spread=spread,
            end_date_iso=end_date,
            bucket_low=bucket_low,
            bucket_high=bucket_high,
            raw=m,
        )
        markets.append(wm)

    return markets
