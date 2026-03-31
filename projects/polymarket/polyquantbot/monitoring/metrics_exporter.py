"""Observability layer — MetricsExporter.

Read-only aggregator that pulls live data from:
    - MetricsValidator  (phase9) — latency, slippage, fill_rate, drawdown
    - RiskGuard         (phase8) — system state / kill-switch status
    - FillTracker       (execution) — per-fill aggregates

Design:
    - Zero writes to any source module — pure reads via public APIs.
    - snapshot() is synchronous and safe to call at any frequency.
    - A background asyncio.Task emits a structured log every 60 s.
    - If any source is unavailable, affected fields are returned as None.
    - Exporter failure never propagates to the calling code.

Usage::

    exporter = MetricsExporter(
        metrics_validator=validator,
        risk_guard=guard,
        fill_tracker=tracker,
    )
    await exporter.start_logging_loop()    # optional 60-s log hook
    snapshot = exporter.snapshot()         # MetricsSnapshot
    payload  = snapshot.to_dict()          # JSON-safe dict
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Optional

import structlog

from .schema import MetricsSnapshot, SystemState

log = structlog.get_logger()

_LOG_INTERVAL_S: float = 60.0


class MetricsExporter:
    """Read-only aggregator that builds a :class:`~schema.MetricsSnapshot`.

    All source modules are optional; missing modules yield ``None`` for the
    corresponding fields.  The exporter is deliberately decoupled — it holds
    weak references only through the constructor arguments and never modifies
    any source module state.

    Args:
        metrics_validator: Optional :class:`~phase9.metrics_validator.MetricsValidator`
            instance to read latency / slippage / fill-rate / drawdown from.
        risk_guard: Optional :class:`~phase8.risk_guard.RiskGuard` instance to
            derive :class:`~schema.SystemState` from.
        fill_tracker: Optional :class:`~execution.fill_tracker.FillTracker`
            instance to read per-fill aggregates from.
        log_interval_s: Period (seconds) between periodic log snapshots.
    """

    def __init__(
        self,
        metrics_validator: Optional[object] = None,
        risk_guard: Optional[object] = None,
        fill_tracker: Optional[object] = None,
        log_interval_s: float = _LOG_INTERVAL_S,
    ) -> None:
        self._metrics_validator = metrics_validator
        self._risk_guard = risk_guard
        self._fill_tracker = fill_tracker
        self._log_interval_s = log_interval_s
        self._logging_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

        log.info(
            "metrics_exporter_initialized",
            has_metrics_validator=metrics_validator is not None,
            has_risk_guard=risk_guard is not None,
            has_fill_tracker=fill_tracker is not None,
            log_interval_s=log_interval_s,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def snapshot(self) -> MetricsSnapshot:
        """Build and return the current :class:`~schema.MetricsSnapshot`.

        Never raises — any per-field error is caught, logged, and the field
        is set to ``None``.

        Returns:
            Latest :class:`~schema.MetricsSnapshot`.
        """
        return MetricsSnapshot(
            latency_p95_ms=self._read_latency_p95(),
            avg_slippage_bps=self._read_avg_slippage(),
            fill_rate=self._read_fill_rate(),
            execution_success_rate=self._read_execution_success_rate(),
            drawdown_pct=self._read_drawdown_pct(),
            system_state=self._read_system_state(),
            snapshot_ts=time.time(),
        )

    async def start_logging_loop(self) -> None:
        """Start a background task that logs a metrics snapshot every 60 s.

        Idempotent — calling more than once has no additional effect.
        The task runs until the event loop is closed or
        :meth:`stop_logging_loop` is called.
        """
        if self._logging_task is not None and not self._logging_task.done():
            return
        self._logging_task = asyncio.create_task(
            self._periodic_log(), name="metrics_exporter_log_loop"
        )
        log.info("metrics_exporter_logging_loop_started", interval_s=self._log_interval_s)

    async def stop_logging_loop(self) -> None:
        """Cancel and await the periodic logging task, if running."""
        if self._logging_task is not None and not self._logging_task.done():
            self._logging_task.cancel()
            try:
                await self._logging_task
            except asyncio.CancelledError:
                pass
        self._logging_task = None
        log.info("metrics_exporter_logging_loop_stopped")

    # ── Private helpers ────────────────────────────────────────────────────────

    def _read_latency_p95(self) -> Optional[float]:
        """Read p95 latency from MetricsValidator."""
        mv = self._metrics_validator
        if mv is None:
            return None
        try:
            samples: list[float] = getattr(mv, "_latency_samples_ms", [])
            if not samples:
                return None
            sorted_s = sorted(samples)
            idx = max(0, math.ceil(len(sorted_s) * 0.95) - 1)
            return round(sorted_s[idx], 2)
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics_exporter_latency_read_error", error=str(exc))
            return None

    def _read_avg_slippage(self) -> Optional[float]:
        """Read average slippage from FillTracker (preferred) or MetricsValidator."""
        ft = self._fill_tracker
        if ft is not None:
            try:
                agg = ft.aggregate()
                samples_exist = getattr(ft, "_records", {})
                if not samples_exist:
                    return None
                return round(agg.avg_slippage_bps, 2)
            except Exception as exc:  # noqa: BLE001
                log.warning("metrics_exporter_fill_tracker_slippage_error", error=str(exc))

        mv = self._metrics_validator
        if mv is None:
            return None
        try:
            samples: list[float] = getattr(mv, "_slippage_samples_bps", [])
            if not samples:
                return None
            return round(sum(samples) / len(samples), 2)
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics_exporter_slippage_read_error", error=str(exc))
            return None

    def _read_fill_rate(self) -> Optional[float]:
        """Read fill rate from MetricsValidator."""
        mv = self._metrics_validator
        if mv is None:
            return None
        try:
            submitted: int = getattr(mv, "_orders_submitted", 0)
            filled: int = getattr(mv, "_orders_filled", 0)
            if submitted == 0:
                return None
            return round(filled / submitted, 4)
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics_exporter_fill_rate_read_error", error=str(exc))
            return None

    def _read_execution_success_rate(self) -> Optional[float]:
        """Read execution success rate from FillTracker (preferred) or MetricsValidator."""
        ft = self._fill_tracker
        if ft is not None:
            try:
                records = getattr(ft, "_records", {})
                if not records:
                    return None
                agg = ft.aggregate()
                return round(agg.execution_success_rate, 4)
            except Exception as exc:  # noqa: BLE001
                log.warning("metrics_exporter_exec_rate_read_error", error=str(exc))

        # Fall back to MetricsValidator fill_rate
        return self._read_fill_rate()

    def _read_drawdown_pct(self) -> Optional[float]:
        """Compute current peak-to-trough drawdown percentage from MetricsValidator PnL timeline."""
        mv = self._metrics_validator
        if mv is None:
            return None
        try:
            timeline: list[float] = getattr(mv, "_pnl_timeline", [])
            if not timeline:
                return None
            peak = timeline[0]
            max_dd = 0.0
            for pnl in timeline:
                if pnl > peak:
                    peak = pnl
                if peak != 0.0:
                    dd = (peak - pnl) / abs(peak)
                    if dd > max_dd:
                        max_dd = dd
            return round(max_dd * 100.0, 4)   # return as percentage
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics_exporter_drawdown_read_error", error=str(exc))
            return None

    def _read_system_state(self) -> SystemState:
        """Derive :class:`~schema.SystemState` from RiskGuard."""
        rg = self._risk_guard
        if rg is None:
            return SystemState.RUNNING
        try:
            disabled: bool = getattr(rg, "disabled", False)
            if disabled:
                return SystemState.HALTED
            return SystemState.RUNNING
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics_exporter_state_read_error", error=str(exc))
            return SystemState.RUNNING

    async def _periodic_log(self) -> None:
        """Background coroutine — emits a structured log every ``_log_interval_s``."""
        while True:
            await asyncio.sleep(self._log_interval_s)
            try:
                snap = self.snapshot()
                log.info(
                    "metrics_snapshot",
                    latency_p95_ms=snap.latency_p95_ms,
                    avg_slippage_bps=snap.avg_slippage_bps,
                    fill_rate=snap.fill_rate,
                    execution_success_rate=snap.execution_success_rate,
                    drawdown_pct=snap.drawdown_pct,
                    system_state=snap.system_state.value,
                    snapshot_ts=snap.snapshot_ts,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("metrics_exporter_periodic_log_error", error=str(exc))
