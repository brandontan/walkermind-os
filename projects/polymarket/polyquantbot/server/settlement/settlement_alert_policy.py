"""Settlement Alert Policy — Priority 7 section 48.

Pure classification functions — no side effects, no I/O.
Injected into OperatorConsole for Telegram alert routing.

Critical conditions (always alert in LIVE; warn-only in PAPER):
  - HALT monitoring anomaly
  - Retries exhausted on a non-paper settlement
  - BLOCKED with fatal reason in LIVE mode

Drift conditions (always alert regardless of mode):
  - Partial batch (some items failed)
  - Stuck reconciliation entry
  - Mismatch without clear repair path
"""
from __future__ import annotations

from typing import Optional

import structlog

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import FUND_SETTLEMENT_HALT_MONITORING_ANOMALY

from .schemas import (
    BATCH_STATUS_PARTIAL,
    RECON_OUTCOME_MISMATCH,
    RECON_OUTCOME_STUCK,
    RETRY_OUTCOME_EXHAUSTED,
    SETTLEMENT_EVENT_DRIFT_DETECTED,
    SETTLEMENT_EVENT_FAILED,
    SETTLEMENT_EVENT_RETRY_ATTEMPT,
    AlertClassification,
    BatchReconciliationResult,
    ReconciliationResult,
    SettlementBatchResult,
    SettlementEvent,
)
from .retry_engine import FATAL_BLOCK_REASONS

log = structlog.get_logger(__name__)

_CRITICAL_EVENT_TYPES = frozenset({
    SETTLEMENT_EVENT_FAILED,
})


class SettlementAlertPolicy:
    """Pure classification of settlement events for Telegram alerting.

    All methods are deterministic — same input always produces same output.
    """

    def classify(
        self,
        event: SettlementEvent,
        mode: str,
        recon_result: Optional[ReconciliationResult] = None,
        batch_result: Optional[SettlementBatchResult] = None,
    ) -> AlertClassification:
        critical = self.is_critical(event.event_type, event.payload.get("blocked_reason"), mode)
        drift = self.is_drift(recon_result, batch_result)

        alert_reason = _build_alert_reason(event, critical, drift, mode)

        if critical or drift:
            log.info(
                "settlement_alert_classified",
                workflow_id=event.workflow_id,
                event_type=event.event_type,
                is_critical=critical,
                is_drift=drift,
                mode=mode,
            )

        return AlertClassification(
            is_critical=critical,
            is_drift=drift,
            alert_reason=alert_reason,
            workflow_id=event.workflow_id,
            settlement_id=event.settlement_id,
        )

    @staticmethod
    def is_critical(
        event_type: str,
        blocked_reason: Optional[str],
        mode: str,
    ) -> bool:
        """Critical = require immediate operator attention in LIVE mode."""
        if mode != "live":
            return False

        if blocked_reason == FUND_SETTLEMENT_HALT_MONITORING_ANOMALY:
            return True

        if blocked_reason in FATAL_BLOCK_REASONS and event_type == SETTLEMENT_EVENT_FAILED:
            return True

        if event_type == SETTLEMENT_EVENT_RETRY_ATTEMPT:
            outcome = blocked_reason
            if outcome == RETRY_OUTCOME_EXHAUSTED:
                return True

        return False

    @staticmethod
    def is_drift(
        recon_result: Optional[ReconciliationResult],
        batch_result: Optional[SettlementBatchResult],
    ) -> bool:
        """Drift = observable state inconsistency that needs investigation."""
        if recon_result is not None:
            if recon_result.outcome in (RECON_OUTCOME_STUCK, RECON_OUTCOME_MISMATCH):
                return True

        if batch_result is not None:
            if batch_result.batch_status == BATCH_STATUS_PARTIAL:
                return True

        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_alert_reason(
    event: SettlementEvent,
    is_critical: bool,
    is_drift: bool,
    mode: str,
) -> str:
    if is_critical:
        blocked = event.payload.get("blocked_reason", "unknown")
        return f"CRITICAL [{mode.upper()}] {event.event_type}: {blocked}"
    if is_drift:
        return f"DRIFT {event.event_type}: workflow={event.workflow_id}"
    return f"INFO {event.event_type}"
