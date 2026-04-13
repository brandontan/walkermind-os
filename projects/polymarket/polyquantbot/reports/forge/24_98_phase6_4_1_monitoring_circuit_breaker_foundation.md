# Forge Report — Phase 6.4.1 Monitoring & Circuit Breaker Foundation Spec (MAJOR)

**Validation Tier:** MAJOR  
**Claim Level:** FOUNDATION  
**Validation Target:** `projects/polymarket/polyquantbot/reports/forge/24_98_phase6_4_1_monitoring_circuit_breaker_foundation.md`, `PROJECT_STATE.md` (and `ROADMAP.md` only if roadmap-level truth changes).  
**Not in Scope:** Runtime wiring into execution loop, background schedulers/polling workers, Telegram/UI alerts, dashboard/UI work, persistent metrics storage, auto-resume logic, selective partial-scope routing implementation, and any order placement/cancel/settlement behavior.  
**Suggested Next Step:** COMMANDER review of Phase 6.4.1 FOUNDATION spec, then scope Phase 6.4.2 runtime implementation. SENTINEL validation is required once runtime monitoring or auto-halt behavior is implemented.

---

## 1) What was defined
This phase defines deterministic, implementation-ready contracts and logic boundaries for monitoring and circuit-breaker control **without enabling runtime halts**.

### 1.1 Safety input model (monitoring-only inputs)
The monitoring snapshot input for Phase 6.4 is limited to:
- `execution_success_rate` (float, 0.0–1.0)
- `execution_failure_rate` (float, 0.0–1.0)
- `rolling_pnl_usd` (float)
- `rolling_drawdown_pct` (float, 0.0–1.0)
- `open_exposure_pct` (float, 0.0–1.0)
- `policy_kill_switch_state` (typed dependency: enabled/armed/halt_active)

Fail-closed input constraints:
- Any missing/non-finite/out-of-range field is invalid.
- Invalid snapshot returns deterministic `full_halt` decision with explicit contract error trace reason.
- No fallback defaults for invalid safety fields.

### 1.2 Deterministic anomaly categories with explicit thresholds
Anomaly levels: `INFO`, `WARNING`, `CRITICAL`.

Threshold matrix (inclusive boundaries):

| Metric | INFO | WARNING | CRITICAL |
|---|---:|---:|---:|
| Execution success rate | `< 0.98` | `< 0.95` | `< 0.90` |
| Execution failure rate | `> 0.02` | `> 0.05` | `> 0.10` |
| Rolling PnL (USD) | `<= -250` | `<= -750` | `<= -1500` |
| Rolling drawdown (%) | `>= 0.03` | `>= 0.05` | `>= 0.08` |
| Open exposure (%) | `>= 0.07` | `>= 0.09` | `> 0.10` |
| Kill-switch dependency | armed=false while enabled=true | halt intent inconsistent | halt_active=true |

Deterministic precedence:
1. Contract invalidity is highest severity (`CRITICAL`).
2. If multiple metric severities exist, take max severity.
3. Equal input snapshot must always yield equal anomaly set.

### 1.3 Circuit-breaker state machine
Breaker states:
- `NORMAL`
- `WARNING`
- `HALTED`

Transition rules are deterministic and idempotent per snapshot:
- `NORMAL -> WARNING` when max anomaly severity = `WARNING`.
- `NORMAL -> HALTED` when max anomaly severity = `CRITICAL`.
- `WARNING -> NORMAL` only when all anomaly severities resolve to none/`INFO`.
- `WARNING -> HALTED` when any `CRITICAL` anomaly appears.
- `HALTED -> HALTED` in this phase (no auto-resume in FOUNDATION).

### 1.4 Decision outputs
Outputs are constrained to:
- `allow` (state `NORMAL`; no warning/critical anomalies)
- `allow_with_warning` (state `WARNING`; warning-only anomalies)
- `block_new_entries` (state `WARNING`; warning anomalies plus guard on exposure/quality)
- `full_halt` (state `HALTED`; any critical anomaly, invalid input, or active kill-switch halt dependency)

