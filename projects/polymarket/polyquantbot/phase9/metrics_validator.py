"""Phase 9 — MetricsValidator: Post-run metric computation and GO-LIVE gating.

Computes and validates all trading session metrics after a paper or live run.
Outputs a structured metrics.json for auditing and GO-LIVE decision.

Metrics computed:
    ev_capture_ratio — Fraction of theoretical EV actually captured.
    fill_rate        — Fraction of submitted orders that got filled.
    p95_latency      — 95th percentile execution latency (ms).
    drawdown         — Maximum peak-to-trough PnL drawdown during the session.

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
        reason: Human-readable explanation of pass/fail result.
        gate_details: Per-metric pass/fail details.
        session_summary: Additional session statistics.
    """
    ev_capture_ratio: float
    fill_rate: float
    p95_latency: float
    drawdown: float
    total_trades: int
    pass_result: bool
    reason: str
    gate_details: dict
    session_summary: dict


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
    ) -> None:
        """Initialise the validator.

        Args:
            ev_capture_target: Minimum EV capture ratio for GO-LIVE (default 0.75).
            fill_rate_target: Minimum fill rate for GO-LIVE (default 0.70).
            p95_latency_target_ms: Maximum p95 latency for GO-LIVE (default 500ms).
            max_drawdown_target: Maximum drawdown fraction for GO-LIVE (default 0.08).
            output_file: Path to write metrics.json output.
            min_trades: Minimum filled orders required for GO-LIVE (default 30).
        """
        self._ev_capture_target = ev_capture_target
        self._fill_rate_target = fill_rate_target
        self._p95_latency_target = p95_latency_target_ms
        self._max_drawdown_target = max_drawdown_target
        self._output_file = output_file
        self._min_trades = min_trades

        # Raw data accumulators
        self._expected_ev_samples: list[float] = []    # theoretical EVs per signal
        self._actual_ev_samples: list[float] = []      # actual EVs captured
        self._fill_outcomes: list[bool] = []           # True=filled, False=not
        self._latency_samples_ms: list[float] = []     # execution latency per order
        self._pnl_timeline: list[float] = []           # cumulative PnL over time
        self._orders_submitted: int = 0
        self._orders_filled: int = 0
        self._session_start: float = time.time()

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
        }

        result = MetricsResult(
            ev_capture_ratio=round(ev_capture_ratio, 4),
            fill_rate=round(fill_rate, 4),
            p95_latency=round(p95_latency, 2),
            drawdown=round(drawdown, 4),
            total_trades=self._orders_filled,
            pass_result=gate_passed,
            reason=reason,
            gate_details=gate_details,
            session_summary=session_summary,
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
