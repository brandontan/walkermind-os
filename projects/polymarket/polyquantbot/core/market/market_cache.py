"""core.market.market_cache — Market metadata cache for PolyQuantBot.

Fetches market metadata (question, outcomes) from the Polymarket Gamma API
and provides fast in-memory lookups for message formatting.

Features:
  - market_id → {question, outcomes} mapping
  - Async refresh every 5 minutes (configurable)
  - 3 retries with 2 s timeout per attempt
  - Graceful fallback: stale cache used on API failure
  - Structured JSON logging

Usage::

    cache = MarketMetadataCache()
    await cache.start()                  # starts background refresh
    meta = cache.get("0xabc...")         # MarketMeta | None
    await cache.stop()
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import structlog

log = structlog.get_logger()

_GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
_REFRESH_INTERVAL_S: float = 300.0   # 5 minutes
_REQUEST_TIMEOUT_S: float = 2.0
_MAX_RETRIES: int = 3


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class MarketMeta:
    """Metadata for a single Polymarket market."""

    market_id: str
    question: str
    outcomes: List[str] = field(default_factory=list)


# ── Cache ─────────────────────────────────────────────────────────────────────

class MarketMetadataCache:
    """Async market metadata cache with periodic background refresh.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        gamma_url: str = _GAMMA_API_URL,
        refresh_interval_s: float = _REFRESH_INTERVAL_S,
        request_timeout_s: float = _REQUEST_TIMEOUT_S,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._gamma_url = gamma_url.rstrip("/")
        self._refresh_interval_s = refresh_interval_s
        self._request_timeout_s = request_timeout_s
        self._max_retries = max_retries

        self._cache: Dict[str, MarketMeta] = {}
        self._last_refresh: float = 0.0
        self._refresh_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, market_id: str) -> Optional[MarketMeta]:
        """Return cached metadata for *market_id*, or ``None`` if not found."""
        return self._cache.get(market_id)

    def get_question(self, market_id: str, fallback: str = "") -> str:
        """Return the human-readable question for *market_id*.

        Falls back to *fallback* (default: empty string) when not found.
        """
        meta = self._cache.get(market_id)
        return meta.question if meta else fallback

    def get_outcomes(self, market_id: str) -> List[str]:
        """Return outcomes list for *market_id*, or ``[]`` when not found."""
        meta = self._cache.get(market_id)
        return meta.outcomes if meta else []

    def size(self) -> int:
        """Return the number of markets currently in cache."""
        return len(self._cache)

    async def refresh(self) -> bool:
        """Fetch markets from the Gamma API and update the cache.

        Returns ``True`` if at least one market was loaded, ``False`` on total
        failure (stale cache is preserved).
        """
        markets = await self._fetch_markets()
        if not markets:
            log.warning(
                "market_cache_refresh_failed",
                cached_count=len(self._cache),
                message="falling back to stale cache",
            )
            return False

        new_cache: Dict[str, MarketMeta] = {}
        for raw in markets:
            meta = _parse_market_meta(raw)
            if meta is not None:
                new_cache[meta.market_id] = meta

        self._cache = new_cache
        self._last_refresh = time.time()
        log.info(
            "market_cache_refreshed",
            market_count=len(new_cache),
        )
        return True

    async def start(self) -> None:
        """Start the background refresh loop.

        Performs an initial fetch immediately, then schedules periodic refreshes.
        """
        await self.refresh()
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        log.info("market_cache_started", refresh_interval_s=self._refresh_interval_s)

    async def stop(self) -> None:
        """Cancel the background refresh loop."""
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        log.info("market_cache_stopped")

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Background task: refresh every *_refresh_interval_s* seconds."""
        while True:
            await asyncio.sleep(self._refresh_interval_s)
            try:
                await self.refresh()
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "market_cache_refresh_error",
                    error=str(exc),
                    exc_info=True,
                )

    async def _fetch_markets(self) -> list:
        """Fetch raw market list from Gamma API with retry."""
        try:
            import aiohttp  # optional dependency
        except ImportError:
            log.error(
                "market_cache_fetch_failed",
                error="aiohttp not installed — run: pip install aiohttp",
            )
            return []

        url = f"{self._gamma_url}/markets"
        params = {"active": "true", "closed": "false", "limit": 500}
        last_error = "unknown"

        for attempt in range(self._max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=self._request_timeout_s),
                    ) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"HTTP {resp.status}")
                        data = await resp.json()

                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data.get("markets", [])
                return []

            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt < self._max_retries - 1:
                    delay = 2 ** attempt
                    log.warning(
                        "market_cache_fetch_retry",
                        attempt=attempt + 1,
                        error=last_error,
                        retry_in_s=delay,
                    )
                    await asyncio.sleep(delay)

        log.error(
            "market_cache_fetch_failed",
            error=last_error,
            attempts=self._max_retries,
        )
        return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_market_meta(raw: dict) -> Optional[MarketMeta]:
    """Extract market_id, question, and outcomes from a raw Gamma API dict.

    Returns ``None`` if required fields are missing or malformed.
    """
    try:
        market_id: Optional[str] = (
            raw.get("conditionId")
            or raw.get("id")
            or raw.get("market_id")
        )
        if not market_id:
            return None

        question: str = str(raw.get("question") or raw.get("title") or "")
        if not question:
            return None

        # outcomes may be a list or a JSON-encoded string
        raw_outcomes = raw.get("outcomes") or raw.get("outcomeNames") or []
        if isinstance(raw_outcomes, str):
            try:
                raw_outcomes = json.loads(raw_outcomes)
            except Exception:  # noqa: BLE001
                raw_outcomes = []

        outcomes: List[str] = [str(o) for o in raw_outcomes if o]

        return MarketMeta(
            market_id=str(market_id),
            question=question,
            outcomes=outcomes,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("market_meta_parse_error", error=str(exc))
        return None


# ── Module-level singleton ────────────────────────────────────────────────────

_default_cache: Optional[MarketMetadataCache] = None


def get_default_cache() -> MarketMetadataCache:
    """Return (and lazily create) the module-level singleton cache."""
    global _default_cache
    if _default_cache is None:
        _default_cache = MarketMetadataCache()
    return _default_cache
