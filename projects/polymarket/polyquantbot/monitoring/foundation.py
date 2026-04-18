"""Phase 6.4.1 — Monitoring & Circuit Breaker FOUNDATION.

Deterministic evaluation contract for monitoring and circuit-breaker decisions.
Pure function: no runtime state, no side effects, no async workers.

All anomalies are deterministically evaluated from typed MonitoringContractInput alone.
Equal inputs always produce equal anomaly set and equal decision.

Claim Level : FOUNDATION
Not in scope : runtime process integration, execution interruption wiring,
               alert delivery, background scheduling, storage schemas,
               or production kill path activation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Decision categories
# ─────────────────────────────────────────────────────────────────────────────


class MonitoringDecision(str, Enum):
    """Deterministic circuit-breaker decision categories (spec Section 5)."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    HALT = "HALT"


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly taxonomy — fixed; names are canonical for precedence and sort
# ─────────────────────────────────────────────────────────────────────────────


class MonitoringAnomalyCategory(str, Enum):
    """Fixed anomaly taxonomy for Phase 6.4.1 monitoring contract (spec Section 4)."""

    # Exposure guard
    EXPOSURE_THRESHOLD_BREACH = "EXPOSURE_THRESHOLD_BREACH"
    EXPOSURE_INPUT_INCONSISTENT = "EXPOSURE_INPUT_INCONSISTENT"
    # Quality guard
    DATA_STALENESS_BREACH = "DATA_STALENESS_BREACH"
    QUALITY_SCORE_BREACH = "QUALITY_SCORE_BREACH"
    SIGNAL_DEDUP_FAILURE = "SIGNAL_DEDUP_FAILURE"
    # Kill-switch / policy
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
    MONITORING_DISABLED = "MONITORING_DISABLED"
    INVALID_CONTRACT_INPUT = "INVALID_CONTRACT_INPUT"


# Precedence table — earlier index = higher precedence (spec Section 5).
_ANOMALY_PRECEDENCE: List[MonitoringAnomalyCategory] = [
    MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT,
    MonitoringAnomalyCategory.MONITORING_DISABLED,
    MonitoringAnomalyCategory.KILL_SWITCH_TRIGGERED,
    MonitoringAnomalyCategory.EXPOSURE_THRESHOLD_BREACH,
    MonitoringAnomalyCategory.EXPOSURE_INPUT_INCONSISTENT,
    MonitoringAnomalyCategory.DATA_STALENESS_BREACH,
    MonitoringAnomalyCategory.QUALITY_SCORE_BREACH,
    MonitoringAnomalyCategory.SIGNAL_DEDUP_FAILURE,
]

# Deterministic anomaly-to-decision mapping (spec Section 5).
_ANOMALY_DECISION: dict[MonitoringAnomalyCategory, MonitoringDecision] = {
    MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT: MonitoringDecision.HALT,
    MonitoringAnomalyCategory.MONITORING_DISABLED: MonitoringDecision.BLOCK,
    MonitoringAnomalyCategory.KILL_SWITCH_TRIGGERED: MonitoringDecision.HALT,
    MonitoringAnomalyCategory.EXPOSURE_THRESHOLD_BREACH: MonitoringDecision.BLOCK,
    MonitoringAnomalyCategory.EXPOSURE_INPUT_INCONSISTENT: MonitoringDecision.BLOCK,
    MonitoringAnomalyCategory.DATA_STALENESS_BREACH: MonitoringDecision.BLOCK,
    MonitoringAnomalyCategory.QUALITY_SCORE_BREACH: MonitoringDecision.BLOCK,
    MonitoringAnomalyCategory.SIGNAL_DEDUP_FAILURE: MonitoringDecision.BLOCK,
}

# Risk-constant lock: max_exposure_ratio MUST equal this value (spec Section 2).
_MAX_EXPOSURE_RATIO_LOCKED: float = 0.10


# ─────────────────────────────────────────────────────────────────────────────
# Typed input contract
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MonitoringContractInput:
    """Typed input contract for Phase 6.4.1 monitoring evaluation (spec Section 3).

    All anomaly categories are evaluable from these explicit fields alone.
    No inferred data is permitted.
    """

    # identity / traceability
    policy_ref: str
    eval_ref: str
    timestamp_ms: int

    # exposure guard inputs
    exposure_ratio: float           # normalized decimal (0.10 == 10%)
    position_notional_usd: float
    total_capital_usd: float

    # quality guard inputs
    data_freshness_ms: int          # age of latest market datum in milliseconds
    quality_score: float            # normalized [0.0, 1.0]
    signal_dedup_ok: bool

    # kill-switch / policy path inputs
    kill_switch_armed: bool
    kill_switch_triggered: bool
    monitoring_enabled: bool
    quality_guard_enabled: bool
    exposure_guard_enabled: bool

    # deterministic thresholds carried in policy contract
    max_exposure_ratio: float       # MUST equal 0.10 (risk-constant lock)
    max_data_freshness_ms: int
    min_quality_score: float


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation result
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MonitoringEvaluationResult:
    """Deterministic evaluation output for one MonitoringContractInput.

    primary_anomaly: highest-precedence triggered anomaly, or None when ALLOW.
    all_anomalies: every triggered anomaly, sorted by enum name for stable output.
    """

    decision: MonitoringDecision
    primary_anomaly: Optional[MonitoringAnomalyCategory]
    all_anomalies: tuple[MonitoringAnomalyCategory, ...]
    policy_ref: str
    eval_ref: str
    timestamp_ms: int


