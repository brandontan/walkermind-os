"""Phase 10.4 — RunController: 24H observation window controller.

Manages the lifecycle of a LivePaperRunner observation run:
    - Enforces a configurable wall-clock duration (default 24 hours).
    - Sends START alert to Telegram.
    - Calls runner.run() in a background task with a deadline.
    - Cancels cleanly on timeout or stop().
    - Sends FINAL REPORT to Telegram on completion.
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
from typing import Optional

import structlog

from .live_paper_runner import LivePaperRunner

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_DURATION_S: float = 24 * 3600.0   # 24 hours
_STOP_TIMEOUT_S: float = 30.0              # max wait for clean shutdown


# ── RunController ─────────────────────────────────────────────────────────────


class RunController:
    """24H (or configurable duration) observation run controller.

    Wraps a :class:`LivePaperRunner` with a hard wall-clock deadline, clean
    start/stop semantics, and automatic final-report generation.

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
            report_output_path: Optional file path to write the final JSON
                report.  Defaults to
                ``projects/polymarket/polyquantbot/report/PHASE10.4_LIVE_PAPER_REPORT.json``.
        """
        self._runner = runner
        self._duration_s = duration_s
        self._report_path = report_output_path or os.path.join(
            os.path.dirname(__file__),
            "..",
            "report",
            "PHASE10.4_LIVE_PAPER_REPORT.json",
        )
        self._stop_event: asyncio.Event = asyncio.Event()
        self._start_ts: float = 0.0
        self._run_task: Optional[asyncio.Task] = None
        self._final_report: Optional[dict] = None

        log.info(
            "run_controller_initialized",
            duration_s=duration_s,
            report_path=self._report_path,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def final_report(self) -> Optional[dict]:
        """Final report dict; populated after run completes."""
        return self._final_report

    @property
    def elapsed_s(self) -> float:
        """Seconds since the run started (0.0 if not started)."""
        return time.time() - self._start_ts if self._start_ts else 0.0

    # ── Main entry point ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Run the observation session until duration elapsed or stop() called.

        This method blocks until the run completes, then writes the final
        report.  Callers should ``await`` it directly or wrap in a task.
        """
        self._start_ts = time.time()
        self._stop_event.clear()

        await self._runner.start()

        log.info(
            "run_controller_starting",
            duration_s=self._duration_s,
            duration_h=round(self._duration_s / 3600.0, 1),
        )

        await self._runner._telegram.alert_error(
            error=(
                f"🚀 *PHASE 10.4 PAPER OBSERVATION STARTED*\n"
                f"Duration: `{self._duration_s/3600:.0f}h`\n"
                f"Markets: `{len(self._runner._market_ids)}`\n"
                f"Mode: `PAPER` — ZERO real orders"
            ),
            context="run_controller_start",
        )

        try:
            # Run with a wall-clock deadline
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
        """Launch runner and duration watchdog concurrently."""
        self._run_task = asyncio.create_task(
            self._runner.run(), name="live_paper_run"
        )
        watchdog_task = asyncio.create_task(
            self._duration_watchdog(), name="run_duration_watchdog"
        )

        try:
            done, pending = await asyncio.wait(
                [self._run_task, watchdog_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in [self._run_task, watchdog_task]:
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

    async def _finalize(self) -> None:
        """Build and persist the final report, then send Telegram summary."""
        self._final_report = self._runner.build_report()
        self._final_report["elapsed_s"] = round(self.elapsed_s, 1)

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

        msg = (
            f"📋 *PHASE 10.4 OBSERVATION COMPLETE*\n"
            f"Elapsed: `{round(self.elapsed_s/3600, 1):.1f}h`\n"
            f"Events: `{summary.get('total_events', 0)}` | "
            f"Fills: `{summary.get('total_fills', 0)}`\n"
            f"Fill Rate: `{metrics.get('fill_rate', 0):.1%}` | "
            f"p95 Lat: `{lat.get('p95_latency_ms', 0):.0f}ms`\n"
            f"Avg Slip: `{slip.get('avg_slippage_bps', 0):.1f}bps`\n"
            f"WS Reconnects: `{summary.get('ws_reconnects', 0)}`\n"
            f"*GO-LIVE READY: {go_live}*"
        )

        await self._runner._telegram.alert_error(
            error=msg, context="run_controller_final_report"
        )

        log.info(
            "run_controller_finalized",
            go_live_ready=go_live,
            elapsed_h=round(self.elapsed_s / 3600.0, 2),
        )
