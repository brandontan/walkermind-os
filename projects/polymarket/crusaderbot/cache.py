"""Async Redis wrapper for CrusaderBot. JSON serialize internally."""
from __future__ import annotations

import json
from typing import Any, Optional

import redis.asyncio as aioredis
import structlog

from .config import settings

log = structlog.get_logger(__name__)


class Cache:
    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        log.info("cache.connected")

    async def disconnect(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None
        log.info("cache.disconnected")

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(await self._client.ping())
        except Exception as exc:
            log.warning("cache.ping_failed", error=str(exc))
            return False

    async def get(self, key: str) -> Any | None:
        if self._client is None:
            raise RuntimeError("cache not connected")
        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if self._client is None:
            raise RuntimeError("cache not connected")
        payload = json.dumps(value, separators=(",", ":"), default=str)
        if ttl is None:
            await self._client.set(key, payload)
        else:
            await self._client.set(key, payload, ex=ttl)

    async def delete(self, key: str) -> int:
        if self._client is None:
            raise RuntimeError("cache not connected")
        return await self._client.delete(key)


cache = Cache()
