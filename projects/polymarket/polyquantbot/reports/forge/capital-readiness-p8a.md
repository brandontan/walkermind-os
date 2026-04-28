# WARP•FORGE REPORT: capital-readiness-p8a
Branch: WARP/capital-readiness-p8a
Date: 2026-04-28 18:30 Asia/Jakarta

---

## Validation Metadata

- Branch: WARP/capital-readiness-p8a
- Validation Tier: MAJOR
- Claim Level: FOUNDATION
- Validation Target: `server/config/capital_mode_config.py`, `server/config/boundary_registry.py` — §49 capability boundary registry + §50 capital-mode config model (CR-01..CR-12)
- Not in Scope: Live execution path, risk controls hardening (P8-B), CLOB order submission, live market data wiring, per-user capital isolation — all deferred to P8-B through P8-E
- Suggested Next Step: WARP•SENTINEL validation required (MAJOR tier) before merge; P8-B risk controls hardening after this is merged

---

## 1. What Was Built

**§49 — Capability Boundary Registry** (`server/config/boundary_registry.py`):
- `PaperOnlyBoundary` frozen dataclass: surface name, file path, assumption, capital risk level, readiness gate, status
- `PAPER_ONLY_BOUNDARIES` — 13-entry audit registry covering every identified paper-only surface across execution, risk, settlement, portfolio, orchestration, persistence, security layers
- Risk classification: 5 CRITICAL, 5 HIGH, 3 MEDIUM, 0 LOW beyond the gate itself
- Status breakdown: 6 BLOCKED, 6 NEEDS_HARDENING, 1 SAFE_AS_IS
- Query helpers: `get_boundaries_by_gate()`, `get_boundaries_by_status()`, `get_critical_boundaries()`
- `get_capital_readiness_criteria()` — 22-item ordered checklist mapping each P8-B through P8-E gate to exact validation requirements; consumed by SENTINEL during each sweep

**§50 — Capital-Mode Config Model** (`server/config/capital_mode_config.py`):
- `CapitalModeConfig` frozen dataclass — 5 independent gate fields (all default False) + 5 risk parameter fields
- `CapitalModeGuardError` — raised when LIVE mode requested with any gate off
- `from_env()` — reads all gates and risk params from env vars; structured log on load
- `validate()` — enforces all 5 gates in LIVE mode; enforces risk bounds in all modes; no silent pass
- `is_capital_mode_allowed()` — boolean check used by caller to gate execution
- `open_gates_report()` — returns gate status dict for operator visibility / Telegram surface
- Locked constants: `KELLY_FRACTION = 0.25`, `MAX_POSITION_FRACTION_CAP = 0.10`, `DRAWDOWN_LIMIT_CAP = 0.08`

**Gate contract (all 5 must be true for LIVE):**

| Gate env var | Set after |
|---|---|
| `ENABLE_LIVE_TRADING=true` | WARP🔹CMD explicit opt-in |
| `CAPITAL_MODE_CONFIRMED=true` | WARP🔹CMD final confirmation (P8-E) |
| `RISK_CONTROLS_VALIDATED=true` | SENTINEL P8-B APPROVED |
| `EXECUTION_PATH_VALIDATED=true` | SENTINEL P8-C APPROVED |
| `SECURITY_HARDENING_VALIDATED=true` | SENTINEL P8-D APPROVED |

---

## 2. Current System Architecture

```
[LIVE trading request]
        │
        ▼
CapitalModeConfig.validate()
  Gate 1: ENABLE_LIVE_TRADING=true          ← existing guard (hardened)
  Gate 2: CAPITAL_MODE_CONFIRMED=true       ← new explicit second confirmation
  Gate 3: RISK_CONTROLS_VALIDATED=true      ← set after SENTINEL P8-B
  Gate 4: EXECUTION_PATH_VALIDATED=true     ← set after SENTINEL P8-C
  Gate 5: SECURITY_HARDENING_VALIDATED=true ← set after SENTINEL P8-D
        │
        │  all 5 required → CapitalModeGuardError if any missing
        ▼
is_capital_mode_allowed() → True only when all 5 gates set + LIVE mode
        │
        ▼
[Future: P8-B/C/D hardened execution path — not yet wired]

BoundaryRegistry
  13 entries audited
  CRITICAL surfaces → block live execution until their P8 gate clears
  NEEDS_HARDENING → must be reworked in P8-B/C/D builds
  get_capital_readiness_criteria() → 22-item SENTINEL checklist
```

