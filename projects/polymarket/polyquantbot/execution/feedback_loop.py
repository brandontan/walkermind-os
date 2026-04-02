"""FeedbackLoop — adaptive learning orchestrator.

Wires execution results into the metrics layer and capital allocator so the
system adapts trade-by-trade:

    execution → FeedbackLoop.on_trade_result()
                  ├─ MultiStrategyMetrics.update_trade_result()   (idempotent)
                  ├─ DynamicCapitalAllocator.update_from_metrics() (reweights)
                  └─ TelegramLive.alert_live_performance()         (optional)

Design
------
- Idempotency: duplicate ``trade_id`` values are silently skipped.
- No silent failure: every exception is logged at ERROR level.
- Works in both PAPER and LIVE mode — no execution guard bypass.
- Thread-safety: single asyncio event loop only.

Usage
-----
Wire the loop into :class:`~execution.clob_executor.LiveExecutor` at startup::

    from execution.feedback_loop import FeedbackLoop

    loop = FeedbackLoop(
        metrics=multi_strategy_metrics,
        allocator=dynamic_capital_allocator,
        telegram=telegram_live,          # optional
        drawdown_provider=lambda s: risk_guard.drawdown(s),  # optional
    )

    executor = LiveExecutor(
        ...,
        trade_result_callback=loop.on_trade_result,
    )

Then after every fill the loop fires automatically.

Telegram performance alerts are rate-limited: a minimum of
``telegram_min_interval_s`` seconds must elapse between successive reports
(default 300 s = 5 minutes).
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Dict, Optional

import structlog

log = structlog.get_logger(__name__)

# Minimum seconds between Telegram performance updates (per-strategy)
_DEFAULT_TELEGRAM_INTERVAL_S: float = 300.0


class FeedbackLoop:
    """Adaptive feedback loop: execution → metrics → allocation.

    Args:
        metrics:            :class:`~monitoring.multi_strategy_metrics.MultiStrategyMetrics`
                            instance shared with the pipeline.
        allocator:          :class:`~strategy.capital_allocator.DynamicCapitalAllocator`
                            instance shared with the pipeline.
        telegram:           Optional :class:`~telegram.telegram_live.TelegramLive`
                            instance for performance update alerts.
        drawdown_provider:  Optional callable ``(strategy_id: str) → float`` that
                            returns the current drawdown for a strategy.  If not
                            provided, drawdown is assumed to be 0.0.
        telegram_min_interval_s: Minimum seconds between Telegram performance
                            updates per strategy.
    """

    def __init__(
        self,
        metrics: "MultiStrategyMetrics",  # type: ignore[name-defined]
        allocator: "DynamicCapitalAllocator",  # type: ignore[name-defined]
        telegram: Optional["TelegramLive"] = None,  # type: ignore[name-defined]
        drawdown_provider: Optional[Callable[[str], float]] = None,
        telegram_min_interval_s: float = _DEFAULT_TELEGRAM_INTERVAL_S,
    ) -> None:
        self._metrics = metrics
        self._allocator = allocator
        self._telegram = telegram
        self._drawdown_provider = drawdown_provider
        self._tg_interval = telegram_min_interval_s

        # Track last Telegram alert per strategy (Unix timestamp)
        self._last_tg_alert: Dict[str, float] = {}

        log.info(
            "feedback_loop_initialized",
            telegram_enabled=telegram is not None,
            telegram_min_interval_s=telegram_min_interval_s,
        )

    # ── Primary entry point ───────────────────────────────────────────────────

    async def on_trade_result(self, trade: "TradeResult") -> None:  # type: ignore[name-defined]
        """Process a completed trade and propagate updates through the pipeline.

        This method is passed as ``trade_result_callback`` to
        :class:`~execution.clob_executor.LiveExecutor`.  It is guaranteed to
        never raise — all exceptions are caught and logged so the execution
        path remains stable.

        Steps:
            1. Update :class:`MultiStrategyMetrics` (idempotent).
            2. Push live metrics into :class:`DynamicCapitalAllocator`.
            3. Optionally send a Telegram performance update (rate-limited).

        Args:
            trade: Completed :class:`~execution.trade_result.TradeResult`.
        """
        try:
            await self._apply_to_metrics(trade)
            await self._apply_to_allocator(trade)
            await self._maybe_send_telegram(trade.strategy_id)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "feedback_loop.unhandled_error",
                trade_id=trade.trade_id,
                strategy_id=trade.strategy_id,
                error=str(exc),
                exc_info=True,
            )

    # ── Step 1: metrics ───────────────────────────────────────────────────────

    async def _apply_to_metrics(self, trade: "TradeResult") -> None:
        """Push trade result into MultiStrategyMetrics (idempotent)."""
        applied = self._metrics.update_trade_result(trade)
        if applied:
            log.debug(
                "feedback_loop.metrics_updated",
                strategy_id=trade.strategy_id,
                trade_id=trade.trade_id,
            )

    # ── Step 2: allocator ─────────────────────────────────────────────────────

    async def _apply_to_allocator(self, trade: "TradeResult") -> None:
        """Push live StrategyMetrics into DynamicCapitalAllocator."""
        try:
            strategy_metrics = self._metrics.get_metrics(trade.strategy_id)
        except KeyError:
            log.warning(
                "feedback_loop.metrics_not_found_for_allocator",
                strategy_id=trade.strategy_id,
            )
            return

        drawdown = 0.0
        if self._drawdown_provider is not None:
            try:
                drawdown = float(self._drawdown_provider(trade.strategy_id))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "feedback_loop.drawdown_provider_error",
                    strategy_id=trade.strategy_id,
                    error=str(exc),
                )

        try:
            self._allocator.update_from_metrics(
                strategy_name=trade.strategy_id,
                strategy_metrics=strategy_metrics,
                drawdown=drawdown,
            )
            log.debug(
                "feedback_loop.allocator_updated",
                strategy_id=trade.strategy_id,
                win_rate=round(strategy_metrics.win_rate, 4),
                ev_capture_rate=round(strategy_metrics.ev_capture_rate, 4),
                drawdown=round(drawdown, 4),
            )
        except KeyError:
            log.warning(
                "feedback_loop.strategy_not_in_allocator",
                strategy_id=trade.strategy_id,
            )

    # ── Step 3: Telegram ──────────────────────────────────────────────────────

    async def _maybe_send_telegram(self, strategy_id: str) -> None:
        """Send a Telegram performance update if the rate-limit window has elapsed."""
        if self._telegram is None:
            return

        now = time.monotonic()
        last = self._last_tg_alert.get(strategy_id, 0.0)
        if now - last < self._tg_interval:
            return

        self._last_tg_alert[strategy_id] = now
        await self._send_performance_update()

    async def _send_performance_update(self) -> None:
        """Build a full portfolio snapshot and dispatch a Telegram alert."""
        try:
            snapshot = self._allocator.allocation_snapshot()
            metrics_snapshot = self._metrics.snapshot()

            # Build per-strategy performance data
            strategy_data: Dict[str, dict] = {}
            for name in snapshot.strategy_weights:
                m = metrics_snapshot.get(name, {})
                strategy_data[name] = {
                    "pnl": m.get("total_pnl", 0.0),
                    "win_rate": m.get("win_rate", 0.0),
                    "trades": m.get("trades_executed", 0),
                    "weight": snapshot.strategy_weights.get(name, 0.0),
                    "size_usd": snapshot.position_sizes.get(name, 0.0),
                }

            await self._telegram.alert_live_performance(
                strategy_data=strategy_data,
                total_allocated_usd=snapshot.total_allocated_usd,
                bankroll=snapshot.bankroll,
                disabled=snapshot.disabled_strategies,
                suppressed=snapshot.suppressed_strategies,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "feedback_loop.telegram_send_error",
                error=str(exc),
                exc_info=True,
            )

    # ── Snapshot helper ───────────────────────────────────────────────────────

    def performance_snapshot(self) -> dict:
        """Return a full performance snapshot suitable for reporting.

        Returns:
            Dict with keys: ``strategies`` (per-strategy metrics + allocation),
            ``total_trades``, ``total_pnl``, ``allocation``.
        """
        metrics_snap = self._metrics.snapshot()
        alloc_snap = self._allocator.allocation_snapshot()

        strategies: Dict[str, dict] = {}
        total_pnl = 0.0

        for name, m in metrics_snap.items():
            pnl = m.get("total_pnl", 0.0)
            total_pnl += pnl
            strategies[name] = {
                **m,
                "weight": alloc_snap.strategy_weights.get(name, 0.0),
                "position_size_usd": alloc_snap.position_sizes.get(name, 0.0),
                "disabled": name in alloc_snap.disabled_strategies,
                "suppressed": name in alloc_snap.suppressed_strategies,
            }

        return {
            "strategies": strategies,
            "total_trades": self._metrics.total_trades,
            "total_pnl": round(total_pnl, 6),
            "total_allocated_usd": alloc_snap.total_allocated_usd,
            "bankroll": alloc_snap.bankroll,
        }