# ─────────────────────────────────────────────────────────────────────────────
# Pure evaluator
# ─────────────────────────────────────────────────────────────────────────────


def evaluate_monitoring_contract(
    contract_input: MonitoringContractInput,
) -> MonitoringEvaluationResult:
    """Evaluate a MonitoringContractInput deterministically.

    Pure function — no state, no side effects, no async.
    Equal inputs always produce equal outputs.

    Decision precedence (highest first, spec Section 5):
    1. INVALID_CONTRACT_INPUT -> HALT
    2. MONITORING_DISABLED    -> BLOCK
    3. KILL_SWITCH_TRIGGERED  -> HALT
    4. Exposure/quality breach anomalies -> BLOCK
    5. No anomaly             -> ALLOW

    Args:
        contract_input: Typed input for evaluation.

    Returns:
        MonitoringEvaluationResult with deterministic decision and anomaly set.
    """
    triggered: List[MonitoringAnomalyCategory] = []

    # ── Step 1: Contract input validity ──────────────────────────────────────
    invalid = _check_contract_validity(contract_input)
    if invalid:
        triggered.append(MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT)

    # ── Steps 2–5: only evaluated when contract is valid ─────────────────────
    if not invalid:
        # Step 2: Monitoring disabled
        if not contract_input.monitoring_enabled:
            triggered.append(MonitoringAnomalyCategory.MONITORING_DISABLED)

        # Step 3: Kill-switch triggered (armed AND triggered)
        if contract_input.kill_switch_armed and contract_input.kill_switch_triggered:
            triggered.append(MonitoringAnomalyCategory.KILL_SWITCH_TRIGGERED)

        # Step 4: Exposure guard anomalies
        if contract_input.exposure_guard_enabled:
            if (
                not math.isfinite(contract_input.exposure_ratio)
                or contract_input.total_capital_usd <= 0.0
                or contract_input.position_notional_usd < 0.0
            ):
                triggered.append(MonitoringAnomalyCategory.EXPOSURE_INPUT_INCONSISTENT)
            elif contract_input.exposure_ratio > contract_input.max_exposure_ratio:
                triggered.append(MonitoringAnomalyCategory.EXPOSURE_THRESHOLD_BREACH)

        # Step 5: Quality guard anomalies
        if contract_input.quality_guard_enabled:
            if contract_input.data_freshness_ms > contract_input.max_data_freshness_ms:
                triggered.append(MonitoringAnomalyCategory.DATA_STALENESS_BREACH)
            if contract_input.quality_score < contract_input.min_quality_score:
                triggered.append(MonitoringAnomalyCategory.QUALITY_SCORE_BREACH)
            if not contract_input.signal_dedup_ok:
                triggered.append(MonitoringAnomalyCategory.SIGNAL_DEDUP_FAILURE)

    # ── Decision resolution ───────────────────────────────────────────────────
    if not triggered:
        return MonitoringEvaluationResult(
            decision=MonitoringDecision.ALLOW,
            primary_anomaly=None,
            all_anomalies=(),
            policy_ref=contract_input.policy_ref,
            eval_ref=contract_input.eval_ref,
            timestamp_ms=contract_input.timestamp_ms,
        )

    all_anomalies_sorted = tuple(
        sorted(triggered, key=lambda a: a.name)
    )

    primary: Optional[MonitoringAnomalyCategory] = None
    for candidate in _ANOMALY_PRECEDENCE:
        if candidate in triggered:
            primary = candidate
            break

    assert primary is not None, "triggered is non-empty but no primary found — logic error"

    return MonitoringEvaluationResult(
        decision=_ANOMALY_DECISION[primary],
        primary_anomaly=primary,
        all_anomalies=all_anomalies_sorted,
        policy_ref=contract_input.policy_ref,
        eval_ref=contract_input.eval_ref,
        timestamp_ms=contract_input.timestamp_ms,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal: input validity checker
# ─────────────────────────────────────────────────────────────────────────────


def _check_contract_validity(inp: MonitoringContractInput) -> bool:
    """Return True if any input validity rule from spec Section 3 is violated."""
    # policy_ref and eval_ref must be non-empty strings
    if not isinstance(inp.policy_ref, str) or not inp.policy_ref:
        return True
    if not isinstance(inp.eval_ref, str) or not inp.eval_ref:
        return True
    # timestamp_ms must be a positive integer
    if not isinstance(inp.timestamp_ms, int) or inp.timestamp_ms <= 0:
        return True
    # numeric fields must be finite
    for val in (
        inp.exposure_ratio,
        inp.quality_score,
        inp.max_exposure_ratio,
        inp.min_quality_score,
        inp.position_notional_usd,
        inp.total_capital_usd,
    ):
        if not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            return True
    # exposure_ratio must be non-negative
    if inp.exposure_ratio < 0.0:
        return True
    # max_exposure_ratio must equal 0.10 to preserve risk-constant lock
    if abs(inp.max_exposure_ratio - _MAX_EXPOSURE_RATIO_LOCKED) > 1e-9:
        return True
    # data_freshness_ms and max_data_freshness_ms must be non-negative integers
    if not isinstance(inp.data_freshness_ms, int) or inp.data_freshness_ms < 0:
        return True
    if not isinstance(inp.max_data_freshness_ms, int) or inp.max_data_freshness_ms < 0:
        return True
    return False
