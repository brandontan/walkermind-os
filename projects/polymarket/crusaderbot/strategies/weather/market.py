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

    # Pattern: "above X" / "over X" / "exceed(s/ing) X" / "at least X"
    #           "X or above" / "X° or above" / "X or more" / "X° or higher"
    m = re.search(
        r"(?:above|over|exceed(?:s|ing)?|at\s+least)\s+([-+]?\d+(?:\.\d+)?)"
        r"|([-+]?\d+(?:\.\d+)?)\s*(?:°[fc]|°|f|degrees)?\s*(?:or\s+)?(?:above|over|more|higher)",
        q,
    )
    if m:
        val = float(m.group(1) or m.group(2))
        low, high = val, float("inf")

    # Pattern: "below X" / "under X" / "at most X" / "no/not more than X"
    #           "X or below" / "X° or lower" / "X or less"
    if low is None:
        m = re.search(
            r"(?:below|under|at\s+most|not?\s+more\s+than)\s+([-+]?\d+(?:\.\d+)?)"
            r"|([-+]?\d+(?:\.\d+)?)\s*(?:°[fc]|°|f|degrees)?\s*(?:or\s+)?(?:below|under|lower|less)",
            q,
        )
        if m:
            val = float(m.group(1) or m.group(2))
            low, high = float("-inf"), val

    # Pattern: "between X and Y" / "X-Y" / "X to Y"
    if low is None:
        m = re.search(
            r"between\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", q
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


_MAX_BOOK_FETCH: int = 40  # cap live CLOB book reads per weather scan


def _book_quote(book: object) -> tuple[float | None, float | None, float]:
    """Real ``(mid, spread, two_sided_depth_usdc)`` from a CLOB ``/book`` dict.

    Returns ``(None, None, 0.0)`` when the book is not genuinely two-sided
    (missing bids or asks, or a crossed/degenerate book). The caller MUST then
    skip the market rather than fabricate a 0.50 placeholder — feeding a fake
    price into the edge model is exactly the bug this fix removes.
    ``mid`` = bid/ask midpoint; ``spread`` = best_ask − best_bid; depth = summed
    notional on both sides (a real-liquidity proxy).
    """
    if not isinstance(book, dict):
        return None, None, 0.0

    def _levels(side: object) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        if isinstance(side, list):
            for lvl in side:
                if isinstance(lvl, dict):
                    try:
                        out.append((float(lvl.get("price")), float(lvl.get("size"))))
                    except (TypeError, ValueError):
                        continue
        return out

    bid_lvls = _levels(book.get("bids"))
    ask_lvls = _levels(book.get("asks"))
    if not bid_lvls or not ask_lvls:
        return None, None, 0.0
    best_bid = max(p for p, _ in bid_lvls)
    best_ask = min(p for p, _ in ask_lvls)
    if not (0.0 < best_bid <= best_ask < 1.0):
        return None, None, 0.0
    mid = (best_bid + best_ask) / 2.0
    spread = best_ask - best_bid
    depth = sum(p * s for p, s in bid_lvls) + sum(p * s for p, s in ask_lvls)
    return mid, spread, depth


def _extract_yes_token(m: dict) -> str | None:
    """First (YES) CLOB token id from a Gamma market dict, or None."""
    raw = m.get("clobTokenIds") or m.get("clob_token_ids")
    if isinstance(raw, str):
        import json as _json
        try:
            raw = _json.loads(raw)
        except Exception:
            raw = None
    if isinstance(raw, list) and raw and raw[0]:
        return str(raw[0])
    return None


def _parse_gamma_outcomes(m: dict) -> tuple[float | None, float | None]:
    """Real ``(yes, no)`` from Gamma ``outcomePrices``, or ``(None, None)`` when
    absent or the 0.50/0.50 placeholder (Polymarket's "no book yet" sentinel)."""
    outcomes = m.get("outcomePrices") or m.get("outcome_prices")
    if isinstance(outcomes, str):
        import json as _json
        try:
            outcomes = _json.loads(outcomes)
        except Exception:
            outcomes = None
    if not isinstance(outcomes, list) or len(outcomes) < 2:
        return None, None
    try:
        yes_p = float(outcomes[0])
        no_p = float(outcomes[1])
    except (TypeError, ValueError):
        return None, None
    if abs(yes_p - 0.5) < 1e-9 and abs(no_p - 0.5) < 1e-9:
        return None, None  # placeholder — treat as "no real Gamma price"
    return yes_p, no_p


async def fetch_weather_markets(
    city: str | None = None,
    limit: int = 100,
    book_fetcher: Any | None = None,
) -> list[WeatherMarket]:
    """Query Gamma for active weather markets, priced from the REAL CLOB book.

    Ordered by ``liquidity`` (not ``startDate``, which biased toward brand-new
    unpriced markets). Each market uses its real Gamma outcome price when
    present; when Gamma carries only the 0.50/0.50 placeholder, the live CLOB
    midpoint is fetched via ``book_fetcher`` (default
    ``integrations.polymarket.get_book``). A market with no real two-sided book
    is SKIPPED — never emitted with a fabricated 0.50 price.
    """
    params: dict[str, Any] = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "liquidity",
        "ascending": "false",
    }
    # Do NOT use tag_slug=weather — Polymarket weather markets carry no tags.
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_GAMMA_BASE}/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("gamma markets fetch failed", extra={"err": str(exc)})
        return []
    return await _build_weather_markets(data, city, book_fetcher)


