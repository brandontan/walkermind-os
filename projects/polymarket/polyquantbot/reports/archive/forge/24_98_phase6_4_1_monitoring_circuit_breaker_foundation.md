# Phase 6.4.1 Monitoring & Circuit Breaker — FOUNDATION Spec Contract (Deterministic)

**Validation Tier:** MAJOR  
**Claim Level:** FOUNDATION  
**Validation Target:** Deterministic spec contract correctness only (typed inputs, threshold boundaries, anomaly-to-decision mapping, and guard policy contract).  
**Not in Scope:** Runtime monitoring loop activation, scheduler wiring, alert transport wiring, persistence, execution-loop halting integration, anomaly evaluator implementation code, and production runtime side effects.  
**Suggested Next Step:** SENTINEL validation required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_99_phase6_4_1_monitoring_circuit_breaker_spec_fix.md`. Tier: MAJOR.

---

## 1) Contract purpose
This document defines a deterministic, evaluable FOUNDATION contract for Phase 6.4.1 monitoring and circuit-breaker decisioning.  
The contract is specification-only and establishes strict typed inputs and fixed decision rules so future runtime implementation cannot reinterpret policy behavior.

---

## 2) Risk-constant alignment (authoritative)
The spec is explicitly aligned with repository risk constants:

- Kelly fraction: `0.25` fractional only (policy reference)
- Max position size: `<= 10%` of total capital
- Max concurrent trades: `5` (context reference)
- Daily loss hard stop: `-2000` USD (context reference)
- Max drawdown stop: `> 8%` (context reference)
- Liquidity minimum: `10000` USD depth (context reference)

### Exposure threshold boundary rule (explicit)
For this Phase 6.4.1 contract:

- Let `exposure_ratio` be normalized as decimal in `[0.0, +inf)` where `0.10 == 10%`.
- **Allowed boundary:** `exposure_ratio <= 0.10` is compliant (no exposure-threshold anomaly).
- **Violation boundary:** `exposure_ratio > 0.10` is a threshold breach (exposure-threshold anomaly).

This resolves the exact 10% edge case: **exactly 10% is allowed, greater than 10% is violation**.

---

## 3) Typed contract inputs (all anomalies evaluable without inference)
All anomaly categories below MUST be evaluable from explicit typed inputs only:

```python
@dataclass(frozen=True)
class MonitoringContractInput:
    # identity / traceability
    policy_ref: str
    eval_ref: str
    timestamp_ms: int

    # exposure guard inputs
    exposure_ratio: float              # normalized decimal (0.10 = 10%)
    position_notional_usd: float
    total_capital_usd: float

    # quality guard inputs
    data_freshness_ms: int             # age of latest market datum
    quality_score: float               # normalized [0.0, 1.0]
    signal_dedup_ok: bool

    # kill-switch / policy path inputs
    kill_switch_armed: bool
    kill_switch_triggered: bool
    monitoring_enabled: bool
    quality_guard_enabled: bool
    exposure_guard_enabled: bool

    # deterministic thresholds carried in policy contract
    max_exposure_ratio: float          # MUST be 0.10 for this phase
    max_data_freshness_ms: int
    min_quality_score: float
```

### Input validity rules
- `policy_ref` and `eval_ref` MUST be non-empty strings.
- `timestamp_ms` MUST be positive integer.
- `exposure_ratio`, `quality_score`, `max_exposure_ratio`, `min_quality_score` MUST be finite numbers.
- `exposure_ratio >= 0.0`.
- `max_exposure_ratio` MUST equal `0.10` in this phase to preserve risk-constant lock.
- `quality_score` and `min_quality_score` are expected in `[0.0, 1.0]`.
- `data_freshness_ms` and `max_data_freshness_ms` MUST be non-negative integers.

Invalid contract input is a deterministic anomaly: `INVALID_CONTRACT_INPUT`.

---

## 4) Anomaly taxonomy (fixed)
Anomaly categories are fixed and named as follows.

### Exposure guard anomalies
1. `EXPOSURE_THRESHOLD_BREACH`  
   Trigger: `exposure_guard_enabled` and `exposure_ratio > max_exposure_ratio`.
2. `EXPOSURE_INPUT_INCONSISTENT`  
   Trigger: `total_capital_usd <= 0` OR `position_notional_usd < 0` OR non-finite numeric input.

### Quality guard anomalies
3. `DATA_STALENESS_BREACH`  
   Trigger: `quality_guard_enabled` and `data_freshness_ms > max_data_freshness_ms`.
4. `QUALITY_SCORE_BREACH`  
   Trigger: `quality_guard_enabled` and `quality_score < min_quality_score`.
5. `SIGNAL_DEDUP_FAILURE`  
   Trigger: `quality_guard_enabled` and `signal_dedup_ok is False`.

### Kill-switch / policy anomalies
6. `KILL_SWITCH_TRIGGERED`  
   Trigger: `kill_switch_armed is True` and `kill_switch_triggered is True`.
7. `MONITORING_DISABLED`  
   Trigger: `monitoring_enabled is False`.
8. `INVALID_CONTRACT_INPUT`  
   Trigger: any input validity rule violation in Section 3.

---

## 5) Deterministic anomaly-to-decision mapping
Decision enums for the contract:

- `ALLOW`
- `BLOCK`
- `HALT`

Deterministic precedence order (highest first):

1. `INVALID_CONTRACT_INPUT` -> `HALT`
2. `MONITORING_DISABLED` -> `BLOCK`
3. `KILL_SWITCH_TRIGGERED` -> `HALT`
4. Any exposure/quality breach anomaly -> `BLOCK`
5. No anomaly -> `ALLOW`

### Guard-level mapping details
- Exposure guard anomalies (`EXPOSURE_THRESHOLD_BREACH`, `EXPOSURE_INPUT_INCONSISTENT`) map to `BLOCK` unless superseded by higher-precedence `HALT` anomalies.
- Quality guard anomalies (`DATA_STALENESS_BREACH`, `QUALITY_SCORE_BREACH`, `SIGNAL_DEDUP_FAILURE`) map to `BLOCK` unless superseded by higher-precedence `HALT` anomalies.

### Multi-anomaly resolution
- Collect all triggered anomalies from typed inputs.
- Apply precedence order once.
- Emit:
  - `decision`
  - `primary_anomaly` (highest precedence)
  - `all_anomalies` (deterministic sorted order by enum name)
  - `policy_ref`, `eval_ref`, `timestamp_ms`

This guarantees stable outputs for identical inputs.

---

## 6) Determinism and implementation constraints
- No hidden state is allowed in evaluator contract for Phase 6.4.1.
- No runtime side effect is permitted in FOUNDATION spec evaluation.
- Equal inputs MUST produce equal anomaly set and equal decision.
- No anomaly may require inferred fields outside Section 3.

---

## 7) Explicit non-goals for this phase
This phase does **not** claim:
- runtime process integration,
- execution interruption wiring,
- alert delivery,
- background scheduling,
- storage schemas,
- or production kill path activation.

This is spec-contract hardening only.
