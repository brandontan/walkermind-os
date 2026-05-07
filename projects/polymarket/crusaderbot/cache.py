"""Cache wrapper. Uses Redis if REDIS_URL is set, otherwise an in-memory TTL cache."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)

_redis = None
_mem_cache: dict[str, tuple[float, Any]] = {}
_mem_lock = asyncio.Lock()


async def init_cache() -> None:
    global _redis
    settings = get_settings()
    if not settings.REDIS_URL:
        logger.info("No REDIS_URL — using in-memory cache (single-process only).")
        return
    try:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
        await _redis.ping()
        logger.info("Redis cache connected.")
    except Exception as exc:
        logger.warning("Redis init failed (%s) — falling back to in-memory cache.", exc)
        _redis = None


async def close_cache() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception as exc:
            logger.warning("Redis aclose failed: %s", exc)
        _redis = None


async def get_cache(key: str) -> Any:
    if _redis is not None:
        try:
            v = await _redis.get(key)
            return json.loads(v) if v is not None else None
        except Exception as exc:
            logger.warning("Redis GET failed for %s: %s", key, exc)
            return None
    async with _mem_lock:
        item = _mem_cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            _mem_cache.pop(key, None)
            return None
        return value


async def set_cache(key: str, value: Any, ttl: int = 300) -> None:
    if _redis is not None:
        try:
            await _redis.set(key, json.dumps(value, default=str), ex=ttl)
            return
        except Exception as exc:
            logger.warning("Redis SET failed for %s: %s", key, exc)
            return
    async with _mem_lock:
        _mem_cache[key] = (time.time() + ttl, value)


async def delete_cache(key: str) -> None:
    if _redis is not None:
        try:
            await _redis.delete(key)
            return
        except Exception as exc:
            logger.warning("Redis DELETE failed for %s: %s", key, exc)
    async with _mem_lock:
        _mem_cache.pop(key, None)


async def ping_cache() -> bool:
    if _redis is not None:
        try:
            await _redis.ping()
            return True
        except Exception as exc:
            logger.warning("Redis PING failed: %s", exc)
            return False
    return True  # in-memory always "up"
