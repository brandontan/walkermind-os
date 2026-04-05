import asyncio
import time
from typing import Dict, Tuple
import structlog

from data.polymarket_api import fetch_market_details

log = structlog.get_logger(__name__)

# ── Cache ─────────────────────────────────────────────────────────────────────
# Structure: { market_id: {"data": {...}, "timestamp": float} }
_CACHE_TTL_SECONDS = 60
_CACHE_MAX_ENTRIES = 100
market_cache: Dict[str, dict] = {}

# ── Metrics ───────────────────────────────────────────────────────────────────
_metrics: Dict[str, int] = {
    "api_success_count": 0,
    "api_fail_count": 0,
    "cache_hit_count": 0,
    "cache_request_count": 0,
}

# ── Retry config ──────────────────────────────────────────────────────────────
_RETRY_DELAYS: Tuple[float, ...] = (0.5, 1.0, 2.0)


def get_metrics() -> dict:
    """Return a snapshot of cache/API metrics."""
    total = _metrics["cache_request_count"]
    hit_rate = _metrics["cache_hit_count"] / total if total > 0 else 0.0
    return {
        "api_success_count": _metrics["api_success_count"],
        "api_fail_count": _metrics["api_fail_count"],
        "cache_hit_rate": round(hit_rate, 4),
    }


def _evict_oldest() -> None:
    """Remove the oldest cache entry (by timestamp)."""
    if not market_cache:
        return
    oldest_key = min(market_cache, key=lambda k: market_cache[k]["timestamp"])
    del market_cache[oldest_key]


def _get_cached(market_id: str) -> dict | None:
    """Return cached context if present and not expired, else None."""
    entry = market_cache.get(market_id)
    if entry is None:
        return None
    if time.time() - entry["timestamp"] > _CACHE_TTL_SECONDS:
        del market_cache[market_id]
        return None
    return entry["data"]


def _store_cache(market_id: str, data: dict) -> None:
    """Store a valid API result in cache, evicting oldest if at capacity."""
    if len(market_cache) >= _CACHE_MAX_ENTRIES:
        _evict_oldest()
    market_cache[market_id] = {"data": data, "timestamp": time.time()}


async def _fetch_with_retry(market_id: str) -> dict:
    """Attempt fetch_market_details up to 3 times with backoff.

    Raises the last exception if all attempts fail.
    """
    last_exc: Exception = Exception("unreachable")
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            data = await asyncio.wait_for(
                fetch_market_details(market_id),
                timeout=5.0,
            )
            return data
        except Exception as exc:
            last_exc = exc
            log.warning(
                "market_context_fetch_attempt_failed",
                market_id=market_id,
                attempt=attempt,
                error=str(exc),
            )
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(delay)
    raise last_exc


async def get_market_context(market_id: str) -> dict:
    """Fetch market context with TTL cache, retry, and fallback.

    Returns:
        {"name": str, "category": str, "resolution": str}
    Never returns None. Fallback is NOT cached — API recovery possible.
    """
    _metrics["cache_request_count"] += 1

    cached = _get_cached(market_id)
    if cached is not None:
        _metrics["cache_hit_count"] += 1
        return cached

    try:
        market_data = await _fetch_with_retry(market_id)
        q = market_data.get("question", "")
        name = q if isinstance(q, str) and q else f"Market #{market_id}"
        context = {
            "name": name,
            "category": market_data.get("category", "Unknown"),
            "resolution": market_data.get(
                "end_date_iso", market_data.get("end_date", "N/A")
            ),
        }
        _store_cache(market_id, context)
        _metrics["api_success_count"] += 1
        log.info("market_context_fetched", market_id=market_id, name=name)
        return context
    except Exception as e:
        _metrics["api_fail_count"] += 1
        log.warning("market_context_all_retries_failed", market_id=market_id, error=str(e))
        return {
            "name": f"Market #{market_id}",
            "category": "Unknown",
            "resolution": "N/A",
        }
