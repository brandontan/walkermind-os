"""Phase 10.7 — PreLiveValidator: Pre-LIVE validation gate.

Performs a comprehensive validation pass before activating LIVE trading mode.
All checks must pass; a single failure blocks LIVE activation.

Checks:
    ev_capture     ≥ 0.75  (configurable)
    fill_rate      ≥ 0.60  (configurable)
    latency_p95    ≤ 500ms (configurable)
    drawdown       ≤ 0.08  (configurable)
    kill_switch    == OFF  (RiskGuard.disabled must be False)
    redis          == connected
    db             == connected
    telegram       == configured

Result schema::

    {
        "status": "PASS" | "FAIL",
        "checks": {
            "ev_capture": true,
            "fill_rate": false,
            ...
        },
        "reason": "fill_rate below threshold: 0.50 < 0.60"
    }

Design:
    - Fail-closed: any single check failure → FAIL.
    - Synchronous (no I/O): reads cached values only.
    - Deterministic: same inputs always produce same output.
    - Idempotent: safe to call repeatedly.
    - Zero silent failure: all exceptions caught and logged as FAIL.

Usage::

    validator = PreLiveValidator(
        metrics_validator=metrics,
        risk_guard=guard,
        redis_client=redis,
        audit_logger=audit,
        telegram_configured=True,
    )
    result = validator.run()
    if result.status == "FAIL":
        log.warning("prelive_check_failed", reason=result.reason)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Thresholds ────────────────────────────────────────────────────────────────

_EV_CAPTURE_MIN: float = 0.75
_FILL_RATE_MIN: float = 0.60
_LATENCY_MAX_MS: float = 500.0
_DRAWDOWN_MAX: float = 0.08

# Sentinel value for unavailable latency — forces latency gate failure.
_LATENCY_UNAVAILABLE: float = 9_999_999.0


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class PreLiveResult:
    """Structured result of a PreLiveValidator.run() call.

    Attributes:
        status: "PASS" if all checks passed, "FAIL" otherwise.
        checks: Per-check pass/fail mapping.
        reason: Human-readable failure reason.  Empty string when PASS.
        timestamp: Unix epoch seconds when the check was run.
    """

    status: str
    checks: dict = field(default_factory=dict)
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "status": self.status,
            "checks": self.checks,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# ── PreLiveValidator ──────────────────────────────────────────────────────────


class PreLiveValidator:
    """Validates all pre-LIVE conditions before activating LIVE trading.

    Evaluates eight gating checks.  All checks must pass; if any single
    check fails the result status is ``"FAIL"`` with the first failure
    reason returned in ``result.reason``.

    Args:
        metrics_validator: MetricsValidator instance for reading live metrics.
        risk_guard: RiskGuard instance (kill-switch source of truth).
        redis_client: Redis client (None means not connected).
        audit_logger: LiveAuditLogger with ``is_db_connected()`` method.
        telegram_configured: Whether Telegram bot token + chat_id are set.
        ev_capture_min: Minimum EV capture ratio threshold.
        fill_rate_min: Minimum fill rate threshold.
        latency_max_ms: Maximum p95 latency threshold in milliseconds.
        drawdown_max: Maximum drawdown threshold.
    """

    def __init__(
        self,
        metrics_validator: Optional[object] = None,
        risk_guard: Optional[object] = None,
        redis_client: Optional[object] = None,
        audit_logger: Optional[object] = None,
        telegram_configured: bool = False,
        ev_capture_min: float = _EV_CAPTURE_MIN,
        fill_rate_min: float = _FILL_RATE_MIN,
        latency_max_ms: float = _LATENCY_MAX_MS,
        drawdown_max: float = _DRAWDOWN_MAX,
    ) -> None:
        self._metrics = metrics_validator
        self._risk_guard = risk_guard
        self._redis = redis_client
        self._audit_logger = audit_logger
        self._telegram_configured = telegram_configured
        self._ev_capture_min = ev_capture_min
        self._fill_rate_min = fill_rate_min
        self._latency_max_ms = latency_max_ms
        self._drawdown_max = drawdown_max

        log.info(
            "prelive_validator_initialized",
            ev_capture_min=ev_capture_min,
            fill_rate_min=fill_rate_min,
            latency_max_ms=latency_max_ms,
            drawdown_max=drawdown_max,
        )

    # ── Primary API ───────────────────────────────────────────────────────────

    def run(self) -> PreLiveResult:
        """Execute all pre-LIVE validation checks.

        Returns:
            PreLiveResult with status, per-check results, and failure reason.
        """
        checks: dict[str, bool] = {}
        first_failure: str = ""

        try:
            # ── 1. EV capture ─────────────────────────────────────────────────
            ev = self._read_metric("ev_capture_ratio", 0.0)
            checks["ev_capture"] = ev >= self._ev_capture_min
            if not checks["ev_capture"] and not first_failure:
                first_failure = (
                    f"ev_capture below threshold: {ev:.4f} < {self._ev_capture_min:.4f}"
                )

            # ── 2. Fill rate ──────────────────────────────────────────────────
            fill = self._read_metric("fill_rate", 0.0)
            checks["fill_rate"] = fill >= self._fill_rate_min
            if not checks["fill_rate"] and not first_failure:
                first_failure = (
                    f"fill_rate below threshold: {fill:.4f} < {self._fill_rate_min:.4f}"
                )

            # ── 3. Latency ────────────────────────────────────────────────────
            latency = self._read_metric("p95_latency", _LATENCY_UNAVAILABLE)
            if latency == _LATENCY_UNAVAILABLE:
                latency = self._read_metric("p95_latency_ms", _LATENCY_UNAVAILABLE)
            checks["latency"] = latency <= self._latency_max_ms
            if not checks["latency"] and not first_failure:
                first_failure = (
                    f"p95_latency exceeded: {latency:.1f}ms > {self._latency_max_ms:.1f}ms"
                )

            # ── 4. Drawdown ───────────────────────────────────────────────────
            drawdown = self._read_metric("drawdown", 1.0)
            checks["drawdown"] = drawdown <= self._drawdown_max
            if not checks["drawdown"] and not first_failure:
                first_failure = (
                    f"drawdown exceeded: {drawdown:.4f} > {self._drawdown_max:.4f}"
                )

            # ── 5. Kill switch ────────────────────────────────────────────────
            kill_active = self._is_kill_switch_active()
            checks["kill_switch_off"] = not kill_active
            if kill_active and not first_failure:
                first_failure = "kill_switch is active — trading halted"

            # ── 6. Redis ──────────────────────────────────────────────────────
            redis_ok = self._redis is not None
            checks["redis_connected"] = redis_ok
            if not redis_ok and not first_failure:
                first_failure = "redis not connected — required for LIVE dedup"

            # ── 7. DB (PostgreSQL) ────────────────────────────────────────────
            db_ok = self._is_db_connected()
            checks["db_connected"] = db_ok
            if not db_ok and not first_failure:
                first_failure = "postgresql not connected — required for LIVE audit"

            # ── 8. Telegram ───────────────────────────────────────────────────
            checks["telegram_configured"] = self._telegram_configured
            if not self._telegram_configured and not first_failure:
                first_failure = "telegram not configured — required for LIVE alerts"

        except Exception as exc:  # noqa: BLE001
            log.error(
                "prelive_validator_unexpected_error",
                error=str(exc),
                exc_info=True,
            )
            checks.setdefault("unexpected_error", False)
            first_failure = f"unexpected error during validation: {exc}"

        status = "PASS" if not first_failure else "FAIL"

        result = PreLiveResult(
            status=status,
            checks=checks,
            reason=first_failure,
        )

        log.info(
            "prelive_validation_complete",
            status=status,
            checks=checks,
            reason=first_failure,
        )

        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _read_metric(self, attr: str, default: float) -> float:
        """Safely read a numeric metric from the metrics validator.

        Args:
            attr: Attribute name on the MetricsResult or validator.
            default: Value to use if attribute is missing or unreadable.

        Returns:
            Current metric value as float.
        """
        if self._metrics is None:
            return default
        val = getattr(self._metrics, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        return default

    def _is_kill_switch_active(self) -> bool:
        """Check whether the kill switch is currently active.

        Returns:
            True if kill switch is active (trading blocked), False otherwise.
        """
        if self._risk_guard is None:
            return True  # No risk guard → treat as kill switch active (fail closed)
        return bool(getattr(self._risk_guard, "disabled", False))

    def _is_db_connected(self) -> bool:
        """Check whether the audit logger has an active DB connection.

        Returns:
            True if connected, False otherwise.
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
