"""Phase 9 — MetricsValidator: Post-run metric computation and GO-LIVE gating.

Computes and validates all trading session metrics after a paper or live run.
Outputs a structured metrics.json for auditing and GO-LIVE decision.

Metrics computed:
    ev_capture_ratio       — Fraction of theoretical EV actually captured.
    fill_rate              — Fraction of submitted orders that got filled.
    p95_latency            — 95th percentile execution latency (ms).
    drawdown               — Maximum peak-to-trough PnL drawdown during the session.
    fill_accuracy          — Fraction of fills within slippage threshold (default 0.0).
    avg_slippage_bps       — Average fill slippage across all trades (bps).
    p95_slippage_bps       — 95th-percentile slippage (bps).
    worst_slippage_bps     — Largest absolute slippage observed (bps).
    execution_success_rate — Fraction of submitted orders that were filled.

GO-LIVE gating (all must pass):
    ev_capture_ratio >= target (default 0.75)
    fill_rate        >= target (default 0.70)
    p95_latency      <= target (default 500ms)
    drawdown         <= target (default 10%)

Output (metrics.json)::

    {
        "ev_capture_ratio": float,
        "fill_rate": float,
        "p95_latency": float,
        "drawdown": float,
        "total_trades": int,
        "fill_accuracy": float,
        "avg_slippage_bps": float,
        "p95_slippage_bps": float,
        "worst_slippage_bps": float,
        "execution_success_rate": float,
        "pass": bool,
        "reason": str,
        "gate_details": {...},
        "session_summary": {...},
        "generated_at": str
    }

Usage::

    validator = MetricsValidator.from_config(config)
    validator.record_ev_signal(expected_ev=0.05)
    validator.record_fill(filled=True)
    validator.record_pnl_sample(pnl=12.5)
    validator.record_slippage(slippage_bps=12.5)
    metrics = validator.compute()
    validator.write(metrics, output_path="metrics.json")
    passed = validator.gate_check(metrics)
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class MetricsResult:
    """Computed metrics from a trading session.

    Attributes:
        ev_capture_ratio: Actual EV captured / theoretical EV available.
        fill_rate: Filled orders / submitted orders.
        p95_latency: 95th percentile execution latency in milliseconds.
        drawdown: Maximum peak-to-trough PnL drawdown (fraction).
        total_trades: Number of filled orders in the session.
        pass_result: True if all GO-LIVE gate checks pass.
        go_live_ready: Alias for pass_result — True when the system meets all
                       GO-LIVE conditions and execution in LIVE mode is
                       permitted.  Used by GoLiveController and SENTINEL.
        reason: Human-readable explanation of pass/fail result.
        gate_details: Per-metric pass/fail details.
        session_summary: Additional session statistics.
        fill_accuracy: Fraction of fills within slippage threshold.
        avg_slippage_bps: Average fill slippage across all trades (bps).
        p95_slippage_bps: 95th-percentile slippage (bps).
        worst_slippage_bps: Largest absolute slippage observed (bps).
        execution_success_rate: Fraction of submitted orders that were filled.
    """
    ev_capture_ratio: float
    fill_rate: float
    p95_latency: float
    drawdown: float
    total_trades: int
    pass_result: bool
    go_live_ready: bool
    reason: str
    gate_details: dict
    session_summary: dict
    # ── Execution quality metrics (Phase 10.2) ──────────────────────────────
    fill_accuracy: float = 0.0
    avg_slippage_bps: float = 0.0
    p95_slippage_bps: float = 0.0
    worst_slippage_bps: float = 0.0
    execution_success_rate: float = 1.0


# ── MetricsValidator ──────────────────────────────────────────────────────────

class MetricsValidator:
    """Computes and validates trading session metrics.

    Usage pattern:
        1. Call record_*() methods during the trading session.
        2. Call compute() at the end of the session.
        3. Call write() to persist metrics.json.
        4. Call gate_check() to determine GO-LIVE eligibility.

    Thread-safety: single asyncio event loop only.
    All record_*() methods are non-async (in-memory updates).
    """

    def __init__(
        self,
        ev_capture_target: float = 0.75,
        fill_rate_target: float = 0.70,
        p95_latency_target_ms: float = 500.0,
        max_drawdown_target: float = 0.08,
        output_file: str = "metrics.json",
        min_trades: int = 30,
        telegram=None,
        slippage_warn_bps: float = 50.0,
        latency_warn_ms: float = 500.0,
    ) -> None:
        """Initialise the validator.

        Args:
            ev_capture_target: Minimum EV capture ratio for GO-LIVE (default 0.75).
            fill_rate_target: Minimum fill rate for GO-LIVE (default 0.70).
            p95_latency_target_ms: Maximum p95 latency for GO-LIVE (default 500ms).
            max_drawdown_target: Maximum drawdown fraction for GO-LIVE (default 0.08).
            output_file: Path to write metrics.json output.
            min_trades: Minimum filled orders required for GO-LIVE (default 30).
            telegram: Optional TelegramLive instance for threshold warning alerts.
            slippage_warn_bps: Slippage threshold (bps) above which a warning alert fires.
            latency_warn_ms: Latency threshold (ms) above which a warning alert fires.
        """
        self._ev_capture_target = ev_capture_target
        self._fill_rate_target = fill_rate_target
        self._p95_latency_target = p95_latency_target_ms
        self._max_drawdown_target = max_drawdown_target
        self._output_file = output_file
        self._min_trades = min_trades
        self._telegram = telegram
        self._slippage_warn_bps = slippage_warn_bps
        self._latency_warn_ms = latency_warn_ms

        # Raw data accumulators
        self._expected_ev_samples: list[float] = []    # theoretical EVs per signal
        self._actual_ev_samples: list[float] = []      # actual EVs captured
        self._fill_outcomes: list[bool] = []           # True=filled, False=not
        self._latency_samples_ms: list[float] = []     # execution latency per order
        self._pnl_timeline: list[float] = []           # cumulative PnL over time
        self._orders_submitted: int = 0
        self._orders_filled: int = 0
        self._session_start: float = time.time()
        # ── Phase 10.2: Execution quality accumulators ────────────────────
        self._slippage_samples_bps: list[float] = []   # per-fill slippage in bps
        self._slippage_threshold_bps: float = 50.0     # threshold for fill_accuracy

        log.info(
            "metrics_validator_initialized",
            ev_capture_target=ev_capture_target,
            fill_rate_target=fill_rate_target,
            p95_latency_target_ms=p95_latency_target_ms,
            max_drawdown_target=max_drawdown_target,
            min_trades=min_trades,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: dict) -> "MetricsValidator":
        """Build from paper_run_config dict.

        Args:
            config: Top-level config dict with 'metrics' sub-key.

        Returns:
            Configured MetricsValidator instance.
        """
        metrics_cfg = config.get("metrics", {})
        return cls(
            ev_capture_target=float(metrics_cfg.get("ev_target_capture_ratio", 0.75)),
            fill_rate_target=float(metrics_cfg.get("fill_rate_target", 0.70)),
            p95_latency_target_ms=float(metrics_cfg.get("p95_latency_target_ms", 500.0)),
            max_drawdown_target=float(metrics_cfg.get("max_drawdown_target", 0.08)),
            output_file=str(metrics_cfg.get("output_file", "metrics.json")),
            min_trades=int(metrics_cfg.get("min_trades", 30)),
        )

    # ── Recording API ─────────────────────────────────────────────────────────

    def set_telegram(self, telegram) -> None:
        """Attach a TelegramLive instance for threshold warning alerts.

        Args:
            telegram: TelegramLive instance (or any object with alert_error()).
        """
        self._telegram = telegram

    def record_ev_signal(
        self,
        expected_ev: float,
        actual_ev: Optional[float] = None,
    ) -> None:
        """Record a signal's expected and actual EV.

        Args:
            expected_ev: Theoretical EV from strategy engine.
            actual_ev: EV actually captured (from fill). If None, uses 0.0
                       (not filled = zero EV captured).
        """
        self._expected_ev_samples.append(max(expected_ev, 0.0))
        self._actual_ev_samples.append(actual_ev if actual_ev is not None else 0.0)

    def record_fill(self, filled: bool) -> None:
        """Record whether a submitted order was filled.

        Args:
            filled: True if the order was filled (full or partial).
        """
        self._fill_outcomes.append(filled)
        self._orders_submitted += 1
        if filled:
            self._orders_filled += 1

    def record_latency(self, latency_ms: float) -> None:
        """Record an execution latency sample.

        Args:
            latency_ms: End-to-end execution latency in milliseconds.
        """
        if latency_ms > 0:
            self._latency_samples_ms.append(latency_ms)

    def record_pnl_sample(self, cumulative_pnl: float) -> None:
        """Record a cumulative PnL snapshot for drawdown calculation.

        Call this after every trade close or on a periodic timer.

        Args:
            cumulative_pnl: Current total realised PnL in USD.
        """
        self._pnl_timeline.append(cumulative_pnl)

    def ingest_callback_metrics(self, callback_metrics: dict) -> None:
        """Bulk-ingest metrics from DecisionCallback.metrics_snapshot().

        Args:
            callback_metrics: Dict from DecisionCallback.metrics_snapshot().
        """
        for latency in callback_metrics.get("latency_samples_ms", []):
            self.record_latency(latency)

    def record_slippage(self, slippage_bps: float) -> None:
        """Record a per-fill slippage sample.

        Args:
            slippage_bps: Slippage for one fill in basis points.
                          Positive = filled worse than expected.
        """
        self._slippage_samples_bps.append(slippage_bps)

    async def warn_slippage(
        self,
        slippage_bps: float,
        context: str = "",
        correlation_id: Optional[str] = None,
    ) -> None:
        """Fire a Telegram warning if slippage exceeds the warn threshold.

        Fires only when a TelegramLive instance has been injected.
        Never raises — failures are logged only.

        Args:
            slippage_bps: Observed slippage in basis points.
            context: Optional context string (market, side, etc.).
            correlation_id: Request trace ID.
        """
        if slippage_bps <= self._slippage_warn_bps:
            return
        log.warning(
            "metrics_slippage_threshold_exceeded",
            slippage_bps=slippage_bps,
            threshold_bps=self._slippage_warn_bps,
            context=context,
        )
        if self._telegram:
            try:
                await self._telegram.alert_error(
                    error=f"Slippage {slippage_bps:.1f}bps exceeds threshold {self._slippage_warn_bps:.1f}bps",
                    context=context or "metrics_validator:slippage_warn",
                    correlation_id=correlation_id,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("metrics_slippage_alert_failed", error=str(exc))

    async def warn_latency(
        self,
        latency_ms: float,
        context: str = "",
        correlation_id: Optional[str] = None,
    ) -> None:
        """Fire a Telegram warning if latency exceeds the warn threshold.

        Fires only when a TelegramLive instance has been injected.
        Never raises — failures are logged only.

        Args:
            latency_ms: Observed latency in milliseconds.
            context: Optional context string (operation, market, etc.).
            correlation_id: Request trace ID.
        """
        if latency_ms <= self._latency_warn_ms:
            return
        log.warning(
            "metrics_latency_threshold_exceeded",
            latency_ms=latency_ms,
            threshold_ms=self._latency_warn_ms,
            context=context,
        )
        if self._telegram:
            try:
                await self._telegram.alert_error(
                    error=f"Latency {latency_ms:.0f}ms exceeds threshold {self._latency_warn_ms:.0f}ms",
                    context=context or "metrics_validator:latency_warn",
                    correlation_id=correlation_id,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("metrics_latency_alert_failed", error=str(exc))

    def ingest_fill_aggregate(self, aggregate: object) -> None:
        """Bulk-ingest execution quality metrics from a FillAggregate.

        Accepts a :class:`~execution.fill_tracker.FillAggregate` (or any
        duck-typed object with the same attributes) and records a
        representative slippage sample from ``avg_slippage_bps``.

        Args:
            aggregate: Object with at least an ``avg_slippage_bps`` attribute.
        """
        avg = getattr(aggregate, "avg_slippage_bps", None)
        if avg is not None:
            self._slippage_samples_bps.append(float(avg))

    # ── Computation ───────────────────────────────────────────────────────────

    def compute(self) -> MetricsResult:
        """Compute all metrics from accumulated data.

        Returns:
            MetricsResult with all computed metrics and GO-LIVE gate result.
        """
        ev_capture_ratio = self._compute_ev_capture()
        fill_rate = self._compute_fill_rate()
        p95_latency = self._compute_p95_latency()
        drawdown = self._compute_max_drawdown()
        # Phase 10.2 execution quality metrics
        avg_slippage_bps = self._compute_avg_slippage()
        p95_slippage_bps = self._compute_p95_slippage()
        worst_slippage_bps = self._compute_worst_slippage()
        fill_accuracy = self._compute_fill_accuracy()
        execution_success_rate = fill_rate  # mirrors fill_rate unless separate data

        gate_details = {
            "ev_capture_ratio": {
                "value": round(ev_capture_ratio, 4),
                "target": self._ev_capture_target,
                "passed": ev_capture_ratio >= self._ev_capture_target,
            },
            "fill_rate": {
                "value": round(fill_rate, 4),
                "target": self._fill_rate_target,
                "passed": fill_rate >= self._fill_rate_target,
            },
            "p95_latency_ms": {
                "value": round(p95_latency, 2),
                "target": self._p95_latency_target,
                "passed": p95_latency <= self._p95_latency_target,
            },
            "max_drawdown": {
                "value": round(drawdown, 4),
                "target": self._max_drawdown_target,
                "passed": drawdown <= self._max_drawdown_target,
            },
            "min_trades": {
                "value": self._orders_filled,
                "target": self._min_trades,
                "passed": self._orders_filled >= self._min_trades,
            },
        }

        # Min trades guard: insufficient data overrides all other gates
        if self._orders_filled < self._min_trades:
            gate_passed = False
            reason = f"insufficient_trades:{self._orders_filled}<{self._min_trades}"
        else:
            gate_passed = all(v["passed"] for v in gate_details.values())
            if gate_passed:
                reason = "all_gates_passed"
            else:
                reason = "unknown_gate_failed"
                # Report the first failing gate (deterministic order from dict)
                for gate_name, detail in gate_details.items():
                    if not detail["passed"]:
                        # Use > for metrics where lower is better (latency, drawdown),
                        # and < for metrics where higher is better (ev_capture, fill_rate, min_trades)
                        higher_is_worse = gate_name in ("p95_latency_ms", "max_drawdown")
                        op = ">" if higher_is_worse else "<"
                        reason = f"{gate_name}_failed:{detail['value']}{op}{detail['target']}"
                        break

        session_duration_s = time.time() - self._session_start
        session_summary = {
            "session_duration_sec": round(session_duration_s, 1),
            "orders_submitted": self._orders_submitted,
            "orders_filled": self._orders_filled,
            "signals_evaluated": len(self._expected_ev_samples),
            "total_expected_ev": round(sum(self._expected_ev_samples), 4),
            "total_actual_ev": round(sum(self._actual_ev_samples), 4),
            "latency_samples": len(self._latency_samples_ms),
            "pnl_snapshots": len(self._pnl_timeline),
            "final_cumulative_pnl": round(self._pnl_timeline[-1], 2) if self._pnl_timeline else 0.0,
            "slippage_samples": len(self._slippage_samples_bps),
        }

        result = MetricsResult(
            ev_capture_ratio=round(ev_capture_ratio, 4),
            fill_rate=round(fill_rate, 4),
            p95_latency=round(p95_latency, 2),
            drawdown=round(drawdown, 4),
            total_trades=self._orders_filled,
            pass_result=gate_passed,
            go_live_ready=gate_passed,
            reason=reason,
            gate_details=gate_details,
            session_summary=session_summary,
            fill_accuracy=round(fill_accuracy, 4),
            avg_slippage_bps=round(avg_slippage_bps, 2),
            p95_slippage_bps=round(p95_slippage_bps, 2),
            worst_slippage_bps=round(worst_slippage_bps, 2),
            execution_success_rate=round(execution_success_rate, 4),
        )

        log.info(
            "metrics_computed",
            ev_capture_ratio=result.ev_capture_ratio,
            fill_rate=result.fill_rate,
            p95_latency_ms=result.p95_latency,
            max_drawdown=result.drawdown,
            total_trades=result.total_trades,
            pass_result=gate_passed,
            reason=reason,
            avg_slippage_bps=result.avg_slippage_bps,
            p95_slippage_bps=result.p95_slippage_bps,
            worst_slippage_bps=result.worst_slippage_bps,
            fill_accuracy=result.fill_accuracy,
            execution_success_rate=result.execution_success_rate,
        )

        return result

    def write(self, result: MetricsResult, output_path: Optional[str] = None) -> str:
        """Write metrics to JSON file.

        Args:
            result: MetricsResult from compute().
            output_path: Override default output file path.

        Returns:
            Absolute path of the written file.
        """
        path = output_path or self._output_file

        payload = {
            "ev_capture_ratio": result.ev_capture_ratio,
            "fill_rate": result.fill_rate,
            "p95_latency": result.p95_latency,
            "drawdown": result.drawdown,
            "total_trades": result.total_trades,
            "fill_accuracy": result.fill_accuracy,
            "avg_slippage_bps": result.avg_slippage_bps,
            "p95_slippage_bps": result.p95_slippage_bps,
            "worst_slippage_bps": result.worst_slippage_bps,
            "execution_success_rate": result.execution_success_rate,
            "pass": result.pass_result,
            "reason": result.reason,
            "gate_details": result.gate_details,
            "session_summary": result.session_summary,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            log.info("metrics_written", path=os.path.abspath(path))
        except OSError as exc:
            log.error("metrics_write_failed", path=path, error=str(exc))

        return os.path.abspath(path)

    def gate_check(self, result: MetricsResult) -> bool:
        """Evaluate GO-LIVE gate. Logs pass/fail for each metric.

        Args:
            result: MetricsResult from compute().

        Returns:
            True if ALL gate criteria are satisfied.
        """
        log.info(
            "go_live_gate_check",
            pass_result=result.pass_result,
            go_live_ready=result.go_live_ready,
            reason=result.reason,
            ev_capture_ratio=result.ev_capture_ratio,
            ev_target=self._ev_capture_target,
            fill_rate=result.fill_rate,
            fill_target=self._fill_rate_target,
            p95_latency_ms=result.p95_latency,
            latency_target=self._p95_latency_target,
            max_drawdown=result.drawdown,
            drawdown_target=self._max_drawdown_target,
            total_trades=result.total_trades,
            min_trades=self._min_trades,
        )

        for metric, detail in result.gate_details.items():
            level = "info" if detail["passed"] else "warning"
            getattr(log, level)(
                "go_live_gate_metric",
                metric=metric,
                value=detail["value"],
                target=detail["target"],
                passed=detail["passed"],
            )

        if result.pass_result:
            log.info("go_live_gate_PASSED — system ready for live trading")
        else:
            log.warning("go_live_gate_FAILED — do not proceed to live trading")

        return result.pass_result

    # ── Internal computation helpers ──────────────────────────────────────────

    def _compute_ev_capture(self) -> float:
        """Compute EV capture ratio = sum(actual_ev) / sum(expected_ev).

        Returns 0.0 if no signals were evaluated.
        Returns 1.0 if expected EV is effectively zero (safe default).
        """
        total_expected = sum(self._expected_ev_samples)
        total_actual = sum(self._actual_ev_samples)

        if total_expected <= 1e-9:
            return 1.0 if total_actual >= 0 else 0.0

        return max(0.0, min(total_actual / total_expected, 2.0))

    def _compute_fill_rate(self) -> float:
        """Compute fill rate = filled / submitted.

        Returns 1.0 if no orders were submitted (neutral default).
        """
        if self._orders_submitted == 0:
            return 1.0
        return self._orders_filled / self._orders_submitted

    def _compute_p95_latency(self) -> float:
        """Compute p95 latency from latency_samples_ms.

        Returns 0.0 if no samples recorded.
        """
        if not self._latency_samples_ms:
            return 0.0

        sorted_samples = sorted(self._latency_samples_ms)
        # Nearest-rank method: ceil(0.95 * N) - 1 gives the correct p95 index.
        # Using int() (floor) underestimates p95 for sample sizes where 0.95*N
        # is not an integer (e.g. N=10: int(9.5)-1=8 → index 8 (9th element, p90)
        # vs ceil(9.5)-1=9 → index 9 (10th element, true p95)).
        idx = max(0, math.ceil(len(sorted_samples) * 0.95) - 1)
        return sorted_samples[idx]

    def _compute_max_drawdown(self) -> float:
        """Compute maximum peak-to-trough drawdown from PnL timeline.

        Drawdown expressed as a fraction of peak PnL above zero.
        Returns 0.0 if no PnL data or no drawdown occurred.
        """
        if len(self._pnl_timeline) < 2:
            return 0.0

        peak = 0.0
        max_dd = 0.0

        for pnl in self._pnl_timeline:
            if pnl > peak:
                peak = pnl
            if peak > 0:
                dd = (peak - pnl) / peak
                max_dd = max(max_dd, dd)

        return max(0.0, max_dd)

    # ── Phase 10.2: Execution quality helpers ─────────────────────────────────

    def _compute_avg_slippage(self) -> float:
        """Compute average slippage across all recorded samples.

        Returns 0.0 if no slippage samples recorded.
        """
        if not self._slippage_samples_bps:
            return 0.0
        return sum(self._slippage_samples_bps) / len(self._slippage_samples_bps)

    def _compute_p95_slippage(self) -> float:
        """Compute 95th-percentile slippage using nearest-rank method.

        Returns 0.0 if no slippage samples recorded.
        """
        if not self._slippage_samples_bps:
            return 0.0
        sorted_samples = sorted(self._slippage_samples_bps)
        idx = max(0, math.ceil(len(sorted_samples) * 0.95) - 1)
        return sorted_samples[idx]

    def _compute_worst_slippage(self) -> float:
        """Compute worst (largest absolute) slippage observed.

        Returns 0.0 if no slippage samples recorded.
        """
        if not self._slippage_samples_bps:
            return 0.0
        return max(abs(s) for s in self._slippage_samples_bps)

    def _compute_fill_accuracy(self) -> float:
        """Compute fraction of fills within the slippage threshold.

        Returns 1.0 if no slippage samples recorded (no data = no violation).
        """
        if not self._slippage_samples_bps:
            return 1.0
        within = sum(
            1 for s in self._slippage_samples_bps
            if abs(s) <= self._slippage_threshold_bps
        )
        return within / len(self._slippage_samples_bps)