async def _build_weather_markets(
    data: object,
    city: str | None,
    book_fetcher: Any | None,
) -> list[WeatherMarket]:
    """Assemble ``WeatherMarket`` rows from a raw Gamma payload, pricing each
    from the real CLOB book when Gamma has only a placeholder.

    Free of HTTP except the injected ``book_fetcher`` (an async ``token_id ->
    book dict`` callable) so it is hermetically testable. Markets that cannot be
    priced honestly are skipped — never emitted at a fabricated 0.50.
    """
    rows = (
        data if isinstance(data, list)
        else (data.get("markets", []) if isinstance(data, dict) else [])
    )
    if book_fetcher is None:
        from ...integrations.polymarket import get_book as book_fetcher  # lazy
    markets: list[WeatherMarket] = []
    book_reads = 0
    for m in rows:
        if not isinstance(m, dict):
            continue
        question = m.get("question") or ""
        if not _is_weather_market(question):
            continue
        if city and city.lower() not in question.lower():
            continue

        yes_p, no_p = _parse_gamma_outcomes(m)
        spread = abs((yes_p or 0.0) + (no_p or 0.0) - 1.0) if yes_p is not None else 0.0
        if yes_p is None:
            # Gamma gave only the 0.50 placeholder -> consult the real CLOB book.
            token = _extract_yes_token(m)
            if token is None or book_reads >= _MAX_BOOK_FETCH:
                continue  # cannot price honestly -> skip (no fabricated 0.50)
            book_reads += 1
            try:
                book = await book_fetcher(token)
            except Exception as exc:  # noqa: BLE001 — fail-soft per market
                log.warning("weather clob book fetch failed", extra={"err": str(exc)})
                continue
            mid, sp, _depth = _book_quote(book)
            if mid is None:
                continue  # genuinely unpriced/illiquid -> skip
            yes_p, no_p, spread = mid, 1.0 - mid, (sp or 0.0)

        vol_24h = float(m.get("volume24hr") or m.get("volume_24hr") or 0)
        end_date = m.get("endDate") or m.get("end_date") or ""
        market_id = str(m.get("id") or "")
        condition_id = str(m.get("conditionId") or m.get("condition_id") or market_id)
        bucket_low, bucket_high = _extract_bucket(question)

        markets.append(WeatherMarket(
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
        ))
    return markets
