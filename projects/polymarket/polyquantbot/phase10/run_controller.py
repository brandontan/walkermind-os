"""Phase 10.8 — RunController: 6H-minimum observation window controller.

Manages the lifecycle of a LivePaperRunner observation run:
    - Enforces a configurable wall-clock duration (default 24 hours).
    - Enforces a minimum run duration of 6 hours — shorter durations are
      rejected immediately with a ValueError.
    - Sends START alert to Telegram (includes SIGNAL_DEBUG_MODE status).
    - Calls runner.run() in a background task with a deadline.
    - At 2 hours: checks signals_generated > 0 and orders_attempted > 0.
      If either is zero, marks run as CRITICAL FAILURE and fires Telegram alert.
    - Cancels cleanly on timeout or stop().
    - Sends FINAL REPORT to Telegram on completion (includes critical_failure
      flag and signal_metrics).
    - Persists the final report to a JSON file.

Usage::

    runner = LivePaperRunner.from_config(config, market_ids=[...])
    controller = RunController(runner, duration_s=86400)
    await controller.start()           # blocks until duration elapsed or stop()
    report = controller.final_report   # available after run completes

Deterministic shutdown:
    - stop() sets _stop_event → cancels the run task → clean teardown.
    - Duration timeout triggers the same code path as stop().
    - Never hangs: stop() has a 30 s hard timeout before force-cancel.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import List, Optional

import structlog

from .live_paper_runner import LivePaperRunner

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_DURATION_S: float = 24 * 3600.0    # 24 hours
_MIN_DURATION_S: float = 6 * 3600.0         # 6 hours — minimum enforced
_STOP_TIMEOUT_S: float = 30.0               # max wait for clean shutdown
_SIGNAL_VALIDATION_WINDOW_S: float = 2 * 3600.0  # 2-hour activity checkpoint


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse an environment variable as a boolean."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


# ── RunController ─────────────────────────────────────────────────────────────


class RunController:
    """Phase 10.8 observation run controller with 6H minimum and 2H validation.

    Wraps a :class:`LivePaperRunner` with a hard wall-clock deadline, clean
    start/stop semantics, automatic final-report generation, and Phase 10.8
    signal-activity validation at the 2-hour mark.

    Minimum run duration of 6 hours is enforced — passing a shorter value
    raises ``ValueError`` immediately in ``__init__``.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        runner: LivePaperRunner,
        duration_s: float = _DEFAULT_DURATION_S,
        report_output_path: Optional[str] = None,
    ) -> None:
        """Initialise the run controller.

        Args:
            runner: Pre-built :class:`LivePaperRunner` instance.
            duration_s: Maximum run duration in seconds (default 86400 = 24 h).
                Must be ≥ 6 hours (21600 s).  Shorter values raise
                ``ValueError``.
            report_output_path: Optional file path to write the final JSON
                report.  Defaults to
                ``projects/polymarket/polyquantbot/report/PHASE10.8_LIVE_PAPER_REPORT.json``.

        Raises:
            ValueError: If ``duration_s`` is less than 6 hours (21600 s).
        """
        if duration_s < _MIN_DURATION_S:
            raise ValueError(
                f"RunController duration_s={duration_s:.0f}s is below the "
                f"minimum allowed run duration of {_MIN_DURATION_S:.0f}s "
                f"({_MIN_DURATION_S / 3600:.0f}h).  "
                f"Phase 10.8 requires a minimum 6-hour run."
            )

        self._runner = runner
        self._duration_s = duration_s
        self._report_path = report_output_path or os.path.join(
            os.path.dirname(__file__),
            "..",
            "report",
            "PHASE10.8_LIVE_PAPER_REPORT.json",
        )
        self._stop_event: asyncio.Event = asyncio.Event()
        self._start_ts: float = 0.0
        self._run_task: Optional[asyncio.Task] = None
        self._final_report: Optional[dict] = None

        # Phase 10.8 — critical-failure tracking
        self._critical_failure: bool = False
        self._critical_failure_reasons: List[str] = []

        log.info(
            "run_controller_initialized",
            duration_s=duration_s,
            min_duration_s=_MIN_DURATION_S,
            signal_validation_window_s=_SIGNAL_VALIDATION_WINDOW_S,
            report_path=self._report_path,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def final_report(self) -> Optional[dict]:
        """Final report dict; populated after run completes."""
        return self._final_report

    @property
    def critical_failure(self) -> bool:
        """True if the 2-hour signal/trade activity validation failed."""
        return self._critical_failure

    @property
    def critical_failure_reasons(self) -> List[str]:
        """List of reason strings explaining the critical failure."""
        return list(self._critical_failure_reasons)

    @property
    def elapsed_s(self) -> float:
        """Seconds since the run started (0.0 if not started)."""
        return time.time() - self._start_ts if self._start_ts else 0.0

    # ── Main entry point ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Run the Phase 10.8 observation session until duration elapsed or stop() called.

        Launches the runner, a duration watchdog, and the 2-hour signal/trade
        activity validation task.  Blocks until the run completes, then writes
        the final report.

        Callers should ``await`` it directly or wrap in a task.
        """
        self._start_ts = time.time()
        self._stop_event.clear()

        await self._runner.start()

        signal_debug_active = _env_bool("SIGNAL_DEBUG_MODE", False)

        log.info(
            "run_controller_starting",
            duration_s=self._duration_s,
            duration_h=round(self._duration_s / 3600.0, 1),
            signal_debug_mode=signal_debug_active,
            signal_validation_window_h=_SIGNAL_VALIDATION_WINDOW_S / 3600.0,
        )

        await self._runner._telegram.alert_error(
            error=(
                f"🚀 *PHASE 10.8 PAPER OBSERVATION STARTED*\n"
                f"Duration: `{self._duration_s/3600:.0f}h` (min 6h enforced)\n"
                f"Markets: `{len(self._runner._market_ids)}`\n"
                f"Mode: `PAPER` — ZERO real orders\n"
                f"SIGNAL_DEBUG_MODE: `{'ON ✅' if signal_debug_active else 'OFF ⚠️'}`\n"
                f"2H Signal Validation: `ACTIVE` — CRITICAL FAILURE if no signals/trades"
            ),
            context="run_controller_start",
        )

        try:
            # Run the pipeline, duration watchdog, and 2H signal validation concurrently
            await asyncio.wait_for(
                self._run_with_stop_watch(),
                timeout=self._duration_s + 60.0,   # +60 s grace for stop
            )
        except asyncio.TimeoutError:
            log.warning(
                "run_controller_hard_timeout",
                duration_s=self._duration_s,
            )
        finally:
            await self._finalize()

    async def stop(self) -> None:
        """Signal a clean stop and wait for the runner to shut down.

        Safe to call from any coroutine.  Returns when the run task has
        finished or the hard timeout (_STOP_TIMEOUT_S) expires.
        """
        log.info("run_controller_stop_requested")
        self._stop_event.set()

        if self._run_task and not self._run_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._run_task), timeout=_STOP_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                log.warning("run_controller_stop_timeout_force_cancel")
                self._run_task.cancel()
                try:
                    await self._run_task
                except asyncio.CancelledError:
                    pass

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _run_with_stop_watch(self) -> None:
        """Launch runner, duration watchdog, and 2H signal validation concurrently."""
        self._run_task = asyncio.create_task(
            self._runner.run(), name="live_paper_run"
        )
        watchdog_task = asyncio.create_task(
            self._duration_watchdog(), name="run_duration_watchdog"
        )
        validation_task = asyncio.create_task(
            self._signal_validation(), name="run_signal_validation"
        )

        try:
            done, pending = await asyncio.wait(
                [self._run_task, watchdog_task, validation_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in [self._run_task, watchdog_task, validation_task]:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    async def _duration_watchdog(self) -> None:
        """Wait for the configured duration or stop event, then stop runner."""
        deadline = self._start_ts + self._duration_s
        while True:
            remaining = deadline - time.time()
            if remaining <= 0 or self._stop_event.is_set():
                break
            wait_s = min(remaining, 60.0)
            try:
                await asyncio.wait_for(
                    asyncio.shield(asyncio.ensure_future(self._stop_event.wait())),
                    timeout=wait_s,
                )
                break  # stop_event fired
            except asyncio.TimeoutError:
                continue

        log.info(
            "run_controller_duration_elapsed",
            elapsed_s=round(self.elapsed_s, 1),
        )
        await self._runner.stop()

    async def _signal_validation(self) -> None:
        """Phase 10.8: 2-hour signal/trade activity validation.

        Waits until ``_SIGNAL_VALIDATION_WINDOW_S`` seconds have elapsed, then
        checks whether signals and orders have been generated.  If either
        counter is still zero, the run is flagged as CRITICAL FAILURE and a
        Telegram alert is sent.

        Does NOT stop the run — the observation continues to the full duration
        regardless of the outcome so that activity logs and root-cause data can
        be collected.
        """
        try:
            await asyncio.sleep(_SIGNAL_VALIDATION_WINDOW_S)
        except asyncio.CancelledError:
            return

        signals = self._runner._signal_count
        orders = self._runner._sim_order_count
        elapsed_h = self.elapsed_s / 3600.0

        failures = []

        if signals == 0:
            failures.append("signals_generated=0")
            log.critical(
                "run_controller_critical_failure_no_signals",
                elapsed_h=round(elapsed_h, 2),
                signals_generated=signals,
                orders_attempted=orders,
            )

        if orders == 0:
            failures.append("orders_attempted=0")
            log.critical(
                "run_controller_critical_failure_no_orders",
                elapsed_h=round(elapsed_h, 2),
                signals_generated=signals,
                orders_attempted=orders,
            )

        if failures:
            self._critical_failure = True
            self._critical_failure_reasons = failures
            reason_str = " | ".join(failures)

            await self._runner._telegram.alert_error(
                error=(
                    f"🚨 *CRITICAL FAILURE — 2H SIGNAL VALIDATION*\n"
                    f"Elapsed: `{elapsed_h:.1f}h`\n"
                    f"signals_generated: `{signals}` {'✅' if signals > 0 else '❌ ZERO'}\n"
                    f"orders_attempted: `{orders}` {'✅' if orders > 0 else '❌ ZERO'}\n"
                    f"Reason: `{reason_str}`\n"
                    f"⚠️ Run continues — collecting root-cause data until end of session."
                ),
                context="run_controller_signal_validation",
            )
        else:
            log.info(
                "run_controller_signal_validation_passed",
                elapsed_h=round(elapsed_h, 2),
                signals_generated=signals,
                orders_attempted=orders,
            )
            await self._runner._telegram.alert_error(
                error=(
                    f"✅ *2H SIGNAL VALIDATION PASSED*\n"
                    f"Elapsed: `{elapsed_h:.1f}h`\n"
                    f"signals_generated: `{signals}` ✅\n"
                    f"orders_attempted: `{orders}` ✅"
                ),
                context="run_controller_signal_validation",
            )

    async def _finalize(self) -> None:
        """Build and persist the final report, then send Telegram summary."""
        self._final_report = self._runner.build_report()
        self._final_report["elapsed_s"] = round(self.elapsed_s, 1)

        # Phase 10.8 — embed critical failure verdict
        self._final_report["critical_failure"] = self._critical_failure
        self._final_report["critical_failure_reasons"] = list(self._critical_failure_reasons)

        # Persist to file
        try:
            os.makedirs(os.path.dirname(self._report_path), exist_ok=True)
            with open(self._report_path, "w", encoding="utf-8") as fh:
                json.dump(self._final_report, fh, indent=2)
            log.info(
                "run_controller_report_written",
                path=self._report_path,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "run_controller_report_write_failed",
                path=self._report_path,
                error=str(exc),
            )

        # Final Telegram summary
        go_live = self._final_report.get("go_live_readiness", "NO")
        summary = self._final_report.get("runtime_summary", {})
        lat = self._final_report.get("latency_stats", {})
        slip = self._final_report.get("slippage_stats", {})
        metrics = self._final_report.get("metrics_table", {})
        sig_metrics = self._final_report.get("signal_metrics", {})

        critical_line = (
            f"🚨 CRITICAL FAILURE: `{' | '.join(self._critical_failure_reasons)}`\n"
            if self._critical_failure
            else "✅ 2H Signal Validation: `PASSED`\n"
        )

        msg = (
            f"📋 *PHASE 10.8 OBSERVATION COMPLETE*\n"
            f"Elapsed: `{round(self.elapsed_s/3600, 1):.1f}h`\n"
            f"Events: `{summary.get('total_events', 0)}` | "
            f"Signals: `{summary.get('total_signals', 0)}`\n"
            f"Sim Orders: `{summary.get('total_sim_orders', 0)}` | "
            f"Fills: `{summary.get('total_fills', 0)}`\n"
            f"Fill Rate: `{metrics.get('fill_rate', 0):.1%}` | "
            f"p95 Lat: `{lat.get('p95_latency_ms', 0):.0f}ms`\n"
            f"Avg Slip: `{slip.get('avg_slippage_bps', 0):.1f}bps`\n"
            f"WS Reconnects: `{summary.get('ws_reconnects', 0)}`\n"
            f"Generated: `{sig_metrics.get('total_generated', 0)}` | "
            f"Skipped: `{sig_metrics.get('total_skipped', 0)}`\n"
            f"{critical_line}"
            f"*GO-LIVE READY: {go_live}*"
        )

        await self._runner._telegram.alert_error(
            error=msg, context="run_controller_final_report"
        )

        log.info(
            "run_controller_finalized",
            go_live_ready=go_live,
            elapsed_h=round(self.elapsed_s / 3600.0, 2),
            critical_failure=self._critical_failure,
            critical_failure_reasons=self._critical_failure_reasons,
        )