---

## 3. Files Created / Modified (full repo-root paths)

**Created:**
```
projects/polymarket/polyquantbot/server/config/__init__.py
projects/polymarket/polyquantbot/server/config/capital_mode_config.py
projects/polymarket/polyquantbot/server/config/boundary_registry.py
projects/polymarket/polyquantbot/tests/test_capital_readiness_p8a.py
projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8a.md
```

**Modified:**
```
projects/polymarket/polyquantbot/state/PROJECT_STATE.md
projects/polymarket/polyquantbot/state/WORKTODO.md
projects/polymarket/polyquantbot/state/CHANGELOG.md
```

---

## 4. What Is Working

- All 16 P8-A tests pass: CR-01..CR-12 (16 test cases including 5 parametrized) (16/16)
- `CapitalModeConfig.from_env()` reads all 5 gates from correct env vars; defaults all to False
- `validate()` raises `CapitalModeGuardError` naming the exact missing gate for each of the 5 gates
- `validate()` passes cleanly in PAPER mode regardless of gate state
- `validate()` passes in LIVE mode only when all 5 gates are True
- Risk bounds enforced: `kelly_fraction` locked to 0.25; `max_position_fraction` capped at 0.10; `daily_loss_limit_usd` must be negative; `drawdown_limit_pct` capped at 0.08
- `BoundaryRegistry` contains 5 CRITICAL surfaces including `PaperExecutionEngine`, `SettlementWorkflow.allow_real_settlement`, `WalletCandidate.financial_fields_zero`
- `get_capital_readiness_criteria()` returns 22 ordered items spanning P8-A through P8-E
- All BLOCKED boundaries have a valid `P8-X` readiness gate assigned

---

## 5. Known Issues

- `CapitalModeConfig` is not yet wired into `server/main.py` or `server/core/runtime.py` — wiring to runtime is deferred to P8-C (live execution readiness) to avoid half-finished integration
- `BoundaryRegistry` is a static audit — entries must be updated as P8-B/C/D lanes complete and surfaces are hardened; SENTINEL must verify each boundary is resolved before approving its gate
- `get_failed_batches()` boundary (batch result persistence) remains unresolved until a dedicated batch persistence lane is built
- No Telegram surface for `open_gates_report()` yet — deferred to P8-D operator visibility lane

---

## 6. What Is Next

- WARP•SENTINEL MAJOR validation required before merge
- P8-B: Capital risk controls hardening (§51) — harden `PaperRiskGate`, wire `WalletCandidate` financial fields, wire live mark-to-market for portfolio unrealized PnL; clears `RISK_CONTROLS_VALIDATED` gate
- P8-C: Live execution readiness audit (§52) — validate live CLOB path, replace price_updater stub, wire `allow_real_settlement`, validate batch processor; clears `EXECUTION_PATH_VALIDATED` gate
- P8-D: Security + observability hardening (§53) — per-user isolation, audit log for admin interventions, production alerting; clears `SECURITY_HARDENING_VALIDATED` gate
- P8-E: Capital validation + claim review (§54) — dry-run, staged rollout plan, docs review, final WARP🔹CMD sign-off; sets `CAPITAL_MODE_CONFIRMED=true`

---

## Metadata

- **Validation Tier:** MAJOR
- **Claim Level:** FOUNDATION (config model + boundary registry — no execution path, no runtime wiring)
- **Validation Target:** §49 boundary audit + §50 capital-mode config guard (CR-01..CR-12)
- **Not in Scope:** Execution path wiring, risk controls hardening, live market data, security hardening — all deferred to P8-B through P8-E
- **Suggested Next Step:** WARP•SENTINEL MAJOR validation; P8-B after merge
