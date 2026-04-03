"""Polymarket market discovery client.

Fetches active markets from the Gamma REST API with retry, timeout, and
graceful fallback so that a transient API failure never crashes the pipeline.

Public API::

    markets = await get_active_markets()
    condition_ids = extract_condition_ids(markets)

Features:
  - 5 s per-request timeout
  - 3 automatic retries with exponential backoff (1 s, 2 s)
  - Graceful fallback: returns [] on total failure instead of raising
  - Structured JSON logging at every stage
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

log = structlog.get_logger()

_DEFAULT_GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
_DEFAULT_TIMEOUT_S: float = 5.0
_DEFAULT_MAX_RETRIES: int = 3


async def get_active_markets(
    gamma_url: str = _DEFAULT_GAMMA_API_URL,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> list[dict]:
    """Fetch active markets from the Gamma REST API.

    Retries up to *max_retries* times with exponential backoff.  On total
    failure the function logs the error and returns an empty list so the
    calling pipeline can decide how to proceed (graceful fallback).

    Args:
        gamma_url: Gamma API base URL.
        timeout_s: Per-request timeout in seconds.
        max_retries: Maximum number of attempts (including the first one).

    Returns:
        List of raw market dicts as returned by the API, or [] on failure.
    """
    try:
        import aiohttp  # optional dependency — checked at call time
    except ImportError:
        log.error(
            "market_fetch_failed",
            error="aiohttp is not installed — run: pip install aiohttp",
        )
        return []

    url = f"{gamma_url.rstrip('/')}/markets"
    params: dict[str, Any] = {
        "active": "true",
        "closed": "false",
        "limit": 100,
    }

    log.info("market_discovery_start", url=url)

    last_error: str = "unknown"
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout_s),
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(
                            f"Gamma API returned HTTP {resp.status} while fetching markets."
                        )
                    data = await resp.json()

            # Normalise response shape (list or dict with 'markets' key)
            if isinstance(data, dict):
                markets: list[dict] = data.get("markets", [])
            elif isinstance(data, list):
                markets = data
            else:
                markets = []

            log.info("markets_fetched", count=len(markets), attempt=attempt + 1)
            return markets

        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt < max_retries - 1:
                delay = 2**attempt  # back-off: 1 s after first failure, 2 s after second
                log.warning(
                    "market_fetch_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=last_error,
                    retry_in_s=delay,
                )
                await asyncio.sleep(delay)

    log.error("market_fetch_failed", error=last_error, attempts=max_retries)
    return []


def extract_condition_ids(markets: list[dict]) -> list[str]:
    """Return the ``conditionId`` field from each market that has one.

    Args:
        markets: Raw market dicts as returned by :func:`get_active_markets`.

    Returns:
        List of non-empty condition ID strings.
    """
    return [
        str(m["conditionId"])
        for m in markets
        if m.get("conditionId")
    ]


def extract_market_data(market: dict) -> dict | None:
    """Safely extract and normalise ``market_id`` and ``p_market`` from a raw
    Gamma API market dict.

    The Gamma API may return prices under ``outcomePrices`` (list of strings)
    or ``prices`` (list of floats).  The market identifier may be ``id``,
    ``conditionId``, or ``market_id``.  A pre-normalised dict that already
    contains ``market_id`` and ``p_market`` keys is also accepted.

    Args:
        market: Raw market dict as returned by :func:`get_active_markets`, or a
                pre-normalised dict with ``market_id`` / ``p_market`` keys.

    Returns:
        ``{"market_id": str, "p_market": float}`` when extraction succeeds and
        the values are valid; ``None`` otherwise.
    """
    try:
        market_id: str | None = (
            market.get("id")
            or market.get("conditionId")
            or market.get("market_id")
        )

        # Try list-based price fields first (raw Gamma API)
        prices = market.get("outcomePrices") or market.get("prices")
        if prices and len(prices) > 0:
            p_market = float(prices[0])
        else:
            # Fall back to scalar p_market key (pre-normalised or test dicts)
            raw_p = market.get("p_market")
            if raw_p is None:
                return None
            p_market = float(raw_p)

        if not (0 < p_market < 1):
            return None

        if not market_id:
            return None

        return {
            "market_id": str(market_id),
            "p_market": p_market,
        }

    except Exception as exc:  # noqa: BLE001
        log.warning("market_parse_error", error=str(exc))
        return None
