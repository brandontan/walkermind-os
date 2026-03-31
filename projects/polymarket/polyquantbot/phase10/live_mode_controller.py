"""Phase 10.6 — LiveModeController: Controlled GO-LIVE activation gate.

Performs a fully stateless, per-execution check against live metrics and
risk state to determine whether LIVE trading is currently permitted.

Unlike GoLiveController (which caches a metrics snapshot), LiveModeController
re-reads all inputs on every call — no cached decision is ever re-used.

GO-LIVE conditions (ALL must pass on every check)::

    ev_capture_ratio  >= 0.75   (configurable)
    fill_rate         >= 0.60   (configurable)
    p95_latency_ms    <= 500    (configurable)
    drawdown          <= 0.08   (configurable)
    kill_switch       == False  (RiskGuard.disabled must be False)

Phase 10.6 infra validation (LIVE mode only)::

    redis_connected   == True   (redis_client provided)
    db_connected      == True   (audit_logger.is_db_connected() == True)
    telegram_ok       == True   (telegram_configured == True)

Failure behaviour::

    Any single failure  → immediate fallback to PAPER (no tolerance)
    kill_switch active  → HARD STOP (no retry, no bypass)
    borderline metrics  → BLOCKED (strict inequality, no tolerance)
    redis missing       → BLOCKED (CriticalExecutionError would follow)
    db missing          → BLOCKED (CriticalAuditError would follow)

Public API::

    controller.is_live_enabled()  → bool
    controller.get_block_reason() → str  (empty string when live is allowed)

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

from ..phase10.go_live_controller import TradingMode

log = structlog.get_logger()

# ── Thresholds ────────────────────────────────────────────────────────────────

_EV_CAPTURE_MIN: float = 0.75
_FILL_RATE_MIN: float = 0.60
_P95_LATENCY_MAX_MS: float = 500.0
_DRAWDOWN_MAX: float = 0.08

# Sentinel value used when a metric cannot be read.
# Set high enough to guarantee latency gate failure when no value is available.
_METRIC_UNAVAILABLE_LATENCY: float = 9_999_999.0


@dataclass
class LiveModeThresholds:
    """Configurable GO-LIVE gate thresholds for LiveModeController."""

    ev_capture_min: float = _EV_CAPTURE_MIN
    fill_rate_min: float = _FILL_RATE_MIN
    p95_latency_max_ms: float = _P95_LATENCY_MAX_MS
    drawdown_max: float = _DRAWDOWN_MAX


# ── LiveModeController ────────────────────────────────────────────────────────


class LiveModeController:
    """Stateless per-execution LIVE mode gate.

    On every call to :meth:`is_live_enabled` the controller reads the current
    values from the injected ``metrics_validator`` and ``risk_guard`` objects.
    No result is ever cached; each call is independent.

    The controller may only activate LIVE mode when the injected
    ``mode`` is explicitly set to :attr:`TradingMode.LIVE`.  In all other
    cases it returns ``False`` immediately.

    Phase 10.6 adds infra validation: when MODE=LIVE, Redis, DB, and Telegram
    must all be configured.  Missing infrastructure blocks LIVE immediately.

    Args:
        mode: Desired trading mode (PAPER is the safe default).
        metrics_validator: Live MetricsValidator instance.
        risk_guard: Live RiskGuard instance (kill-switch source of truth).
        thresholds: Optional override thresholds.
        redis_client: Optional Redis client (required in LIVE mode).
        audit_logger: Optional LiveAuditLogger (DB required in LIVE mode).
        telegram_configured: Whether Telegram is configured (required in LIVE).
    """

    def __init__(
        self,
        mode: TradingMode = TradingMode.PAPER,
        metrics_validator: Optional[object] = None,
        risk_guard: Optional[object] = None,
        thresholds: Optional[LiveModeThresholds] = None,
        redis_client: Optional[object] = None,
        audit_logger: Optional[object] = None,
        telegram_configured: bool = False,
    ) -> None:
        self._mode = mode
        self._metrics_validator = metrics_validator
        self._risk_guard = risk_guard
        self._thresholds = thresholds or LiveModeThresholds()
        self._redis_client = redis_client
        self._audit_logger = audit_logger
        self._telegram_configured = telegram_configured

        log.info(
            "live_mode_controller_initialized",
            mode=mode.value,
            ev_capture_min=self._thresholds.ev_capture_min,
            fill_rate_min=self._thresholds.fill_rate_min,
            p95_latency_max_ms=self._thresholds.p95_latency_max_ms,
            drawdown_max=self._thresholds.drawdown_max,
            redis_connected=redis_client is not None,
            db_connected=self._is_db_connected(),
            telegram_configured=telegram_configured,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        config: dict,
        metrics_validator: Optional[object] = None,
        risk_guard: Optional[object] = None,
    ) -> "LiveModeController":
        """Build from a configuration dict.

        Args:
            config: Top-level config dict.  Reads ``go_live`` sub-key.
            metrics_validator: Live MetricsValidator instance.
            risk_guard: Live RiskGuard instance.

        Returns:
            Configured LiveModeController.
        """
        cfg = config.get("go_live", {})
        raw_mode = str(cfg.get("mode", "PAPER")).upper()
        try:
            mode = TradingMode(raw_mode)
        except ValueError:
            log.warning(
                "live_mode_controller_invalid_mode",
                raw_mode=raw_mode,
                fallback="PAPER",
            )
            mode = TradingMode.PAPER

        thresholds = LiveModeThresholds(
            ev_capture_min=float(cfg.get("ev_capture_min", _EV_CAPTURE_MIN)),
            fill_rate_min=float(cfg.get("fill_rate_min", _FILL_RATE_MIN)),
            p95_latency_max_ms=float(cfg.get("p95_latency_max_ms", _P95_LATENCY_MAX_MS)),
            drawdown_max=float(cfg.get("drawdown_max", _DRAWDOWN_MAX)),
        )
        return cls(
            mode=mode,
            metrics_validator=metrics_validator,
            risk_guard=risk_guard,
            thresholds=thresholds,
        )

    # ── Mode control ──────────────────────────────────────────────────────────

    @property
    def mode(self) -> TradingMode:
        """Current configured trading mode."""
        return self._mode

    def set_mode(self, mode: TradingMode) -> None:
        """Change the trading mode.

        Args:
            mode: New trading mode.
        """
        prev = self._mode
        self._mode = mode
        log.info(
            "live_mode_controller_mode_changed",
            previous=prev.value,
            current=mode.value,
        )

    # ── Primary gate ──────────────────────────────────────────────────────────

    def is_live_enabled(self) -> bool:
        """Return True only when ALL GO-LIVE conditions are currently met.

        This is a stateless check — every call re-reads live values from
        the injected ``metrics_validator`` and ``risk_guard``.  No result is
        cached or reused between calls.

        Returns:
            True if LIVE trading is currently permitted.
        """
        # Fast-path: PAPER mode blocks unconditionally.
        if self._mode is TradingMode.PAPER:
            log.debug("live_mode_controller_paper_mode")
            return False

        reason = self._compute_block_reason()
        if reason:
            log.warning("live_mode_controller_blocked", reason=reason)
            return False

        log.debug("live_mode_controller_live_allowed")
        return True

    def get_block_reason(self) -> str:
        """Return a machine-readable reason why LIVE is currently blocked.

        Returns an empty string when LIVE trading is permitted.

        Returns:
            Reason string, or ``""`` if LIVE is currently allowed.
        """
        if self._mode is TradingMode.PAPER:
            return "paper_mode"
        return self._compute_block_reason()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_block_reason(self) -> str:
        """Evaluate all GO-LIVE conditions and return the first block reason.

        The method re-reads all current metric values on every invocation.

        Returns:
            First failure reason string, or ``""`` when all checks pass.
        """
        # ── Kill switch (highest priority) ────────────────────────────────────
        if self._risk_guard is not None:
            kill_active = bool(getattr(self._risk_guard, "disabled", False))
            if kill_active:
                log.warning("live_mode_controller_kill_switch_active")
                return "kill_switch_active"
        else:
            # No risk guard injected — treat as kill switch active (fail closed).
            log.warning("live_mode_controller_no_risk_guard")
            return "no_risk_guard"

        # ── Metrics availability ──────────────────────────────────────────────
        if self._metrics_validator is None:
            log.warning("live_mode_controller_no_metrics_validator")
            return "no_metrics_validator"

        # ── Read live metrics ─────────────────────────────────────────────────
        ev_capture = self._read_metric("ev_capture_ratio", 0.0)
        fill_rate = self._read_metric("fill_rate", 0.0)
        # MetricsValidator uses "p95_latency" as the field name; also accept
        # "p95_latency_ms" for duck-typed sources.
        p95_latency = self._read_metric("p95_latency", _METRIC_UNAVAILABLE_LATENCY)
        if p95_latency == _METRIC_UNAVAILABLE_LATENCY:
            p95_latency = self._read_metric("p95_latency_ms", _METRIC_UNAVAILABLE_LATENCY)
        drawdown = self._read_metric("drawdown", 1.0)

        # ── Gate checks (strict — no tolerance) ───────────────────────────────
        if ev_capture < self._thresholds.ev_capture_min:
            return (
                f"ev_capture_below_threshold:"
                f"{ev_capture:.4f}<{self._thresholds.ev_capture_min:.4f}"
            )

        if fill_rate < self._thresholds.fill_rate_min:
            return (
                f"fill_rate_below_threshold:"
                f"{fill_rate:.4f}<{self._thresholds.fill_rate_min:.4f}"
            )

        if p95_latency > self._thresholds.p95_latency_max_ms:
            return (
                f"p95_latency_exceeded:"
                f"{p95_latency:.1f}>{self._thresholds.p95_latency_max_ms:.1f}"
            )

        if drawdown > self._thresholds.drawdown_max:
            return (
                f"drawdown_exceeded:"
                f"{drawdown:.4f}>{self._thresholds.drawdown_max:.4f}"
            )

        # ── Phase 10.6: Infrastructure validation (LIVE only) ────────────────
        if self._redis_client is None:
            log.warning("live_mode_controller_no_redis")
            return "no_redis_client"

        if not self._is_db_connected():
            log.warning("live_mode_controller_no_db")
            return "no_db_connected"

        if not self._telegram_configured:
            log.warning("live_mode_controller_telegram_not_configured")
            return "telegram_not_configured"

        return ""

    def _is_db_connected(self) -> bool:
        """Check whether the audit logger has an active DB connection.

        Returns:
            True if audit_logger.is_db_connected() returns True, else False.
        """
        if self._audit_logger is None:
            return False
        is_connected = getattr(self._audit_logger, "is_db_connected", None)
        if callable(is_connected):
            try:
                return bool(is_connected())
            except Exception:  # noqa: BLE001
                return False
        return False

    def _read_metric(self, attr: str, default: float) -> float:
        """Safely read a numeric metric from MetricsValidator.

        Attempts to read from `metrics_validator.compute()` result first,
        then falls back to direct attribute access.

        Args:
            attr: Attribute name on the MetricsResult / validator.
            default: Value to use if attribute is missing.

        Returns:
            Current metric value as float.
        """
        mv = self._metrics_validator
        if mv is None:
            return default

        # Try direct attribute on validator (live streaming values)
        val = getattr(mv, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

        return default
