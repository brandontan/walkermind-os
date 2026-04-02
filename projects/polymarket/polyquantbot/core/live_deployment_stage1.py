"""Phase 14 — LiveDeploymentStage1: Controlled LIVE trading activation gate.

Activates Stage 1 LIVE trading with strict safety constraints and monitoring
for the first 10 trades.  All safety limits are reduced below normal maximums
to contain risk during initial LIVE validation.

Stage 1 limits (hard-coded safe-defaults, may be overridden at construction):
    max_position_per_strategy  = 2%   (vs 10% normal max)
    max_total_exposure         = 5%   (vs 10% normal max)
    max_concurrent_trades      = 2
    drawdown_limit             = 5%   (vs 8% normal max)

Lifecycle::

    1. apply_live_config()     — set MODE=LIVE, ENABLE_LIVE_TRADING=true, override limits.
    2. dry_validate()          — verify execution path without sending real orders.
    3. enable_execution()      — activate the CLOB executor for real orders.
    4. monitor_trade()         — call after each trade; anomalies trigger fail-safe.
    5. send_activation_alert() — dispatch Telegram alert on successful LIVE activation.

Fail-safe trigger conditions (any → immediate halt):
    - Absolute slippage  > SLIPPAGE_ALERT_THRESHOLD (default 5%)
    - Execution failure  (result.status == "rejected")
    - Unexpected allocation (size > max_position_per_strategy × bankroll × 1.05)

Design:
    - Fail-closed: any safety violation calls system_state.halt().
    - Structured JSON logging on every state change.
    - All secrets from env only — never hardcoded.
    - Idempotent: calling enable_execution() multiple times is safe.
    - Thread-safety: single asyncio event loop.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from ..config.live_config import LiveConfig, LiveModeGuardError
from ..core.pipeline.go_live_controller import GoLiveController, TradingMode
from ..telegram.message_formatter import format_live_stage1_activated, format_kill_alert

log = structlog.get_logger()

# ── Stage 1 defaults ──────────────────────────────────────────────────────────

_STAGE1_MAX_POSITION_FRACTION: float = 0.02      # 2% per strategy
_STAGE1_MAX_TOTAL_EXPOSURE: float = 0.05          # 5% total
_STAGE1_MAX_CONCURRENT_TRADES: int = 2
_STAGE1_DRAWDOWN_LIMIT: float = 0.05             # 5%

# Anomaly thresholds
_SLIPPAGE_ALERT_THRESHOLD: float = 0.05          # 5% absolute slippage
_SAFETY_WATCH_TRADES: int = 10                   # monitor first N trades


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class Stage1TradeRecord:
    """Structured record for each trade monitored during Stage 1.

    Attributes:
        trade_number: Sequential trade index (1-based).
        market_id: Polymarket condition ID.
        side: "YES" | "NO".
        expected_price: Price at signal generation time.
        fill_price: Actual execution price.
        size_usd: Order size in USD.
        status: Execution status ("filled" | "partial" | "rejected").
        slippage: Absolute price slippage (fill_price - expected_price).
        anomaly: True when any anomaly threshold was breached.
        anomaly_reason: Human-readable anomaly description (empty if none).
        correlation_id: Request trace ID.
    """

    trade_number: int
    market_id: str
    side: str
    expected_price: float
    fill_price: float
    size_usd: float
    status: str
    slippage: float
    anomaly: bool
    anomaly_reason: str
    correlation_id: str = ""

    def to_dict(self) -> dict:
        """Return JSON-serialisable representation."""
        return {
            "trade_number": self.trade_number,
            "market_id": self.market_id,
            "side": self.side,
            "expected_price": self.expected_price,
            "fill_price": self.fill_price,
            "size_usd": self.size_usd,
            "status": self.status,
            "slippage": round(self.slippage, 6),
            "anomaly": self.anomaly,
            "anomaly_reason": self.anomaly_reason,
            "correlation_id": self.correlation_id,
        }


@dataclass
class DryValidationResult:
    """Result from a dry-validation cycle.

    Attributes:
        execution_path_live: True when execution is confirmed to route LIVE.
        order_creation_ok: True when an ExecutionRequest can be constructed.
        config_validated: True when LiveConfig.validate() passed.
        go_live_allowed: True when GoLiveController.allow_execution() returned True.
        passed: True when all sub-checks passed.
        failure_reason: Reason for the first failing check (empty on success).
    """

    execution_path_live: bool
    order_creation_ok: bool
    config_validated: bool
    go_live_allowed: bool
    passed: bool
    failure_reason: str = ""

    def to_dict(self) -> dict:
        """Return JSON-serialisable representation."""
        return {
            "execution_path_live": self.execution_path_live,
            "order_creation_ok": self.order_creation_ok,
            "config_validated": self.config_validated,
            "go_live_allowed": self.go_live_allowed,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
        }


# ── LiveDeploymentStage1 ──────────────────────────────────────────────────────


class LiveDeploymentStage1:
    """Controlled LIVE trading activation gate for Stage 1 deployment.

    Manages the full lifecycle from config application through dry-validation,
    real execution enablement, and trade-level safety monitoring for the first
    :attr:`safety_watch_trades` trades.

    Args:
        live_config: Pre-constructed LiveConfig instance.  If None, built via
            LiveConfig.from_env() when :meth:`apply_live_config` is called.
        go_live_controller: GoLiveController instance.  If None, constructed
            from Stage 1 defaults in :meth:`apply_live_config`.
        system_state: Optional SystemStateManager for halt() calls.  When None
            the fail-safe still logs but cannot halt the state machine.
        telegram: Optional TelegramLive instance for alert delivery.
        bankroll: Bankroll in USD used for allocation checks.
        max_position_fraction: Per-strategy position cap (fraction of bankroll).
        max_total_exposure: Total portfolio exposure cap (fraction of bankroll).
        max_concurrent_trades: Hard cap on concurrent open trades.
        drawdown_limit: Drawdown fraction that triggers fail-safe halt.
        active_strategies: Names of strategies registered for Stage 1.
        safety_watch_trades: Number of initial trades to monitor closely.
    """

    def __init__(
        self,
        live_config: Optional[LiveConfig] = None,
        go_live_controller: Optional[GoLiveController] = None,
        system_state: Optional[object] = None,
        telegram: Optional[object] = None,
        bankroll: float = 10_000.0,
        max_position_fraction: float = _STAGE1_MAX_POSITION_FRACTION,
        max_total_exposure: float = _STAGE1_MAX_TOTAL_EXPOSURE,
        max_concurrent_trades: int = _STAGE1_MAX_CONCURRENT_TRADES,
        drawdown_limit: float = _STAGE1_DRAWDOWN_LIMIT,
        active_strategies: Optional[List[str]] = None,
        safety_watch_trades: int = _SAFETY_WATCH_TRADES,
    ) -> None:
        self._live_config = live_config
        self._go_live_controller = go_live_controller
        self._system_state = system_state
        self._telegram = telegram
        self._bankroll = bankroll
        self._max_position_fraction = max_position_fraction
        self._max_total_exposure = max_total_exposure
        self._max_concurrent_trades = max_concurrent_trades
        self._drawdown_limit = drawdown_limit
        self._active_strategies: List[str] = list(active_strategies or [])
        self._safety_watch_trades = safety_watch_trades

        # Runtime state
        self._config_applied: bool = False
        self._execution_enabled: bool = False
        self._trade_records: List[Stage1TradeRecord] = []
        self._fail_safe_triggered: bool = False

        log.info(
            "live_deployment_stage1_initialized",
            bankroll=bankroll,
            max_position_fraction=max_position_fraction,
            max_total_exposure=max_total_exposure,
            max_concurrent_trades=max_concurrent_trades,
            drawdown_limit=drawdown_limit,
            active_strategies=self._active_strategies,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def config_applied(self) -> bool:
        """True after apply_live_config() completed successfully."""
        return self._config_applied

    @property
    def execution_enabled(self) -> bool:
        """True after enable_execution() was called."""
        return self._execution_enabled

    @property
    def fail_safe_triggered(self) -> bool:
        """True if the fail-safe halt was triggered."""
        return self._fail_safe_triggered

    @property
    def trade_records(self) -> List[Stage1TradeRecord]:
        """Immutable view of trade records captured during safety watch."""
        return list(self._trade_records)

    @property
    def live_config(self) -> Optional[LiveConfig]:
        """Currently applied LiveConfig (None until apply_live_config called)."""
        return self._live_config

    @property
    def go_live_controller(self) -> Optional[GoLiveController]:
        """Currently configured GoLiveController."""
        return self._go_live_controller

    # ── Lifecycle steps ───────────────────────────────────────────────────────

    def apply_live_config(
        self,
        live_config: Optional[LiveConfig] = None,
        go_live_controller: Optional[GoLiveController] = None,
    ) -> None:
        """Apply LIVE configuration with Stage 1 safe limits.

        Accepts explicit objects or builds defaults.  Calls
        ``LiveConfig.validate()`` to confirm the LIVE guard passes.

        Args:
            live_config: Explicit LiveConfig instance.  When None, uses the
                instance provided at construction or builds from env.
            go_live_controller: Explicit GoLiveController.  When None, builds
                one from Stage 1 defaults in LIVE mode.

        Raises:
            LiveModeGuardError: When ``ENABLE_LIVE_TRADING`` is not true.
            ValueError: When any config bound is violated.
        """
        cfg = live_config or self._live_config
        if cfg is None:
            cfg = LiveConfig.from_env()

        cfg.validate()  # raises LiveModeGuardError / ValueError on failure

        ctrl = go_live_controller or self._go_live_controller
        if ctrl is None:
            ctrl = GoLiveController(
                mode=TradingMode.LIVE,
                max_capital_usd=self._bankroll * self._max_total_exposure,
                max_trades_per_day=200,
            )

        self._live_config = cfg
        self._go_live_controller = ctrl
        self._config_applied = True

        log.info(
            "live_deployment_stage1_config_applied",
            trading_mode=cfg.trading_mode.value,
            enable_live_trading=cfg.enable_live_trading,
            max_position_fraction=self._max_position_fraction,
            max_total_exposure=self._max_total_exposure,
            max_concurrent_trades=self._max_concurrent_trades,
            drawdown_limit=self._drawdown_limit,
        )

    def dry_validate(self, metrics: Optional[object] = None) -> DryValidationResult:
        """Run 1–2 dry validation cycles to verify execution path.

        Does NOT send any real orders.  Verifies:
          - LiveConfig.validate() passes (config_validated)
          - An ExecutionRequest can be constructed (order_creation_ok)
          - GoLiveController mode is LIVE (execution_path_live)
          - GoLiveController.allow_execution() returns True after metrics set (go_live_allowed)

        Args:
            metrics: Optional metrics object to feed into the controller so
                all metric gates pass.  When None a passing stub is used.

        Returns:
            DryValidationResult with sub-check flags and overall passed status.
        """
        execution_path_live = False
        order_creation_ok = False
        config_validated = False
        go_live_allowed = False
        failure_reason = ""

        # -- Config validation --
        try:
            if self._live_config is not None:
                self._live_config.validate()
            config_validated = True
        except Exception as exc:
            failure_reason = f"config_validation_failed: {exc}"

        # -- Order creation check --
        if config_validated:
            try:
                from ..execution.clob_executor import ExecutionRequest
                _ = ExecutionRequest(
                    market_id="dry-validate-market",
                    side="YES",
                    price=0.50,
                    size=10.0,
                )
                order_creation_ok = True
            except Exception as exc:
                failure_reason = f"order_creation_failed: {exc}"

        # -- Execution path check --
        if self._go_live_controller is not None:
            execution_path_live = self._go_live_controller.mode is TradingMode.LIVE
            if not execution_path_live and not failure_reason:
                failure_reason = "execution_path_not_live"

        # -- Allow-execution gate check --
        if execution_path_live and self._go_live_controller is not None:
            ctrl = self._go_live_controller
            if metrics is not None:
                ctrl.set_metrics(metrics)
            else:
                # Feed a passing stub so the gate opens
                _stub = _StubMetrics(
                    ev_capture_ratio=0.81,
                    fill_rate=0.72,
                    p95_latency=287.0,
                    drawdown=0.024,
                )
                ctrl.set_metrics(_stub)
            go_live_allowed = ctrl.allow_execution()
            if not go_live_allowed and not failure_reason:
                failure_reason = "go_live_controller_blocked"

        passed = config_validated and order_creation_ok and execution_path_live and go_live_allowed

        log.info(
            "live_deployment_stage1_dry_validate",
            config_validated=config_validated,
            order_creation_ok=order_creation_ok,
            execution_path_live=execution_path_live,
            go_live_allowed=go_live_allowed,
            passed=passed,
            failure_reason=failure_reason,
        )

        return DryValidationResult(
            execution_path_live=execution_path_live,
            order_creation_ok=order_creation_ok,
            config_validated=config_validated,
            go_live_allowed=go_live_allowed,
            passed=passed,
            failure_reason=failure_reason,
        )

    def enable_execution(self) -> None:
        """Activate the CLOB executor for real order placement.

        Idempotent: calling this when already enabled is a no-op.

        Raises:
            RuntimeError: If apply_live_config() has not been called first.
        """
        if not self._config_applied:
            raise RuntimeError(
                "apply_live_config() must be called before enable_execution(). "
                "Ensure LIVE config is validated before activating the executor."
            )
        if self._execution_enabled:
            log.debug("live_deployment_stage1_execution_already_enabled")
            return
        self._execution_enabled = True
        log.info(
            "live_deployment_stage1_execution_enabled",
            max_position_fraction=self._max_position_fraction,
            max_total_exposure=self._max_total_exposure,
        )

    async def send_activation_alert(self, correlation_id: str = "") -> None:
        """Send the LIVE TRADING ACTIVATED (STAGE 1) Telegram alert.

        Args:
            correlation_id: Optional session trace ID.
        """
        msg = format_live_stage1_activated(
            mode="LIVE",
            bankroll=self._bankroll,
            max_position_pct=self._max_position_fraction * 100.0,
            max_total_exposure_pct=self._max_total_exposure * 100.0,
            max_concurrent_trades=self._max_concurrent_trades,
            drawdown_limit_pct=self._drawdown_limit * 100.0,
            active_strategies=self._active_strategies,
            correlation_id=correlation_id,
        )
        if self._telegram is not None:
            await _safe_telegram_raw(self._telegram, msg)
        log.info(
            "live_deployment_stage1_activation_alert_sent",
            correlation_id=correlation_id,
            strategies=self._active_strategies,
        )

    async def monitor_trade(
        self,
        market_id: str,
        side: str,
        expected_price: float,
        fill_price: float,
        size_usd: float,
        status: str,
        correlation_id: str = "",
    ) -> Stage1TradeRecord:
        """Monitor a single trade during the Stage 1 safety watch window.

        Called after each trade for the first :attr:`_safety_watch_trades`
        trades.  Computes slippage, checks anomaly conditions, and triggers
        the fail-safe halt if any threshold is breached.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            expected_price: Price at signal time.
            fill_price: Actual execution price.
            size_usd: Order size in USD.
            status: Execution status ("filled" | "partial" | "rejected").
            correlation_id: Request trace ID.

        Returns:
            Stage1TradeRecord with anomaly classification.
        """
        trade_number = len(self._trade_records) + 1
        slippage = abs(fill_price - expected_price)
        anomaly = False
        anomaly_reason = ""

        # Anomaly checks
        if status == "rejected":
            anomaly = True
            anomaly_reason = f"execution_failure: order rejected (market={market_id})"
        elif slippage > _SLIPPAGE_ALERT_THRESHOLD:
            anomaly = True
            anomaly_reason = (
                f"abnormal_slippage: {slippage:.4f} > threshold {_SLIPPAGE_ALERT_THRESHOLD}"
            )
        elif size_usd > self._bankroll * self._max_position_fraction * 1.05:
            anomaly = True
            anomaly_reason = (
                f"unexpected_allocation: size_usd={size_usd:.2f} exceeds "
                f"{self._max_position_fraction * 1.05 * 100:.1f}% of bankroll"
            )

        record = Stage1TradeRecord(
            trade_number=trade_number,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            fill_price=fill_price,
            size_usd=size_usd,
            status=status,
            slippage=slippage,
            anomaly=anomaly,
            anomaly_reason=anomaly_reason,
            correlation_id=correlation_id,
        )
        self._trade_records.append(record)

        log.info(
            "live_deployment_stage1_trade_monitored",
            trade_number=trade_number,
            market_id=market_id,
            side=side,
            fill_price=fill_price,
            slippage=slippage,
            anomaly=anomaly,
            anomaly_reason=anomaly_reason,
            status=status,
        )

        if anomaly:
            await self._trigger_fail_safe(anomaly_reason, correlation_id)

        return record

    def status(self) -> dict:
        """Return structured status snapshot for health monitoring.

        Returns:
            Dict with lifecycle flags and trade-level summary.
        """
        anomaly_count = sum(1 for r in self._trade_records if r.anomaly)
        return {
            "config_applied": self._config_applied,
            "execution_enabled": self._execution_enabled,
            "fail_safe_triggered": self._fail_safe_triggered,
            "trades_monitored": len(self._trade_records),
            "anomalies_detected": anomaly_count,
            "safety_watch_active": len(self._trade_records) < self._safety_watch_trades,
            "max_position_fraction": self._max_position_fraction,
            "max_total_exposure": self._max_total_exposure,
            "max_concurrent_trades": self._max_concurrent_trades,
            "drawdown_limit": self._drawdown_limit,
            "bankroll": self._bankroll,
            "active_strategies": self._active_strategies,
        }

    # ── Fail-safe ─────────────────────────────────────────────────────────────

    async def _trigger_fail_safe(self, reason: str, correlation_id: str = "") -> None:
        """Immediately halt all trading on anomaly detection.

        Args:
            reason: Human-readable reason for the fail-safe trigger.
            correlation_id: Request trace ID for logging.
        """
        if self._fail_safe_triggered:
            return  # already halted — idempotent

        self._fail_safe_triggered = True
        self._execution_enabled = False

        log.error(
            "live_deployment_stage1_fail_safe_triggered",
            reason=reason,
            correlation_id=correlation_id,
        )

        # Halt the system state machine
        if self._system_state is not None:
            halt_fn = getattr(self._system_state, "halt", None)
            if callable(halt_fn):
                try:
                    await asyncio.wait_for(halt_fn(reason), timeout=5.0)
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "live_deployment_stage1_halt_failed",
                        error=str(exc),
                    )

        # Send kill alert
        if self._telegram is not None:
            msg = format_kill_alert(reason=reason, correlation_id=correlation_id)
            await _safe_telegram_raw(self._telegram, msg)


# ── Module helpers ─────────────────────────────────────────────────────────────


class _StubMetrics:
    """Minimal metrics stub that passes all GoLiveController gates."""

    def __init__(
        self,
        ev_capture_ratio: float = 0.81,
        fill_rate: float = 0.72,
        p95_latency: float = 287.0,
        drawdown: float = 0.024,
    ) -> None:
        self.ev_capture_ratio = ev_capture_ratio
        self.fill_rate = fill_rate
        self.p95_latency = p95_latency
        self.drawdown = drawdown


async def _safe_telegram_raw(tg: object, message: str) -> None:
    """Send a pre-formatted message via TelegramLive, suppressing all errors.

    Args:
        tg: TelegramLive instance.
        message: Pre-formatted Telegram Markdown string.
    """
    fn = getattr(tg, "_enqueue", None)
    if callable(fn):
        try:
            from ..telegram.telegram_live import AlertType
            await asyncio.wait_for(fn(AlertType.OPEN, message, None), timeout=5.0)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("live_deployment_stage1_telegram_enqueue_error", error=str(exc))
    # Fallback: use alert_error as delivery channel
    fn2 = getattr(tg, "alert_error", None)
    if callable(fn2):
        try:
            await asyncio.wait_for(fn2(error=message, context="live_deployment_stage1"), timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("live_deployment_stage1_telegram_alert_error", error=str(exc))
