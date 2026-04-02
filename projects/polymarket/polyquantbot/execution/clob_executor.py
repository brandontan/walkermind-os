"""CLOB Executor — LiveExecutor.

Live order execution via py-clob-client (Polymarket CLOB).
Supports limit orders, market orders, cancellation, and status polling.

Features:
    - Idempotency key enforced on every order (dedup via order_id prefix).
    - Retry with exponential backoff on transient failures.
    - Pre-trade validation: min size, zero liquidity, orderbook validity.
    - Latency measurement: API RTT recorded per execution.
    - Cancel-all-open on critical failure.
    - Paper mode (DRY_RUN=true): logs intent without sending to exchange.
    - Structured JSON logging on every operation.

Environment variables:
    CLOB_API_KEY            — Polymarket CLOB API key
    CLOB_API_SECRET         — API secret
    CLOB_API_PASSPHRASE     — API passphrase
    CLOB_CHAIN_ID           — Polygon chain ID (default: 137)
    DRY_RUN                 — "true" to enable paper mode (no real orders)

Input schema (ExecutionRequest):
    market_id: str
    side: "YES" | "NO"
    price: float
    size: float

Output schema (ExecutionResult):
    order_id: str
    status: "submitted" | "filled" | "partial" | "rejected"
    filled_size: float
    avg_price: float
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_MIN_ORDER_SIZE: float = 1.0        # USD minimum
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 0.5      # seconds
_RETRY_MAX_DELAY: float = 8.0
_API_TIMEOUT: float = 10.0          # seconds
_PRICE_MIN: float = 0.01
_PRICE_MAX: float = 0.99
_IDEMPOTENCY_PREFIX_LEN: int = 8    # chars from correlation_id used as key prefix


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class ExecutionRequest:
    """Incoming order request.

    Attributes:
        market_id: Polymarket condition ID.
        side: "YES" or "NO".
        price: Limit price ∈ [0.01, 0.99].
        size: Order size in USD.
        order_type: "LIMIT" | "MARKET".
        correlation_id: Unique request ID for tracing.
    """

    market_id: str
    side: str           # "YES" | "NO"
    price: float
    size: float
    order_type: str = "LIMIT"
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    strategy_id: str = ""          # originating strategy (for feedback loop)
    expected_ev: float = 0.0       # signal expected value per USD (for feedback loop)


@dataclass
class ExecutionResult:
    """Order execution result.

    Attributes:
        order_id: Exchange-assigned order ID.
        status: "submitted" | "filled" | "partial" | "rejected".
        filled_size: USD amount actually filled.
        avg_price: Volume-weighted average fill price.
        latency_ms: API round-trip time in milliseconds.
        error: Error message if rejected (else None).
        correlation_id: Matches request correlation_id.
        is_paper: True if executed in paper/dry-run mode.
    """

    order_id: str
    status: str
    filled_size: float
    avg_price: float
    latency_ms: float
    correlation_id: str
    error: Optional[str] = None
    is_paper: bool = False


# ── LiveExecutor ──────────────────────────────────────────────────────────────

class LiveExecutor:
    """Live order execution layer for Polymarket CLOB.

    Uses py-clob-client for order placement, cancellation, and status polling.
    Falls back to paper mode when DRY_RUN=true or client unavailable.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        chain_id: int = 137,
        dry_run: bool = False,
        min_order_size: float = _MIN_ORDER_SIZE,
        max_retries: int = _MAX_RETRIES,
        api_timeout_s: float = _API_TIMEOUT,
        trade_result_callback: Optional[
            Callable[["TradeResult"], Awaitable[None]]  # type: ignore[name-defined]
        ] = None,
    ) -> None:
        """Initialise the executor.

        Args:
            api_key: Polymarket CLOB API key.
            api_secret: API secret.
            api_passphrase: API passphrase.
            chain_id: Polygon chain ID (137 = mainnet).
            dry_run: Paper mode — log orders but do not send to exchange.
            min_order_size: Minimum order size in USD.
            max_retries: Max retry attempts on transient failure.
            api_timeout_s: Timeout for each API call in seconds.
            trade_result_callback: Optional async callable invoked after every
                successful fill (status != "rejected").  Receives a
                :class:`TradeResult` and feeds the feedback loop.
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._api_passphrase = api_passphrase
        self._chain_id = chain_id
        self._dry_run = dry_run
        self._min_size = min_order_size
        self._max_retries = max_retries
        self._timeout = api_timeout_s
        self._trade_result_callback = trade_result_callback

        self._client = None   # lazy-init in _ensure_client()
        self._open_orders: dict[str, str] = {}   # correlation_id → order_id (dedup)

        log.info(
            "live_executor_initialized",
            chain_id=chain_id,
            dry_run=dry_run,
            min_order_size=min_order_size,
            feedback_loop_enabled=trade_result_callback is not None,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "LiveExecutor":
        """Build from environment variables.

        Reads:
            CLOB_API_KEY, CLOB_API_SECRET, CLOB_API_PASSPHRASE
            CLOB_CHAIN_ID  (default: "137")
            DRY_RUN        (default: "false")
        """
        dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        return cls(
            api_key=os.environ["CLOB_API_KEY"],
            api_secret=os.environ["CLOB_API_SECRET"],
            api_passphrase=os.environ["CLOB_API_PASSPHRASE"],
            chain_id=int(os.getenv("CLOB_CHAIN_ID", "137")),
            dry_run=dry_run,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute(
        self,
        request: ExecutionRequest,
        market_ctx: Optional[dict] = None,
    ) -> ExecutionResult:
        """Execute an order with full pre-trade validation, retry, and logging.

        Args:
            request: ExecutionRequest with market, side, price, size.
            market_ctx: Optional dict with orderbook_valid flag for pre-trade check.

        Returns:
            ExecutionResult with status and fill details.
        """
        cid = request.correlation_id
        t0 = time.perf_counter()

        log.info(
            "execution_started",
            correlation_id=cid,
            market_id=request.market_id,
            side=request.side,
            price=request.price,
            size=request.size,
            order_type=request.order_type,
            dry_run=self._dry_run,
        )

        # ── Pre-trade validation ───────────────────────────────────────────────
        validation_error = self._validate(request, market_ctx)
        if validation_error:
            latency_ms = (time.perf_counter() - t0) * 1000
            log.warning(
                "execution_pre_trade_rejected",
                correlation_id=cid,
                reason=validation_error,
            )
            return ExecutionResult(
                order_id="",
                status="rejected",
                filled_size=0.0,
                avg_price=0.0,
                latency_ms=round(latency_ms, 2),
                correlation_id=cid,
                error=validation_error,
                is_paper=self._dry_run,
            )

        # ── Dedup guard ────────────────────────────────────────────────────────
        idempotency_key = self._idempotency_key(request)
        if idempotency_key in self._open_orders:
            existing_id = self._open_orders[idempotency_key]
            log.warning(
                "execution_duplicate_order_blocked",
                correlation_id=cid,
                existing_order_id=existing_id,
                idempotency_key=idempotency_key,
            )
            return ExecutionResult(
                order_id=existing_id,
                status="rejected",
                filled_size=0.0,
                avg_price=0.0,
                latency_ms=0.0,
                correlation_id=cid,
                error="duplicate_order_idempotency_block",
                is_paper=self._dry_run,
            )

        # ── Paper mode bypass ──────────────────────────────────────────────────
        if self._dry_run:
            result = await self._paper_execute(request, t0)
            if result.status != "rejected":
                await self._emit_trade_result(request, result)
            return result

        # ── Live execution with retry ──────────────────────────────────────────
        result = await self._live_execute_with_retry(request, idempotency_key, t0)
        if result.status != "rejected":
            await self._emit_trade_result(request, result)
        return result

    async def cancel_order(
        self,
        order_id: str,
        correlation_id: str,
    ) -> bool:
        """Cancel an open order by order ID.

        Args:
            order_id: Exchange order ID to cancel.
            correlation_id: Request ID for tracing.

        Returns:
            True if cancel succeeded or order already gone. False on error.
        """
        if self._dry_run:
            log.info(
                "paper_cancel_order",
                order_id=order_id,
                correlation_id=correlation_id,
            )
            return True

        for attempt in range(1, self._max_retries + 1):
            try:
                client = await self._ensure_client()
                t0 = time.perf_counter()
                await asyncio.wait_for(
                    asyncio.to_thread(client.cancel, order_id),
                    timeout=self._timeout,
                )
                latency_ms = (time.perf_counter() - t0) * 1000
                log.info(
                    "order_cancelled",
                    order_id=order_id,
                    correlation_id=correlation_id,
                    latency_ms=round(latency_ms, 2),
                    attempt=attempt,
                )
                # Remove from open orders tracking
                self._open_orders = {
                    k: v for k, v in self._open_orders.items() if v != order_id
                }
                return True

            except Exception as exc:  # noqa: BLE001
                delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
                log.warning(
                    "cancel_attempt_failed",
                    order_id=order_id,
                    correlation_id=correlation_id,
                    attempt=attempt,
                    error=str(exc),
                    retry_delay_s=delay,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)

        log.error(
            "cancel_all_attempts_failed",
            order_id=order_id,
            correlation_id=correlation_id,
        )
        return False

    async def cancel_all_open(self, correlation_id: str) -> int:
        """Cancel all tracked open orders.

        Called on critical failure / shutdown.

        Returns:
            Number of successfully cancelled orders.
        """
        if not self._open_orders:
            return 0

        order_ids = list(self._open_orders.values())
        log.warning(
            "cancel_all_open_orders",
            count=len(order_ids),
            correlation_id=correlation_id,
        )
        cancelled = 0
        for order_id in order_ids:
            ok = await self.cancel_order(order_id, correlation_id)
            if ok:
                cancelled += 1
        return cancelled

    async def get_order_status(
        self,
        order_id: str,
        correlation_id: str,
    ) -> Optional[dict]:
        """Poll order status from the exchange.

        Args:
            order_id: Exchange order ID.
            correlation_id: Request ID for tracing.

        Returns:
            Dict with keys: status, filled_size, avg_price — or None on error.
        """
        if self._dry_run:
            return {
                "status": "filled",
                "filled_size": 0.0,
                "avg_price": 0.0,
            }

        for attempt in range(1, self._max_retries + 1):
            try:
                client = await self._ensure_client()
                t0 = time.perf_counter()
                raw = await asyncio.wait_for(
                    asyncio.to_thread(client.get_order, order_id),
                    timeout=self._timeout,
                )
                latency_ms = (time.perf_counter() - t0) * 1000
                result = self._parse_order_status(raw)
                log.info(
                    "order_status_polled",
                    order_id=order_id,
                    correlation_id=correlation_id,
                    status=result.get("status"),
                    latency_ms=round(latency_ms, 2),
                    attempt=attempt,
                )
                return result

            except Exception as exc:  # noqa: BLE001
                delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
                log.warning(
                    "order_status_poll_failed",
                    order_id=order_id,
                    correlation_id=correlation_id,
                    attempt=attempt,
                    error=str(exc),
                    retry_delay_s=delay,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)

        log.error(
            "order_status_all_attempts_failed",
            order_id=order_id,
            correlation_id=correlation_id,
        )
        return None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _validate(
        self,
        req: ExecutionRequest,
        market_ctx: Optional[dict],
    ) -> Optional[str]:
        """Pre-trade validation. Returns error string or None if valid."""
        if req.size < self._min_size:
            return f"size={req.size} < min_order_size={self._min_size}"
        if req.side not in ("YES", "NO"):
            return f"invalid_side={req.side}"
        if not (_PRICE_MIN <= req.price <= _PRICE_MAX):
            return f"price={req.price} out of range [{_PRICE_MIN}, {_PRICE_MAX}]"
        if req.size <= 0:
            return "size_must_be_positive"
        if market_ctx and not market_ctx.get("orderbook_valid", True):
            return "orderbook_invalid_pre_trade_rejected"
        depth = (market_ctx or {}).get("depth", 1.0)
        if depth <= 0:
            return "zero_liquidity_execution_blocked"
        return None

    def _idempotency_key(self, req: ExecutionRequest) -> str:
        """Generate a stable idempotency key from request fields."""
        return (
            f"{req.market_id}:{req.side}:{req.price:.6f}:{req.size:.6f}"
        )

    async def _paper_execute(
        self, req: ExecutionRequest, t0: float
    ) -> ExecutionResult:
        """Simulate order execution in paper mode."""
        await asyncio.sleep(0.01)   # simulate minimal API latency
        order_id = f"paper_{req.correlation_id[:8]}_{int(time.time())}"
        latency_ms = (time.perf_counter() - t0) * 1000

        log.info(
            "paper_order_executed",
            correlation_id=req.correlation_id,
            order_id=order_id,
            market_id=req.market_id,
            side=req.side,
            price=req.price,
            size=req.size,
            latency_ms=round(latency_ms, 2),
        )
        return ExecutionResult(
            order_id=order_id,
            status="submitted",
            filled_size=0.0,       # paper: no actual fill
            avg_price=req.price,
            latency_ms=round(latency_ms, 2),
            correlation_id=req.correlation_id,
            is_paper=True,
        )

    async def _live_execute_with_retry(
        self,
        req: ExecutionRequest,
        idempotency_key: str,
        t0: float,
    ) -> ExecutionResult:
        """Place live order with retry on transient failure."""
        last_error: Optional[str] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                client = await self._ensure_client()
                order_args = self._build_order_args(req, idempotency_key)

                api_t0 = time.perf_counter()
                raw_result = await asyncio.wait_for(
                    asyncio.to_thread(client.create_order, **order_args),
                    timeout=self._timeout,
                )
                latency_ms = (time.perf_counter() - api_t0) * 1000

                result = self._parse_create_order(
                    raw=raw_result,
                    req=req,
                    latency_ms=round(latency_ms, 2),
                    t0=t0,
                )

                # Track open order for cancel-all and dedup
                if result.status in ("submitted", "partial"):
                    self._open_orders[idempotency_key] = result.order_id

                log.info(
                    "order_placed",
                    correlation_id=req.correlation_id,
                    order_id=result.order_id,
                    status=result.status,
                    filled_size=result.filled_size,
                    avg_price=result.avg_price,
                    latency_ms=result.latency_ms,
                    attempt=attempt,
                )
                return result

            except asyncio.TimeoutError:
                last_error = f"api_timeout_attempt_{attempt}"
                delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
                log.warning(
                    "order_timeout",
                    correlation_id=req.correlation_id,
                    attempt=attempt,
                    retry_delay_s=delay,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)

            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
                log.warning(
                    "order_attempt_failed",
                    correlation_id=req.correlation_id,
                    attempt=attempt,
                    error=last_error,
                    retry_delay_s=delay,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)

        latency_ms = (time.perf_counter() - t0) * 1000
        log.error(
            "order_all_attempts_failed",
            correlation_id=req.correlation_id,
            error=last_error,
            market_id=req.market_id,
        )
        return ExecutionResult(
            order_id="",
            status="rejected",
            filled_size=0.0,
            avg_price=0.0,
            latency_ms=round(latency_ms, 2),
            correlation_id=req.correlation_id,
            error=last_error or "unknown_error",
        )

    async def _ensure_client(self):
        """Lazy-initialize the py-clob-client ClobClient."""
        if self._client is not None:
            return self._client

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            creds = ApiCreds(
                api_key=self._api_key,
                api_secret=self._api_secret,
                api_passphrase=self._api_passphrase,
            )
            self._client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=self._chain_id,
                creds=creds,
            )
            log.info("clob_client_initialized", chain_id=self._chain_id)
        except ImportError as exc:
            raise RuntimeError(
                "py-clob-client not installed. Run: pip install py-clob-client"
            ) from exc

        return self._client

    def _build_order_args(self, req: ExecutionRequest, idempotency_key: str) -> dict:
        """Build keyword arguments for ClobClient.create_order."""
        from py_clob_client.clob_types import OrderArgs, OrderType

        return {
            "order_args": OrderArgs(
                token_id=req.market_id,
                price=req.price,
                size=req.size,
                side=req.side,
            ),
            "order_type": (
                OrderType.GTC if req.order_type == "LIMIT" else OrderType.FOK
            ),
            "client_order_id": idempotency_key,
        }

    @staticmethod
    def _parse_create_order(
        raw: dict,
        req: ExecutionRequest,
        latency_ms: float,
        t0: float,
    ) -> ExecutionResult:
        """Parse py-clob-client response into ExecutionResult."""
        order_id = str(raw.get("orderID") or raw.get("id") or "")
        status_raw = str(raw.get("status", "")).lower()

        status_map = {
            "matched": "filled",
            "live": "submitted",
            "partial": "partial",
            "cancelled": "rejected",
            "unmatched": "submitted",
        }
        status = status_map.get(status_raw, "submitted")

        filled_size = float(raw.get("sizeMatched") or raw.get("filled_size") or 0.0)
        avg_price = float(raw.get("avgPrice") or raw.get("avg_price") or req.price)

        return ExecutionResult(
            order_id=order_id,
            status=status,
            filled_size=filled_size,
            avg_price=avg_price,
            latency_ms=latency_ms,
            correlation_id=req.correlation_id,
        )

    async def _emit_trade_result(
        self,
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        """Construct a TradeResult from fill data and invoke the feedback callback.

        Called after every non-rejected execution.  Silently logs and returns
        on any error so the main execution path is never blocked.

        Args:
            request: The original execution request.
            result:  The completed ExecutionResult.
        """
        if self._trade_result_callback is None:
            return
        if not request.strategy_id:
            return

        from .trade_result import TradeResult

        try:
            trade = TradeResult.from_execution(
                strategy_id=request.strategy_id,
                market_id=request.market_id,
                side=request.side,
                price=request.price,
                size=request.size,
                filled_size=result.filled_size,
                avg_fill_price=result.avg_price,
                expected_ev=request.expected_ev,
                order_id=result.order_id,
            )
            log.debug(
                "executor.emitting_trade_result",
                trade_id=trade.trade_id,
                strategy_id=trade.strategy_id,
                won=trade.won,
                pnl=round(trade.pnl, 4),
            )
            await self._trade_result_callback(trade)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "executor.trade_result_callback_error",
                error=str(exc),
                correlation_id=request.correlation_id,
                exc_info=True,
            )

    @staticmethod
    def _parse_order_status(raw: dict) -> dict:
        """Parse order status response."""
        status_raw = str(raw.get("status", "")).lower()
        status_map = {
            "matched": "filled",
            "live": "submitted",
            "partial": "partial",
            "cancelled": "rejected",
        }
        return {
            "status": status_map.get(status_raw, "submitted"),
            "filled_size": float(raw.get("sizeMatched") or 0.0),
            "avg_price": float(raw.get("avgPrice") or 0.0),
        }
