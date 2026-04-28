# WARP•FORGE REPORT: capital-readiness-p8b
Branch: claude/plan-build-warp-merge-EqC83
Date: 2026-04-28 Asia/Jakarta

---

## Validation Metadata

- Branch: claude/plan-build-warp-merge-EqC83
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: `server/risk/capital_risk_gate.py` — CapitalRiskGate (§51 risk controls hardening) + WalletFinancialProvider wiring + OrchestratorService enrichment hook (CR-13..CR-22)
- Not in Scope: Runtime wiring of CapitalRiskGate into PaperBetaWorker (P8-C), live WalletFinancialProvider implementation (P8-C), PortfolioStore unrealized PnL live mark-to-market (P8-C), CLOB execution path (P8-C)
- Suggested Next Step: WARP•SENTINEL MAJOR validation required before merge; P8-C live execution readiness audit after merge

---

## 1. What Was Built

**CapitalRiskGate** (`server/risk/capital_risk_gate.py`):
- Risk gate that reads ALL limits from an injected `CapitalModeConfig` instance — no hardcoded constants
- Enforces the full 5-gate guard in LIVE mode (raises `CapitalModeGuardError` before any signal evaluation)
- In PAPER mode: evaluates risk bounds only (same safe behaviour as `PaperRiskGate`)
- Evaluation order: kill_switch → idempotency → LIVE gate check → edge → liquidity → drawdown → exposure → daily loss
- `status()` method surfaces all limits + live state for Telegram/operator visibility
- Kelly=0.25 is locked in CapitalModeConfig and exposed via `status()` report

**WalletFinancialProvider** (`server/risk/capital_risk_gate.py`):
- `@runtime_checkable` Protocol defining the wiring contract for live financial data injection
- Three methods: `get_balance_usd()`, `get_exposure_pct()`, `get_drawdown_pct()` — all keyed by `wallet_id`
- `enrich_candidate(candidate, provider)` helper: takes a frozen `WalletCandidate` + provider, returns a new candidate with financial fields populated (uses `dataclasses.replace`)

**OrchestratorService enrichment hook** (`server/services/orchestration_service.py`):
- `_record_to_candidate(record, provider=None)` — accepts optional `WalletFinancialProvider`
- `OrchestratorService.__init__` accepts `financial_provider: Optional[WalletFinancialProvider] = None`
- `_load_candidates()` threads the provider through to every candidate; if None, defaults to 0.0 (backward-compatible)
- No existing callers are broken — provider defaults to None

**BoundaryRegistry updates** (`server/config/boundary_registry.py`):
- `PaperRiskGate` boundary assumption updated: notes CapitalRiskGate is built, runtime wiring is P8-C
- `WalletCandidate.financial_fields_zero` status: `BLOCKED` → `NEEDS_HARDENING`; assumption updated to note wiring exists, live provider is P8-C

---

## 2. Current System Architecture

```
[Signal evaluation request]
        │
        ▼
CapitalRiskGate.evaluate(signal, state)
  1. kill_switch check (PublicBetaState.kill_switch)
  2. idempotency check (state.processed_signals)
  3. LIVE mode: CapitalModeConfig.validate() ← raises CapitalModeGuardError if any gate off
  4. edge <= 0 → non_positive_ev
  5. edge < 0.02 → edge_below_threshold
  6. liquidity < config.min_liquidity_usd → liquidity_below_floor
  7. drawdown > config.drawdown_limit_pct (0.08) → drawdown_stop
  8. exposure >= config.max_position_fraction (0.10 cap) → exposure_cap
  9. realized_pnl <= config.daily_loss_limit_usd (-$2k) → daily_loss_limit
        │
        ▼
RiskDecision(allowed=True/False, reason=...)

[WalletCandidate routing — with financial provider]

WalletLifecycleStore.list_wallets_for_user()
        │
        ▼
_record_to_candidate(record, provider=WalletFinancialProvider)
        │ provider → enrich_candidate(candidate, provider)
        │   balance_usd  ← provider.get_balance_usd(wallet_id)
        │   exposure_pct ← provider.get_exposure_pct(wallet_id)
        │   drawdown_pct ← provider.get_drawdown_pct(wallet_id)
        ▼
WalletSelectionPolicy.select()
  Filter 5: _risk_ok() → drawdown_pct <= 0.08 AND exposure_pct < 0.10
```