Deterministic mapping:
- `CRITICAL` => `HALTED` => `full_halt`
- `WARNING` + exposure/quality guard tripped => `WARNING` => `block_new_entries`
- `WARNING` (non-guard) => `WARNING` => `allow_with_warning`
- No warning/critical => `NORMAL` => `allow`

### 1.5 Integration boundary for future wiring
- Monitoring component **observes only** and emits typed snapshots/anomalies.
- Circuit-breaker component **evaluates only** and emits typed decisions.
- Execution/settlement/transport invocation remains explicitly out of scope for this phase.

### 1.6 Typed contract proposal
Proposed Python dataclasses/enums for next implementation phase:

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class AnomalySeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

class BreakerState(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    HALTED = "HALTED"

class BreakerDecisionCode(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    BLOCK_NEW_ENTRIES = "block_new_entries"
    FULL_HALT = "full_halt"

@dataclass(frozen=True)
class MetricSnapshotInput:
    execution_success_rate: float
    execution_failure_rate: float
    rolling_pnl_usd: float
    rolling_drawdown_pct: float
    open_exposure_pct: float
    kill_switch_enabled: bool
    kill_switch_armed: bool
    kill_switch_halt_active: bool
    trace_refs: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AnomalySignal:
    category: str
    severity: AnomalySeverity
    reason: str

@dataclass(frozen=True)
class AnomalyEvaluationResult:
    signals: tuple[AnomalySignal, ...]
    max_severity: AnomalySeverity | None
    invalid_contract: bool

@dataclass(frozen=True)
class BreakerDecisionResult:
    state: BreakerState
    decision: BreakerDecisionCode
    reasons: tuple[str, ...]
    trace_payload: dict[str, Any]
```

### 1.7 Relationship to existing kill-switch foundation (Phase 6.3)
- Existing reference: `projects/polymarket/polyquantbot/platform/safety/kill_switch.py`.
- Phase 6.4.1 uses kill-switch status as an input dependency only.
- If kill-switch reports `halt_active=True`, breaker result must deterministically become `HALTED` + `full_halt`.
- Phase 6.4.1 does not modify or invoke kill-switch runtime actions.

### 1.8 Preserved Phase 6.3 guarantees
This foundation explicitly preserves:
- Deterministic behavior.
- Fail-closed invalid input handling.
- Side-effect-free evaluation path.
- No execution / settlement / transport invocation.

## 2) Current architecture fit
- Fits under existing safety architecture as a **parallel FOUNDATION contract layer** adjacent to kill-switch contracts.
- Keeps runtime orchestration untouched while defining strict typed interfaces needed for Phase 6.4.2 implementation.
- Respects the locked pipeline by positioning monitoring/breaker evaluation as pre-execution control signals without introducing live wiring in this phase.

## 3) Files created / modified (full paths)
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_98_phase6_4_1_monitoring_circuit_breaker_foundation.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4) What is unambiguously ready next
- Implement `MetricSnapshotInput` validation and anomaly evaluator as side-effect-free pure logic.
- Implement breaker state transition evaluator using explicit previous-state + current-anomaly input.
- Add deterministic tests for threshold boundaries and transition table coverage.
- Wire runtime integration only in a dedicated next phase after COMMANDER scope approval.

## 5) Known issues / open decisions
- Rolling window definition remains to be fixed in implementation scope (tick-count vs time-window); this spec only defines threshold semantics.
- Boundary behavior for exact equality is defined as inclusive where listed, but implementation should encode table-driven checks to avoid branch drift.
- `block_new_entries` enforcement path is intentionally not wired yet and must be implemented later.

## 6) What is next
- COMMANDER reviews this FOUNDATION spec.
- COMMANDER decides Phase 6.4.2 implementation scope (runtime wiring, tests, and sentinel gate if behavior becomes active).
- SENTINEL validation is deferred until runtime monitoring or auto-halt behavior is implemented.

---

**Report Timestamp:** 2026-04-13 19:17 UTC  
**Role:** FORGE-X (NEXUS)  
**Task:** 6.4.1 — Monitoring & Circuit Breaker Foundation Spec (MAJOR, FOUNDATION)
