"""Wallet stats service — fetch and cache Polymarket wallet data.

Fetches from the Polymarket Gamma API:
    GET /profiles/{address}  -> single wallet stats
    GET /leaderboard         -> top wallets for discovery

In-memory cache with 5-minute TTL. Cache keys are lower-cased addresses.
On any API failure the stats are returned with available=False so callers
can still allow copy setup without blocking on data availability.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_CACHE_TTL = 300  # seconds
_TIMEOUT = aiohttp.ClientTimeout(total=10)

# {address_lower: (monotonic_timestamp, WalletStats)}
_cache: dict[str, tuple[float, "WalletStats"]] = {}


@dataclass(frozen=True)
class WalletStats:
    address: str
    pnl_30d: float | None
    win_rate: float | None
    avg_trade: float | None
    trades_count: int
    active_positions: int
    category: str
    available: bool


async def fetch_wallet_stats(address: str) -> WalletStats:
    """Return stats for a single wallet address.

    Checks in-memory cache first (TTL = 5 min). Falls back to
    available=False on any network or parse error.
    """
    addr_key = address.lower()
    now = time.monotonic()
    cached = _cache.get(addr_key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    stats = await _fetch_profile(address)
    _cache[addr_key] = (now, stats)
    return stats


async def fetch_top_wallets(category: str | None = None) -> list[WalletStats]:
    """Return up to 10 top wallets for the discovery leaderboard.

    category values: None | "crypto" | "sports" | "politics" | "world"
                     | "top_pnl" (default sort) | "top_wr" (sort by win rate)

    Returns empty list on failure — callers show an error state.
    """
    try:
        params: dict[str, str | int] = {"limit": 10, "order": "desc"}
        if category == "top_wr":
            params["sortBy"] = "winRate"
        else:
            params["sortBy"] = "pnl30d"
        if category and category not in ("top_pnl", "top_wr"):
            params["category"] = category

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            url = f"{_GAMMA_BASE}/leaderboard"
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("leaderboard API status=%d", resp.status)
                    return []
                data = await resp.json()
                entries = data if isinstance(data, list) else data.get("results", [])
                return [_parse(e.get("address", ""), e) for e in entries[:10]]
    except Exception:
        logger.exception("fetch_top_wallets failed category=%s", category)
        return []


async def _fetch_profile(address: str) -> WalletStats:
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            url = f"{_GAMMA_BASE}/profiles/{address}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("profile API status=%d addr=%s", resp.status, address)
                    return _unavailable(address)
                data = await resp.json()
                return _parse(address, data)
    except Exception:
        logger.exception("profile fetch failed addr=%s", address)
        return _unavailable(address)


def _unavailable(address: str) -> WalletStats:
    return WalletStats(
        address=address,
        pnl_30d=None,
        win_rate=None,
        avg_trade=None,
        trades_count=0,
        active_positions=0,
        category="Unknown",
        available=False,
    )


def _parse(address: str, data: dict) -> WalletStats:
    def _float(key1: str, key2: str = "") -> float | None:
        v = data.get(key1) or (data.get(key2) if key2 else None)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _int(key1: str, key2: str = "") -> int:
        v = data.get(key1) or (data.get(key2) if key2 else None)
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    return WalletStats(
        address=address,
        pnl_30d=_float("pnl30d", "pnl_30d"),
        win_rate=_float("winRate", "win_rate"),
        avg_trade=_float("avgTradeSize", "avg_trade_size"),
        trades_count=_int("tradesCount", "trades_count"),
        active_positions=_int("openPositions", "open_positions"),
        category=str(data.get("primaryCategory") or data.get("category") or "General"),
        available=True,
    )
