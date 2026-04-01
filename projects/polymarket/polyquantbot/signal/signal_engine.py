"""Phase 10.8 — SignalEngine: structured signal debug logging and counters.

Wraps any user-supplied decision_callback with:
  - Per-tick structured debug logging
  - Signal counter metrics (generated / skipped with reason breakdown)
  - SIGNAL_DEBUG_MODE: lower edge threshold for observation runs
  - Forced test-signal fallback when no signal fires for 30 minutes

Usage::

    engine = SignalEngine(
        decision_callback=my_callback,
        signal_metrics=metrics,
        debug_mode=True,
    )

    # Drop-in replacement for decision_callback:
    signal = await engine(market_id, market_ctx)

Environment variables:
    SIGNAL_DEBUG_MODE      — "true" lowers edge threshold to 0.02
    SIGNAL_EDGE_THRESHOLD  — normal edge threshold (default 0.05)
    SIGNAL_DEBUG_THRESHOLD — debug edge threshold (default 0.02)
    SIGNAL_NO_SIGNAL_TIMEOUT_S — seconds before forced test signal (default 1800)
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

import structlog

from ..monitoring.signal_metrics import SignalMetrics, SkipReason

log = structlog.get_logger()

# ── Configuration defaults ────────────────────────────────────────────────────

_DEFAULT_EDGE_THRESHOLD: float = 0.05
_DEFAULT_DEBUG_EDGE_THRESHOLD: float = 0.02
_DEFAULT_NO_SIGNAL_TIMEOUT_S: float = 1800.0  # 30 minutes
_DEBUG_TEST_SIGNAL_SIZE_USD: float = 1.0  # smallest safe size


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse an environment variable as a boolean."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


def _env_float(name: str, default: float) -> float:
    """Parse an environment variable as a float."""
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


# ── SignalEngine ──────────────────────────────────────────────────────────────


class SignalEngine:
    """Wraps a decision_callback with Phase 10.8 debug instrumentation.

    Thread-safety: single asyncio event loop only.

    Attributes:
        debug_mode: When True, edge threshold is lowered for observation.
        edge_threshold: Minimum model-vs-market edge required to trade.
        no_signal_timeout_s: Seconds of silence before a test signal is emitted.
    """

    def __init__(
        self,
        decision_callback: Callable[
            [str, dict], Awaitable[Optional[dict]]
        ],
        signal_metrics: SignalMetrics,
        debug_mode: Optional[bool] = None,
        edge_threshold: Optional[float] = None,
        debug_edge_threshold: Optional[float] = None,
        no_signal_timeout_s: Optional[float] = None,
    ) -> None:
        """Initialise the SignalEngine.

        Args:
            decision_callback: Async callable ``(market_id, ctx) -> dict | None``.
                Must return a dict with keys: side, price, size_usd, p_model,
                p_market (the latter two used for edge debug logging).
                Return None to skip this tick.
            signal_metrics: SignalMetrics instance accumulating counters.
            debug_mode: Override SIGNAL_DEBUG_MODE env var when not None.
            edge_threshold: Override SIGNAL_EDGE_THRESHOLD env var when not None.
            debug_edge_threshold: Override SIGNAL_DEBUG_THRESHOLD when not None.
            no_signal_timeout_s: Seconds before forced test signal is emitted.
        """
        self._callback = decision_callback
        self._metrics = signal_metrics

        self.debug_mode: bool = (
            debug_mode
            if debug_mode is not None
            else _env_bool("SIGNAL_DEBUG_MODE", False)
        )

        normal_threshold = (
            edge_threshold
            if edge_threshold is not None
            else _env_float("SIGNAL_EDGE_THRESHOLD", _DEFAULT_EDGE_THRESHOLD)
        )
        debug_threshold = (
            debug_edge_threshold
            if debug_edge_threshold is not None
            else _env_float("SIGNAL_DEBUG_THRESHOLD", _DEFAULT_DEBUG_EDGE_THRESHOLD)
        )

        # Active threshold depends on mode
        self.edge_threshold: float = debug_threshold if self.debug_mode else normal_threshold

        self.no_signal_timeout_s: float = (
            no_signal_timeout_s
            if no_signal_timeout_s is not None
            else _env_float("SIGNAL_NO_SIGNAL_TIMEOUT_S", _DEFAULT_NO_SIGNAL_TIMEOUT_S)
        )

        self._last_signal_ts: float = time.time()

        log.info(
            "signal_engine_initialized",
            debug_mode=self.debug_mode,
            edge_threshold=self.edge_threshold,
            no_signal_timeout_s=self.no_signal_timeout_s,
        )

    # ── Public callable ───────────────────────────────────────────────────────

    async def __call__(
        self, market_id: str, market_ctx: dict
    ) -> Optional[dict]:
        """Invoke the wrapped callback and apply signal debug instrumentation.

        Logs every tick's decision, updates counters, and emits a test signal
        if no real signal has fired within ``no_signal_timeout_s``.

        Args:
            market_id: Polymarket condition ID.
            market_ctx: Current market microstructure context from the runner.

        Returns:
            Signal dict or None.
        """
        log.debug(
            "decision_callback_triggered",
            market_id=market_id,
            debug_mode=self.debug_mode,
            edge_threshold=self.edge_threshold,
        )

        # ── Check forced test-signal timeout ─────────────────────────────────
        if self._should_emit_test_signal():
            return self._build_test_signal(market_id, market_ctx)

        # ── Invoke wrapped callback ───────────────────────────────────────────
        try:
            raw_signal = await self._callback(market_id, market_ctx)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "signal_engine_callback_error",
                market_id=market_id,
                error=str(exc),
                exc_info=True,
            )
            # Callback failure is an internal system block, not a low-edge skip
            self._metrics.record_skip(SkipReason.RISK_BLOCK)
            return None

        if raw_signal is None:
            self._log_skip(market_id, market_ctx, SkipReason.LOW_EDGE)
            return None

        # ── Extract model/market probabilities for edge logging ───────────────
        p_model: float = float(raw_signal.get("p_model", 0.0))
        p_market: float = float(raw_signal.get("p_market", float(raw_signal.get("price", 0.0))))
        edge: float = abs(p_model - p_market)

        # ── Edge threshold gate ───────────────────────────────────────────────
        if edge < self.edge_threshold:
            self._log_decision(
                market_id=market_id,
                p_model=p_model,
                p_market=p_market,
                edge=edge,
                decision="SKIP",
                reason=SkipReason.LOW_EDGE,
            )
            self._metrics.record_skip(SkipReason.LOW_EDGE)
            return None

        # ── Signal accepted ───────────────────────────────────────────────────
        self._log_decision(
            market_id=market_id,
            p_model=p_model,
            p_market=p_market,
            edge=edge,
            decision="EXECUTE",
            reason=None,
        )
        self._metrics.record_generated()
        self._last_signal_ts = time.time()

        return raw_signal

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _should_emit_test_signal(self) -> bool:
        """Return True if no signal has fired within no_signal_timeout_s."""
        return (time.time() - self._last_signal_ts) >= self.no_signal_timeout_s

    def _build_test_signal(self, market_id: str, market_ctx: dict) -> dict:
        """Emit a minimal safe test signal marked as 'debug_signal'.

        Args:
            market_id: Target market.
            market_ctx: Current market context (used for best-ask price).

        Returns:
            Signal dict with is_debug_signal=True.
        """
        bid = float(market_ctx.get("bid", 0.5))
        ask = float(market_ctx.get("ask", 0.55))
        price = round((bid + ask) / 2.0, 4) if ask > bid else 0.5

        test_signal: dict[str, Any] = {
            "side": "YES",
            "price": price,
            "size_usd": _DEBUG_TEST_SIGNAL_SIZE_USD,
            "expected_ev": 0.0,
            "p_model": price + self.edge_threshold,
            "p_market": price,
            "is_debug_signal": True,
            "debug_id": str(uuid.uuid4())[:8],
        }

        self._last_signal_ts = time.time()
        self._metrics.record_generated()

        log.warning(
            "signal_engine_forced_test_signal",
            market_id=market_id,
            price=price,
            size_usd=_DEBUG_TEST_SIGNAL_SIZE_USD,
            debug_id=test_signal["debug_id"],
            timeout_s=self.no_signal_timeout_s,
        )

        return test_signal

    def _log_decision(
        self,
        market_id: str,
        p_model: float,
        p_market: float,
        edge: float,
        decision: str,
        reason: Optional[SkipReason],
    ) -> None:
        """Emit a structured signal-decision log event.

        Args:
            market_id: Polymarket condition ID.
            p_model: Model-estimated probability.
            p_market: Current market price (implied probability).
            edge: Absolute model-vs-market edge.
            decision: "EXECUTE" or "SKIP".
            reason: SkipReason if decision is SKIP, else None.
        """
        log.info(
            "signal_decision",
            market=market_id,
            p_model=round(p_model, 4),
            p_market=round(p_market, 4),
            edge=round(edge, 4),
            threshold=round(self.edge_threshold, 4),
            decision=decision,
            reason=reason.value if reason else None,
        )

    def _log_skip(
        self,
        market_id: str,
        market_ctx: dict,
        reason: SkipReason,
    ) -> None:
        """Log a tick skipped because the callback returned None."""
        price = float(market_ctx.get("mid", 0.0))
        log.info(
            "signal_decision",
            market=market_id,
            p_model=0.0,
            p_market=round(price, 4),
            edge=0.0,
            threshold=round(self.edge_threshold, 4),
            decision="SKIP",
            reason=reason.value,
        )
        self._metrics.record_skip(reason)

    # ── Metrics convenience ───────────────────────────────────────────────────

    def record_skip(self, reason: SkipReason) -> None:
        """Record a skip event from an external caller (e.g. ExecutionGuard).

        Args:
            reason: Why this signal was skipped.
        """
        self._metrics.record_skip(reason)
