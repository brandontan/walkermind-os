"""Phase 10 — GoLiveController: Controlled LIVE mode gating.

Manages the PAPER → LIVE mode transition by enforcing a strict set of
GO-LIVE conditions derived from the MetricsValidator output.  All execution
calls must flow through :meth:`GoLiveController.allow_execution` before
being dispatched to the live executor.

Mode toggle::

    PAPER — orders logged but never sent to the exchange.
    LIVE  — orders dispatched to the exchange after all guards pass.

GO-LIVE conditions (all must pass)::

    ev_capture_ratio  >= 0.75   (configurable)
    fill_rate         >= 0.60   (configurable)
    p95_latency_ms    <= 500    (configurable)
    drawdown          <= 0.08   (configurable)

Capital controls::

    max_capital_usd      — hard cap on total capital allocated.
    max_trades_per_day   — maximum number of trades per UTC day.

Usage::

    controller = GoLiveController.from_config(config)
    # After paper run:
    metrics = validator.compute()
    controller.set_metrics(metrics)
    if controller.allow_execution():
        await executor.execute(request)

Thread-safety: single asyncio event loop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Mode enum ─────────────────────────────────────────────────────────────────


class TradingMode(str, Enum):
    """Execution mode."""

    PAPER = "PAPER"
    LIVE = "LIVE"


# ── GO-LIVE thresholds ────────────────────────────────────────────────────────


@dataclass
class GoLiveThresholds:
    """Configurable GO-LIVE gate thresholds."""

    ev_capture_min: float = 0.75
    fill_rate_min: float = 0.60
    p95_latency_max_ms: float = 500.0
    drawdown_max: float = 0.08


# ── GoLiveController ──────────────────────────────────────────────────────────


class GoLiveController:
    """Controls the PAPER/LIVE mode toggle and enforces GO-LIVE conditions.

    Execution is allowed only when:
      - mode is explicitly set to LIVE *and*
      - all GO-LIVE metric thresholds are satisfied *and*
      - capital / trade-count caps have not been exhausted.

    When any condition fails the call returns ``False`` and the reason is
    logged at WARNING level so callers can react without silent failures.
    """

    def __init__(
        self,
        mode: TradingMode = TradingMode.PAPER,
        thresholds: Optional[GoLiveThresholds] = None,
        max_capital_usd: float = 10_000.0,
        max_trades_per_day: int = 200,
    ) -> None:
        """Initialise the controller.

        Args:
            mode: Initial trading mode (default PAPER).
            thresholds: GO-LIVE gate thresholds.
            max_capital_usd: Maximum capital that may be deployed per day.
            max_trades_per_day: Maximum number of trade executions per UTC day.
        """
        self._mode = mode
        self._thresholds = thresholds or GoLiveThresholds()
        self._max_capital_usd = max_capital_usd
        self._max_trades_per_day = max_trades_per_day

        # Metrics set by set_metrics()
        self._ev_capture_ratio: Optional[float] = None
        self._fill_rate: Optional[float] = None
        self._p95_latency_ms: Optional[float] = None
        self._drawdown: Optional[float] = None
        self._metrics_ready: bool = False

        # Capital / trade counters — reset on UTC day rollover
        self._capital_deployed_usd: float = 0.0
        self._trades_today: int = 0
        self._day_epoch: int = self._utc_day()

        log.info(
            "go_live_controller_initialized",
            mode=mode.value,
            max_capital_usd=max_capital_usd,
            max_trades_per_day=max_trades_per_day,
            ev_capture_min=self._thresholds.ev_capture_min,
            fill_rate_min=self._thresholds.fill_rate_min,
            p95_latency_max_ms=self._thresholds.p95_latency_max_ms,
            drawdown_max=self._thresholds.drawdown_max,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: dict) -> "GoLiveController":
        """Build from configuration dict.

        Args:
            config: Top-level config dict.  Reads ``go_live`` sub-key.

        Returns:
            Configured GoLiveController.
        """
        cfg = config.get("go_live", {})
        raw_mode = str(cfg.get("mode", "PAPER")).upper()
        try:
            mode = TradingMode(raw_mode)
        except ValueError:
            log.warning(
                "go_live_controller_invalid_mode",
                raw_mode=raw_mode,
                fallback="PAPER",
            )
            mode = TradingMode.PAPER

        thresholds = GoLiveThresholds(
            ev_capture_min=float(cfg.get("ev_capture_min", 0.75)),
            fill_rate_min=float(cfg.get("fill_rate_min", 0.60)),
            p95_latency_max_ms=float(cfg.get("p95_latency_max_ms", 500.0)),
            drawdown_max=float(cfg.get("drawdown_max", 0.08)),
        )

        return cls(
            mode=mode,
            thresholds=thresholds,
            max_capital_usd=float(cfg.get("max_capital_usd", 10_000.0)),
            max_trades_per_day=int(cfg.get("max_trades_per_day", 200)),
        )

    # ── Mode control ──────────────────────────────────────────────────────────

    @property
    def mode(self) -> TradingMode:
        """Current trading mode."""
        return self._mode

    def set_mode(self, mode: TradingMode) -> None:
        """Explicitly set the trading mode.

        Args:
            mode: New trading mode.
        """
        prev = self._mode
        self._mode = mode
        log.info(
            "go_live_controller_mode_changed",
            previous=prev.value,
            current=mode.value,
        )

    # ── Metrics ingestion ─────────────────────────────────────────────────────

    def set_metrics(self, metrics: object) -> None:
        """Ingest a MetricsResult produced by MetricsValidator.compute().

        The controller reads ``ev_capture_ratio``, ``fill_rate``,
        ``p95_latency``, and ``drawdown`` directly from the object.

        Args:
            metrics: MetricsResult instance (or any duck-typed equivalent with
                     the same attributes).
        """
        self._ev_capture_ratio = float(getattr(metrics, "ev_capture_ratio", 0.0))
        self._fill_rate = float(getattr(metrics, "fill_rate", 0.0))
        self._p95_latency_ms = float(getattr(metrics, "p95_latency", 9999.0))
        self._drawdown = float(getattr(metrics, "drawdown", 1.0))
        self._metrics_ready = True

        log.info(
            "go_live_controller_metrics_ingested",
            ev_capture_ratio=self._ev_capture_ratio,
            fill_rate=self._fill_rate,
            p95_latency_ms=self._p95_latency_ms,
            drawdown=self._drawdown,
        )

    # ── Execution gate ────────────────────────────────────────────────────────

    def allow_execution(self, trade_size_usd: float = 0.0) -> bool:
        """Return True if a trade execution is currently permitted.

        Checks (in order):
          1. Mode must be LIVE.
          2. Metrics must be available.
          3. All GO-LIVE metric thresholds must be satisfied.
          4. Daily trade cap must not be exhausted.
          5. Capital cap must not be exhausted.

        Args:
            trade_size_usd: Estimated USD size of the trade (used for capital
                            cap check).

        Returns:
            True if all conditions pass, False otherwise.
        """
        self._roll_day_counters()

        if self._mode is TradingMode.PAPER:
            log.debug("go_live_controller_blocked_paper_mode")
            return False

        if not self._metrics_ready:
            log.warning(
                "go_live_controller_blocked_no_metrics",
                reason="metrics_not_set",
            )
            return False

        # ── Metric gates ─────────────────────────────────────────────────────
        # Safety: metrics_ready guard above ensures these are never None here.
        if self._ev_capture_ratio is None or self._fill_rate is None or \
                self._p95_latency_ms is None or self._drawdown is None:
            log.error("go_live_controller_metrics_state_inconsistent")
            return False

        if self._ev_capture_ratio < self._thresholds.ev_capture_min:
            log.warning(
                "go_live_controller_blocked",
                reason="ev_capture_below_threshold",
                value=self._ev_capture_ratio,
                threshold=self._thresholds.ev_capture_min,
            )
            return False

        if self._fill_rate < self._thresholds.fill_rate_min:
            log.warning(
                "go_live_controller_blocked",
                reason="fill_rate_below_threshold",
                value=self._fill_rate,
                threshold=self._thresholds.fill_rate_min,
            )
            return False

        if self._p95_latency_ms > self._thresholds.p95_latency_max_ms:
            log.warning(
                "go_live_controller_blocked",
                reason="p95_latency_exceeded",
                value=self._p95_latency_ms,
                threshold=self._thresholds.p95_latency_max_ms,
            )
            return False

        if self._drawdown > self._thresholds.drawdown_max:
            log.warning(
                "go_live_controller_blocked",
                reason="drawdown_exceeded",
                value=self._drawdown,
                threshold=self._thresholds.drawdown_max,
            )
            return False

        # ── Capital / trade-count caps ────────────────────────────────────────
        if self._trades_today >= self._max_trades_per_day:
            log.warning(
                "go_live_controller_blocked",
                reason="daily_trade_cap_reached",
                trades_today=self._trades_today,
                cap=self._max_trades_per_day,
            )
            return False

        projected_capital = self._capital_deployed_usd + trade_size_usd
        if trade_size_usd > 0 and projected_capital > self._max_capital_usd:
            log.warning(
                "go_live_controller_blocked",
                reason="capital_cap_reached",
                capital_deployed=self._capital_deployed_usd,
                trade_size=trade_size_usd,
                cap=self._max_capital_usd,
            )
            return False

        log.debug(
            "go_live_controller_execution_allowed",
            mode=self._mode.value,
            trades_today=self._trades_today,
            capital_deployed=self._capital_deployed_usd,
        )
        return True

    def record_trade(self, size_usd: float = 0.0) -> None:
        """Record a completed trade against the daily counters.

        Must be called after each trade execution to track caps.

        Args:
            size_usd: USD size of the executed trade.
        """
        self._roll_day_counters()
        self._trades_today += 1
        if size_usd > 0:
            self._capital_deployed_usd += size_usd
        log.debug(
            "go_live_controller_trade_recorded",
            trades_today=self._trades_today,
            capital_deployed=self._capital_deployed_usd,
        )

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return structured status snapshot for health monitoring."""
        self._roll_day_counters()
        return {
            "mode": self._mode.value,
            "metrics_ready": self._metrics_ready,
            "ev_capture_ratio": self._ev_capture_ratio,
            "fill_rate": self._fill_rate,
            "p95_latency_ms": self._p95_latency_ms,
            "drawdown": self._drawdown,
            "trades_today": self._trades_today,
            "capital_deployed_usd": self._capital_deployed_usd,
            "max_capital_usd": self._max_capital_usd,
            "max_trades_per_day": self._max_trades_per_day,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _utc_day() -> int:
        """Return today's UTC day-of-epoch integer (seconds // 86400)."""
        return int(time.time()) // 86400

    def _roll_day_counters(self) -> None:
        """Reset daily counters when the UTC day changes."""
        today = self._utc_day()
        if today != self._day_epoch:
            log.info(
                "go_live_controller_daily_counters_reset",
                previous_day=self._day_epoch,
                new_day=today,
                previous_trades=self._trades_today,
                previous_capital=self._capital_deployed_usd,
            )
            self._day_epoch = today
            self._trades_today = 0
            self._capital_deployed_usd = 0.0
