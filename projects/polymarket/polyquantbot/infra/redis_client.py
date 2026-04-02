"""Infra — RedisClient: Async Redis integration for real-time state persistence.

Provides a single async Redis client with typed helpers for storing and
retrieving system state, metrics snapshots, allocation weights, and active
positions.

Keys schema:
    polyquantbot:metrics:{strategy_id}   → JSON StrategyMetrics dict
    polyquantbot:allocation:weights      → JSON {strategy_name: weight}
    polyquantbot:positions               → JSON {market_id: position_dict}
    polyquantbot:system_state            → JSON {state, reason, ts}
    polyquantbot:live_metrics_snapshot   → JSON full metrics snapshot

Design:
    - Non-blocking: all operations are async with timeout.
    - Fail-safe: Redis failures are logged and swallowed — never crash trading.
    - Retry: up to 3 attempts with 0.5s/1s/2s backoff on transient errors.
    - Idempotent: all writes are SET (upsert), safe to call repeatedly.
    - Structured logging on every operation.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

import structlog

log = structlog.get_logger(__name__)

# ── Key prefix ────────────────────────────────────────────────────────────────

_PREFIX = "polyquantbot"
_KEY_METRICS = f"{_PREFIX}:metrics"           # :{strategy_id}
_KEY_WEIGHTS = f"{_PREFIX}:allocation:weights"
_KEY_POSITIONS = f"{_PREFIX}:positions"
_KEY_SYSTEM_STATE = f"{_PREFIX}:system_state"
_KEY_LIVE_SNAPSHOT = f"{_PREFIX}:live_metrics_snapshot"

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_TTL_S: int = 86400 * 7   # 7 days
_OP_TIMEOUT_S: float = 2.0
_MAX_RETRIES: int = 3
_RETRY_BASE_S: float = 0.5


# ── RedisClient ───────────────────────────────────────────────────────────────


class RedisClient:
    """Async Redis client for PolyQuantBot state persistence.

    Uses aioredis (redis-py async) under the hood.  Connection is lazy —
    established on first use.

    Args:
        url: Redis connection URL (default: env REDIS_URL or redis://localhost:6379).
        ttl_s: Default TTL in seconds for stored keys (default 7 days).
        op_timeout_s: Timeout per Redis operation in seconds.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        ttl_s: int = _DEFAULT_TTL_S,
        op_timeout_s: float = _OP_TIMEOUT_S,
    ) -> None:
        self._url = url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._ttl_s = ttl_s
        self._op_timeout_s = op_timeout_s
        self._redis: Optional[Any] = None  # redis.asyncio.Redis instance
        self._lock = asyncio.Lock()

        log.info(
            "redis_client_initialized",
            url=self._url,
            ttl_s=ttl_s,
            op_timeout_s=op_timeout_s,
        )

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish Redis connection.  Idempotent — safe to call multiple times."""
        async with self._lock:
            if self._redis is not None:
                return
            try:
                import redis.asyncio as aioredis  # type: ignore[import]
                self._redis = aioredis.from_url(
                    self._url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=int(self._op_timeout_s),
                )
                await asyncio.wait_for(self._redis.ping(), timeout=self._op_timeout_s)
                log.info("redis_client_connected", url=self._url)
            except Exception as exc:
                self._redis = None
                log.error(
                    "redis_client_connect_failed",
                    url=self._url,
                    error=str(exc),
                )

    async def close(self) -> None:
        """Close the Redis connection gracefully."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
                log.info("redis_client_closed")
            except Exception as exc:
                log.warning("redis_client_close_error", error=str(exc))
            finally:
                self._redis = None

    # ── Metrics ───────────────────────────────────────────────────────────────

    async def save_strategy_metrics(
        self, strategy_id: str, metrics_dict: Dict[str, Any]
    ) -> bool:
        """Persist per-strategy metrics snapshot to Redis.

        Args:
            strategy_id: Strategy name (key suffix).
            metrics_dict: Serialisable metrics dict from StrategyMetrics.to_dict().

        Returns:
            True on success, False on failure.
        """
        key = f"{_KEY_METRICS}:{strategy_id}"
        return await self._set_json(key, metrics_dict)

    async def load_strategy_metrics(
        self, strategy_id: str
    ) -> Optional[Dict[str, Any]]:
        """Load per-strategy metrics from Redis.

        Args:
            strategy_id: Strategy name.

        Returns:
            Metrics dict or None if not found / on error.
        """
        key = f"{_KEY_METRICS}:{strategy_id}"
        return await self._get_json(key)

    async def save_live_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        """Persist full multi-strategy metrics snapshot.

        Args:
            snapshot: Full snapshot dict from MultiStrategyMetrics.snapshot().

        Returns:
            True on success, False on failure.
        """
        return await self._set_json(_KEY_LIVE_SNAPSHOT, snapshot)

    async def load_live_snapshot(self) -> Optional[Dict[str, Any]]:
        """Load full live metrics snapshot from Redis.

        Returns:
            Snapshot dict or None if not found.
        """
        return await self._get_json(_KEY_LIVE_SNAPSHOT)

    # ── Allocation weights ────────────────────────────────────────────────────

    async def save_allocation_weights(
        self, weights: Dict[str, float]
    ) -> bool:
        """Persist allocation weights.

        Args:
            weights: Mapping of strategy_name → normalized weight ∈ [0, 1].

        Returns:
            True on success, False on failure.
        """
        return await self._set_json(_KEY_WEIGHTS, weights)

    async def load_allocation_weights(self) -> Optional[Dict[str, float]]:
        """Load allocation weights from Redis.

        Returns:
            Weights dict or None if not found.
        """
        return await self._get_json(_KEY_WEIGHTS)

    # ── Positions ─────────────────────────────────────────────────────────────

    async def save_positions(self, positions: Dict[str, Any]) -> bool:
        """Persist active positions snapshot.

        Args:
            positions: Mapping of market_id → position data dict.

        Returns:
            True on success, False on failure.
        """
        return await self._set_json(_KEY_POSITIONS, positions)

    async def load_positions(self) -> Optional[Dict[str, Any]]:
        """Load active positions from Redis.

        Returns:
            Positions dict or None if not found.
        """
        return await self._get_json(_KEY_POSITIONS)

    # ── System state ──────────────────────────────────────────────────────────

    async def save_system_state(
        self, state: str, reason: str, extra: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Persist system state.

        Args:
            state: SystemState value ("RUNNING" | "PAUSED" | "HALTED").
            reason: Reason for the current state.
            extra: Optional additional fields.

        Returns:
            True on success, False on failure.
        """
        import time
        payload: Dict[str, Any] = {
            "state": state,
            "reason": reason,
            "saved_at": time.time(),
        }
        if extra:
            payload.update(extra)
        return await self._set_json(_KEY_SYSTEM_STATE, payload)

    async def load_system_state(self) -> Optional[Dict[str, Any]]:
        """Load last-saved system state from Redis.

        Returns:
            State dict or None if not found.
        """
        return await self._get_json(_KEY_SYSTEM_STATE)

    # ── Generic helpers ───────────────────────────────────────────────────────

    async def _set_json(self, key: str, value: Any) -> bool:
        """SET key to JSON-encoded value with TTL.  Retries on transient error."""
        if self._redis is None:
            await self.connect()
        if self._redis is None:
            log.warning("redis_set_skipped_no_connection", key=key)
            return False

        serialised = json.dumps(value, default=str)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                await asyncio.wait_for(
                    self._redis.set(key, serialised, ex=self._ttl_s),
                    timeout=self._op_timeout_s,
                )
                log.debug("redis_set_ok", key=key, attempt=attempt)
                return True
            except asyncio.TimeoutError:
                log.warning("redis_set_timeout", key=key, attempt=attempt)
            except Exception as exc:
                log.warning("redis_set_error", key=key, attempt=attempt, error=str(exc))
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))

        log.error("redis_set_all_attempts_failed", key=key)
        return False

    async def _get_json(self, key: str) -> Optional[Any]:
        """GET key and JSON-decode.  Returns None on miss or error."""
        if self._redis is None:
            await self.connect()
        if self._redis is None:
            log.warning("redis_get_skipped_no_connection", key=key)
            return None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                raw = await asyncio.wait_for(
                    self._redis.get(key),
                    timeout=self._op_timeout_s,
                )
                if raw is None:
                    log.debug("redis_get_miss", key=key)
                    return None
                log.debug("redis_get_ok", key=key, attempt=attempt)
                return json.loads(raw)
            except asyncio.TimeoutError:
                log.warning("redis_get_timeout", key=key, attempt=attempt)
            except json.JSONDecodeError as exc:
                log.error("redis_get_json_decode_error", key=key, error=str(exc))
                return None
            except Exception as exc:
                log.warning("redis_get_error", key=key, attempt=attempt, error=str(exc))
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))

        log.error("redis_get_all_attempts_failed", key=key)
        return None

    async def ping(self) -> bool:
        """Check Redis connectivity.

        Returns:
            True if Redis responds to PING, False otherwise.
        """
        if self._redis is None:
            await self.connect()
        if self._redis is None:
            return False
        try:
            await asyncio.wait_for(self._redis.ping(), timeout=self._op_timeout_s)
            return True
        except Exception:
            return False

    def __repr__(self) -> str:
        connected = self._redis is not None
        return f"<RedisClient url={self._url!r} connected={connected}>"
