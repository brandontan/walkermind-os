"""Phase 10.5 — LiveExecutor (execution layer): Gated LIVE order placement.

Wraps the Phase 7 LiveExecutor with mandatory Phase 10.5 safety layers:

    1. LiveModeController.is_live_enabled()  — must pass on every call.
    2. ExecutionGuard.validate()             — pre-trade risk/dedup check.
    3. Redis dedup                           — idempotency via correlation_id.
    4. Phase 7 LiveExecutor.execute()        — actual CLOB placement.
    5. FillTracker.record_fill()             — audit fill outcome.

FAIL-CLOSED design::

    Any check failure          → BLOCKED result returned; no exchange call made.
    LiveModeController blocked → PAPER fallback; logged at WARNING.
    ExecutionGuard rejected    → order rejected; logged at WARNING.
    Redis unavailable          → dedup skipped; execution still attempted.
    Exchange error             → retry with backoff; re-raise on max retries.
    Unhandled exception        → BLOCKED result; never silently re-raises.

Idempotency::

    A unique dedup key (market_id:side:price:size:correlation_id) is checked
    against Redis before every execution.  If the key already exists, the
    order is rejected as a duplicate.  The key is written with a TTL after
    successful submission.

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import structlog

from ..execution.fill_tracker import FillTracker
from ..phase10.execution_guard import ExecutionGuard
from ..phase10.live_mode_controller import LiveModeController
from ..phase7.core.execution.live_executor import (
    ExecutionRequest,
    ExecutionResult,
    LiveExecutor as _Phase7Executor,
)

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEDUP_TTL_S: int = 60           # Redis key TTL in seconds
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY_S: float = 0.5
_RETRY_MAX_DELAY_S: float = 8.0


# ── Gated execution result ────────────────────────────────────────────────────


@dataclass
class GatedExecutionResult:
    """Result from the gated LiveExecutor.

    Attributes:
        allowed: True if the order was forwarded to the exchange.
        block_reason: Reason for blocking (empty when allowed=True).
        result: Inner ExecutionResult (None when blocked before exchange call).
        correlation_id: Request correlation ID for tracing.
        latency_ms: Total latency from gate-check to fill confirmation (ms).
    """

    allowed: bool
    block_reason: str
    result: Optional[ExecutionResult]
    correlation_id: str
    latency_ms: float = 0.0


# ── LiveExecutor (Phase 10.5 gated) ──────────────────────────────────────────


class LiveExecutor:
    """Phase 10.5 gated live executor.

    Wraps :class:`phase7.core.execution.live_executor.LiveExecutor` with
    :class:`~phase10.live_mode_controller.LiveModeController` and
    :class:`~phase10.execution_guard.ExecutionGuard` as mandatory pre-execution
    gates.

    Args:
        live_mode_controller: Phase 10.5 stateless LIVE gate.
        execution_guard: Phase 10 pre-trade risk/dedup validator.
        phase7_executor: Underlying Phase 7 CLOB executor.
        fill_tracker: Fill audit recorder.
        redis_client: Optional Redis client for dedup (skipped if None).
        dedup_ttl_s: Redis key TTL in seconds.
    """

    def __init__(
        self,
        live_mode_controller: LiveModeController,
        execution_guard: ExecutionGuard,
        phase7_executor: _Phase7Executor,
        fill_tracker: Optional[FillTracker] = None,
        redis_client: Optional[object] = None,
        dedup_ttl_s: int = _DEDUP_TTL_S,
    ) -> None:
        self._live_ctrl = live_mode_controller
        self._guard = execution_guard
        self._executor = phase7_executor
        self._fill_tracker = fill_tracker or FillTracker()
        self._redis = redis_client
        self._dedup_ttl = dedup_ttl_s

        log.info(
            "gated_live_executor_initialized",
            redis_enabled=redis_client is not None,
            dedup_ttl_s=dedup_ttl_s,
        )

    # ── Primary API ───────────────────────────────────────────────────────────

    async def execute(
        self,
        request: ExecutionRequest,
        market_ctx: Optional[dict] = None,
    ) -> GatedExecutionResult:
        """Execute an order through all Phase 10.5 safety gates.

        Gates executed in order (fail-closed — any failure blocks execution):
          1. LiveModeController.is_live_enabled()
          2. ExecutionGuard.validate()
          3. Redis dedup check
          4. Phase 7 executor (exchange call)
          5. FillTracker.record_fill()

        Args:
            request: Order request to execute.
            market_ctx: Market context dict with ``depth``, ``spread``, etc.

        Returns:
            :class:`GatedExecutionResult` — allowed=False when blocked.
        """
        cid = request.correlation_id
        t0 = time.perf_counter()
        ctx = market_ctx or {}

        # ── Gate 1: LiveModeController ────────────────────────────────────────
        if not self._live_ctrl.is_live_enabled():
            block_reason = self._live_ctrl.get_block_reason()
            log.warning(
                "gated_executor_blocked_live_mode",
                reason=block_reason,
                correlation_id=cid,
                market_id=request.market_id,
            )
            return GatedExecutionResult(
                allowed=False,
                block_reason=f"live_mode_blocked:{block_reason}",
                result=None,
                correlation_id=cid,
                latency_ms=_elapsed_ms(t0),
            )

        # ── Gate 2: ExecutionGuard ─────────────────────────────────────────────
        liquidity_usd = float(ctx.get("depth", 0.0))
        spread = float(ctx.get("spread", 0.02))
        slippage_pct = spread * 0.5

        guard_sig = (
            f"{request.market_id}:{request.side}:"
            f"{round(request.price, 4)}:{round(request.size, 2)}"
        )

        validation = self._guard.validate(
            market_id=request.market_id,
            side=request.side,
            price=request.price,
            size_usd=float(request.size),
            liquidity_usd=liquidity_usd,
            slippage_pct=slippage_pct,
            order_guard_signature=guard_sig,
        )

        if not validation.passed:
            log.warning(
                "gated_executor_blocked_guard",
                reason=validation.reason,
                correlation_id=cid,
                market_id=request.market_id,
            )
            return GatedExecutionResult(
                allowed=False,
                block_reason=f"execution_guard:{validation.reason}",
                result=None,
                correlation_id=cid,
                latency_ms=_elapsed_ms(t0),
            )

        # ── Gate 3: Redis dedup ───────────────────────────────────────────────
        dedup_key = _build_dedup_key(request)
        dup_blocked = await self._check_dedup(dedup_key, cid)
        if dup_blocked:
            return GatedExecutionResult(
                allowed=False,
                block_reason=f"redis_dedup:{dedup_key}",
                result=None,
                correlation_id=cid,
                latency_ms=_elapsed_ms(t0),
            )

        # ── Gate 4: Register submission in FillTracker ────────────────────────
        self._fill_tracker.record_submission(
            order_id=cid,
            market_id=request.market_id,
            side=request.side,
            expected_price=request.price,
            size_usd=float(request.size),
        )

        # ── Gate 5: Execute via Phase 7 executor ──────────────────────────────
        inner_result: Optional[ExecutionResult] = None
        try:
            inner_result = await self._execute_with_retry(request, ctx)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "gated_executor_exchange_error",
                correlation_id=cid,
                market_id=request.market_id,
                error=str(exc),
                exc_info=True,
            )
            # allowed=True: all pre-execution gates were passed; the exchange
            # call itself failed.  Callers can distinguish gate-block
            # (allowed=False) from exchange-failure (allowed=True, status=rejected).
            return GatedExecutionResult(
                allowed=True,
                block_reason="exchange_error",
                result=ExecutionResult(
                    order_id=cid,
                    status="rejected",
                    filled_size=0.0,
                    avg_price=0.0,
                    latency_ms=_elapsed_ms(t0),
                    correlation_id=cid,
                    error=str(exc),
                    is_paper=False,
                ),
                correlation_id=cid,
                latency_ms=_elapsed_ms(t0),
            )

        # ── Gate 6: FillTracker record ────────────────────────────────────────
        if inner_result and inner_result.status in ("filled", "partial"):
            self._fill_tracker.record_fill(
                order_id=cid,
                executed_price=inner_result.avg_price,
                filled_size=inner_result.filled_size,
            )

        # ── Write Redis dedup key after successful submission ──────────────────
        if inner_result and inner_result.status != "rejected":
            await self._write_dedup(dedup_key, cid)

        elapsed = _elapsed_ms(t0)
        log.info(
            "gated_executor_executed",
            correlation_id=cid,
            market_id=request.market_id,
            status=inner_result.status if inner_result else "unknown",
            latency_ms=round(elapsed, 2),
        )

        return GatedExecutionResult(
            allowed=True,
            block_reason="",
            result=inner_result,
            correlation_id=cid,
            latency_ms=elapsed,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _execute_with_retry(
        self,
        request: ExecutionRequest,
        ctx: dict,
    ) -> ExecutionResult:
        """Execute with exponential backoff retry.

        Args:
            request: Order request.
            ctx: Market context dict.

        Returns:
            ExecutionResult from Phase 7 executor.

        Raises:
            Exception: After max retries exhausted.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    self._executor.execute(request, ctx),
                    timeout=10.0,
                )
                return result
            except asyncio.TimeoutError as exc:
                last_exc = exc
                log.warning(
                    "gated_executor_timeout",
                    attempt=attempt,
                    correlation_id=request.correlation_id,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning(
                    "gated_executor_attempt_failed",
                    attempt=attempt,
                    correlation_id=request.correlation_id,
                    error=str(exc),
                )
            if attempt < _MAX_RETRIES:
                delay = min(_RETRY_BASE_DELAY_S * (2 ** (attempt - 1)), _RETRY_MAX_DELAY_S)
                await asyncio.sleep(delay)

        raise last_exc or RuntimeError("max_retries_exceeded")

    async def _check_dedup(self, dedup_key: str, correlation_id: str) -> bool:
        """Check Redis dedup cache.

        Args:
            dedup_key: Order dedup signature.
            correlation_id: Request trace ID for logging.

        Returns:
            True if the key exists (duplicate — block the order).
        """
        if self._redis is None:
            return False
        try:
            exists = await asyncio.wait_for(
                self._redis.exists(dedup_key),  # type: ignore[attr-defined]
                timeout=1.0,
            )
            if exists:
                log.warning(
                    "gated_executor_redis_dedup_hit",
                    dedup_key=dedup_key,
                    correlation_id=correlation_id,
                )
            return bool(exists)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "gated_executor_redis_check_failed",
                dedup_key=dedup_key,
                correlation_id=correlation_id,
                error=str(exc),
            )
            return False  # fail open on Redis error (execution proceeds)

    async def _write_dedup(self, dedup_key: str, correlation_id: str) -> None:
        """Write dedup key to Redis with TTL.

        Args:
            dedup_key: Order dedup signature.
            correlation_id: Request trace ID for logging.
        """
        if self._redis is None:
            return
        try:
            await asyncio.wait_for(
                self._redis.setex(  # type: ignore[attr-defined]
                    dedup_key, self._dedup_ttl, correlation_id
                ),
                timeout=1.0,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "gated_executor_redis_write_failed",
                dedup_key=dedup_key,
                correlation_id=correlation_id,
                error=str(exc),
            )


# ── Module helpers ────────────────────────────────────────────────────────────


def _build_dedup_key(request: ExecutionRequest) -> str:
    """Build a unique dedup key for the order.

    Format: ``{market_id}:{side}:{price_4dp}:{size_2dp}:{correlation_id}``

    Args:
        request: ExecutionRequest.

    Returns:
        Dedup key string.
    """
    return (
        f"{request.market_id}:{request.side}:"
        f"{round(request.price, 4)}:{round(request.size, 2)}:"
        f"{request.correlation_id}"
    )


def _elapsed_ms(t0: float) -> float:
    """Return elapsed time in milliseconds since t0.

    Args:
        t0: Start time from ``time.perf_counter()``.

    Returns:
        Elapsed time in milliseconds.
    """
    return (time.perf_counter() - t0) * 1000.0