---

## 3. Files Created / Modified (full repo-root paths)

**Created:**
```
projects/polymarket/polyquantbot/server/risk/capital_risk_gate.py
projects/polymarket/polyquantbot/tests/test_capital_readiness_p8b.py
projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8b.md
```

**Modified:**
```
projects/polymarket/polyquantbot/server/services/orchestration_service.py
projects/polymarket/polyquantbot/server/config/boundary_registry.py
projects/polymarket/polyquantbot/state/PROJECT_STATE.md
projects/polymarket/polyquantbot/state/WORKTODO.md
projects/polymarket/polyquantbot/state/CHANGELOG.md
```

---

## 4. What Is Working

- All 12 P8-B tests pass: CR-13..CR-22 (12 test cases including 3 parametrized) (12/12)
- All 23 P8-A tests pass: CR-01..CR-12 (23 test cases) — no regressions (23/23)
- Total: 35/35 passing
- `CapitalRiskGate.evaluate()` rejects on kill_switch, idempotency, non-positive edge, drawdown breach, exposure cap, daily loss limit
- `CapitalRiskGate.evaluate()` allows signal when all conditions clear in PAPER mode
- `CapitalRiskGate.evaluate()` raises `CapitalModeGuardError` in LIVE mode when any gate is off
- `enrich_candidate()` replaces 0.0 fields with provider values; original frozen candidate unchanged
- Enriched candidate with drawdown > 0.08 is rejected by `WalletSelectionPolicy._risk_ok()` (CR-22)
- `OrchestratorService` accepts optional `WalletFinancialProvider`; no breaking change to existing callers
- `PaperRiskGate` and all existing server tests unchanged

---

## 5. Known Issues

- `CapitalRiskGate` is not yet wired into the runtime execution path — `PaperBetaWorker` still uses `PaperRiskGate`; replacement wiring is P8-C
- `WalletFinancialProvider` has no live-data implementation — P8-C deliverable (requires market data feed)
- `PortfolioStore.unrealized_pnl` still uses `current_price` from paper_positions — live mark-to-market is P8-C
- `CapitalRiskGate.status()` Telegram surface not yet wired to a command — deferred to P8-D operator visibility lane
- `WalletCandidate.financial_fields_zero` boundary is `NEEDS_HARDENING` (not `SAFE_AS_IS`) until a live provider is injected

---

## 6. What Is Next

- WARP•SENTINEL MAJOR validation required before merge
- P8-C: Live execution readiness audit (§52) — wire `CapitalRiskGate` into `PaperBetaWorker` runtime, replace `price_updater` stub, implement `WalletFinancialProvider` backed by portfolio store, wire `allow_real_settlement`; clears `EXECUTION_PATH_VALIDATED` gate
- P8-D: Security + observability hardening (§53) — per-user capital isolation, audit log, production alerting, wire `CapitalRiskGate.status()` to Telegram; clears `SECURITY_HARDENING_VALIDATED` gate
- P8-E: Capital validation + claim review (§54) — dry-run, staged rollout, docs sign-off; sets `CAPITAL_MODE_CONFIRMED=true`

---

## Metadata

- **Validation Tier:** MAJOR
- **Claim Level:** NARROW INTEGRATION (risk gate + candidate wiring — no runtime path, no live data provider)
- **Validation Target:** §51 risk controls hardening — CapitalRiskGate evaluate contract + WalletFinancialProvider enrichment wiring (CR-13..CR-22)
- **Not in Scope:** Runtime wiring, live market data, settlement path, per-user isolation — all deferred to P8-C through P8-E
- **Suggested Next Step:** WARP•SENTINEL MAJOR validation; P8-C after merge
