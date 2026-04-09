"""Falcon external alpha ingestion utilities.

This module provides a bounded, fault-tolerant client for the Falcon
parameterized retrieval API and converts heterogeneous external payloads
into deterministic internal signal context.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import aiohttp
import structlog

log = structlog.get_logger(__name__)

_market_title_cache: dict[str, str] = {}

_FALCON_BASE_URL = "https://narrative.agent.heisenberg.so"
_FALCON_ENDPOINT = "/api/v2/semantic/retrieve/parameterized"
_FALCON_AGENT_MARKETS = 574
_FALCON_AGENT_TRADES = 556
_FALCON_AGENT_CANDLES = 568
_FALCON_AGENT_ORDERBOOK = 572


@dataclass(frozen=True)
class FalconPagination:
    """Falcon pagination contract."""

    limit: int = 50
    offset: int = 0


TransportCallable = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class FalconAPIClient:
    """Bounded async Falcon client with retry, timeout, and request shaping."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = _FALCON_BASE_URL,
        endpoint: str = _FALCON_ENDPOINT,
        timeout_seconds: float = 8.0,
        max_retries: int = 3,
        min_request_interval_seconds: float = 0.15,
        transport: TransportCallable | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("FALCON_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._endpoint = endpoint
        self._timeout_seconds = max(timeout_seconds, 1.0)
        self._max_retries = max(max_retries, 1)
        self._min_request_interval_seconds = max(min_request_interval_seconds, 0.0)
        self._transport = transport
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def request(
        self,
        *,
        agent_id: int,
        params: dict[str, Any] | None = None,
        pagination: FalconPagination | None = None,
    ) -> dict[str, Any]:
        """Execute one Falcon request with bounded retries."""
        payload = self._build_payload(agent_id=agent_id, params=params or {}, pagination=pagination)
        if self._transport is not None:
            return await self._transport(payload)

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        await self._enforce_rate_limit()
        for attempt in range(1, self._max_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"{self._base_url}{self._endpoint}",
                        json=payload,
                        headers=headers,
                    ) as response:
                        body = await response.json(content_type=None)
                        if response.status >= 400:
                            raise RuntimeError(f"falcon_http_{response.status}: {body}")
                        if not isinstance(body, dict):
                            raise RuntimeError("falcon_response_not_dict")
                        return body
            except Exception as exc:
                log.warning(
                    "falcon_request_failed",
                    agent_id=agent_id,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(round(0.25 * (2 ** (attempt - 1)), 3))

        raise RuntimeError("falcon_retry_exhausted")

    async def _enforce_rate_limit(self) -> None:
        """Bound request rate to avoid burst overload."""
        async with self._rate_limit_lock:
            now = time.monotonic()
            wait_s = self._min_request_interval_seconds - (now - self._last_request_at)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            self._last_request_at = time.monotonic()

    @staticmethod
    def _build_payload(
        *,
        agent_id: int,
        params: dict[str, Any],
        pagination: FalconPagination | None,
    ) -> dict[str, Any]:
        safe_pagination = pagination or FalconPagination()
        bounded_limit = max(1, min(int(safe_pagination.limit), 200))
        bounded_offset = max(0, int(safe_pagination.offset))
        safe_params = {key: str(value) for key, value in params.items() if value is not None}
        return {
            "agent_id": int(agent_id),
            "params": safe_params,
            "pagination": {
                "limit": bounded_limit,
                "offset": bounded_offset,
            },
            "formatter_config": {"format_type": "raw"},
        }


async def fetch_markets(
    client: FalconAPIClient,
    *,
    params: dict[str, Any] | None = None,
    pagination: FalconPagination | None = None,
) -> list[dict[str, Any]]:
    """Fetch Polymarket market dataset from Falcon."""
    response = await client.request(agent_id=_FALCON_AGENT_MARKETS, params=params, pagination=pagination)
    return _extract_rows(response)


async def fetch_trades(
    client: FalconAPIClient,
    *,
    params: dict[str, Any] | None = None,
    pagination: FalconPagination | None = None,
) -> list[dict[str, Any]]:
    """Fetch Polymarket trade-flow dataset from Falcon."""
    response = await client.request(agent_id=_FALCON_AGENT_TRADES, params=params, pagination=pagination)
    return _extract_rows(response)


async def fetch_candles(
    client: FalconAPIClient,
    *,
    params: dict[str, Any] | None = None,
    pagination: FalconPagination | None = None,
) -> list[dict[str, Any]]:
    """Fetch Polymarket candle dataset from Falcon."""
    response = await client.request(agent_id=_FALCON_AGENT_CANDLES, params=params, pagination=pagination)
    return _extract_rows(response)


async def fetch_orderbook(
    client: FalconAPIClient,
    *,
    params: dict[str, Any] | None = None,
    pagination: FalconPagination | None = None,
) -> list[dict[str, Any]]:
    """Fetch Polymarket orderbook dataset from Falcon."""
    response = await client.request(agent_id=_FALCON_AGENT_ORDERBOOK, params=params, pagination=pagination)
    return _extract_rows(response)


def normalize_external_signal(
    *,
    market: dict[str, Any],
    trades: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    orderbook: list[dict[str, Any]],
) -> dict[str, float | str]:
    """Convert Falcon raw rows into deterministic internal alpha payload."""
    market_id = str(market.get("market_id") or market.get("id") or "")
    market_title = _resolve_market_title(market)
    if market_id and market_title:
        _cache_market_title(market_id, market_title)

    price = _to_float(market.get("price"), default=0.0)
    volume = _to_float(market.get("volume"), default=0.0)
    momentum, volatility = _compute_price_context(candles)
    liquidity, _spread = _compute_liquidity_context(orderbook)
    smart_money_score = _compute_smart_money_score(trades)

    return {
        "market_id": market_id,
        "market_title": market_title,
        "price": round(price, 6),
        "volume": round(volume, 2),
        "momentum": round(momentum, 6),
        "liquidity": round(liquidity, 2),
        "smart_money_indicator": round(smart_money_score, 6),
        "volatility_snapshot": round(volatility, 6),
    }


def build_signal_normalization_pipeline(
    *,
    markets: list[dict[str, Any]],
    trades_by_market: dict[str, list[dict[str, Any]]],
    candles_by_market: dict[str, list[dict[str, Any]]],
    orderbook_by_market: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, float | str]]:
    """Normalize external datasets by market id for data-layer consumption."""
    normalized: dict[str, dict[str, float | str]] = {}
    for market in markets:
        market_id = str(market.get("market_id") or market.get("id") or "")
        if not market_id:
            continue
        normalized[market_id] = normalize_external_signal(
            market=market,
            trades=trades_by_market.get(market_id, []),
            candles=candles_by_market.get(market_id, []),
            orderbook=orderbook_by_market.get(market_id, []),
        )
    return normalized


async def fetch_external_alpha_with_fallback(
    client: FalconAPIClient,
    *,
    market_id: str,
    token_id: str,
) -> dict[str, float | str]:
    """Fetch and normalize Falcon alpha safely.

    Returns deterministic fallback payload when Falcon is unavailable.
    """
    cached_title = get_cached_market_title(market_id)
    try:
        markets = await fetch_markets(client, params={"market_id": market_id})
        if markets:
            resolved_title = _resolve_market_title(markets[0])
            if resolved_title:
                _cache_market_title(market_id, resolved_title)
                cached_title = resolved_title
        trades = await fetch_trades(client, params={"market_id": market_id})
        candles = await fetch_candles(client, params={"token_id": token_id})
        orderbook = await fetch_orderbook(client, params={"token_id": token_id})
        market = markets[0] if markets else {"market_id": market_id}
        return normalize_external_signal(
            market=market,
            trades=trades,
            candles=candles,
            orderbook=orderbook,
        )
    except Exception as exc:
        log.warning("falcon_external_alpha_fallback", market_id=market_id, error=str(exc))
        return {
            "market_id": market_id,
            "market_title": cached_title or f"Market {market_id}",
            "price": 0.0,
            "volume": 0.0,
            "momentum": 0.0,
            "liquidity": 0.0,
            "smart_money_indicator": 0.0,
            "volatility_snapshot": 0.0,
        }

def get_cached_market_title(market_id: str) -> str:
    """Return cached market title for market_id, if available."""
    return _market_title_cache.get(str(market_id), "")


def _cache_market_title(market_id: str, market_title: str) -> None:
    safe_market_id = str(market_id).strip()
    safe_title = str(market_title).strip()
    if safe_market_id and safe_title:
        _market_title_cache[safe_market_id] = safe_title


def _resolve_market_title(market: dict[str, Any]) -> str:
    for key in ("market_title", "title", "question", "name"):
        value = market.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(response.get("data"), list):
        return [row for row in response["data"] if isinstance(row, dict)]
    if isinstance(response.get("result"), list):
        return [row for row in response["result"] if isinstance(row, dict)]
    return []


def _to_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _compute_smart_money_score(trades: list[dict[str, Any]]) -> float:
    if not trades:
        return 0.0

    trade_sizes = [_to_float(trade.get("size") or trade.get("amount"), default=0.0) for trade in trades]
    average_size = sum(trade_sizes) / max(len(trade_sizes), 1)
    large_trade_count = sum(1 for size in trade_sizes if size >= max(average_size * 2.0, 1_000.0))

    wallets = [str(trade.get("wallet") or trade.get("wallet_address") or "") for trade in trades]
    wallet_counts = Counter(wallet for wallet in wallets if wallet)
    repeated_wallet_count = sum(1 for count in wallet_counts.values() if count >= 3)

    large_trade_ratio = large_trade_count / max(len(trades), 1)
    repeated_wallet_ratio = repeated_wallet_count / max(len(wallet_counts), 1)
    score = (0.7 * large_trade_ratio) + (0.3 * repeated_wallet_ratio)
    return max(0.0, min(1.0, score))


def _compute_price_context(candles: list[dict[str, Any]]) -> tuple[float, float]:
    if len(candles) < 2:
        return 0.0, 0.0

    closes = [_to_float(candle.get("close"), default=0.0) for candle in candles if candle.get("close") is not None]
    if len(closes) < 2:
        return 0.0, 0.0

    first = closes[0]
    last = closes[-1]
    momentum = 0.0 if first == 0.0 else (last - first) / abs(first)

    returns: list[float] = []
    for prev, current in zip(closes[:-1], closes[1:]):
        if prev <= 0:
            continue
        returns.append((current - prev) / prev)

    if not returns:
        return momentum, 0.0

    mean_ret = sum(returns) / len(returns)
    variance = sum((ret - mean_ret) ** 2 for ret in returns) / len(returns)
    volatility = math.sqrt(max(variance, 0.0))
    return momentum, volatility


def _compute_liquidity_context(orderbook: list[dict[str, Any]]) -> tuple[float, float]:
    bids = [_to_float(item.get("bid") or item.get("price"), default=0.0) for item in orderbook if item.get("side") == "bid"]
    asks = [_to_float(item.get("ask") or item.get("price"), default=0.0) for item in orderbook if item.get("side") == "ask"]

    best_bid = max(bids) if bids else 0.0
    best_ask = min(asks) if asks else 0.0
    spread = max(best_ask - best_bid, 0.0) if best_bid and best_ask else 0.0

    total_depth = sum(_to_float(item.get("depth") or item.get("size"), default=0.0) for item in orderbook)
    return total_depth, spread
