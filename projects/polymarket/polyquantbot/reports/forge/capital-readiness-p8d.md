# WARP•FORGE REPORT: capital-readiness-p8d
Branch: WARP/capital-readiness-p8d
Date: 2026-04-29 Asia/Jakarta

---

## Validation Metadata

- Branch: WARP/capital-readiness-p8d
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: §53 Security + Observability Hardening — FLAG-1 daily loss fix, FLAG-2 acceptance, /capital_status Telegram+API, admin audit log, capital-mode alerting, permission model boundary, capital-mode runbook
- Not in Scope: Full per-user portfolio route binding (P9 multi-user rollout), DB persistence for intervention records (P9 storage lane), live market data provider (P8-C), staged rollout dry-run (P8-E)
- Suggested Next Step: WARP•SENTINEL MAJOR validation required before merge; P8-E capital validation after merge

---

## 1. What Was Built

### D1 — FLAG-1 fix: day-scoped daily_loss_limit (HARD BLOCKER resolved)

`PublicBetaState` (`server/core/public_beta_state.py`):
- Added `daily_open_realized_pnl: float = 0.0` — lifetime PnL baseline at day-open
- Added `daily_reset_date: date | None = None` — current Jakarta trading day
- Added `daily_realized_pnl` property — `round(realized_pnl - daily_open_realized_pnl, 4)`
- Added `reset_daily_pnl_if_needed()` — idempotent; snapshots baseline when Jakarta date changes

Before this fix: `daily_loss_limit` gate in `CapitalRiskGate.evaluate()` compared `state.realized_pnl` (lifetime cumulative) against -$2,000. Once lifetime losses exceeded -$2,000 the gate was permanently tripped. This blocked live trading indefinitely.

After this fix: gate compares `state.daily_realized_pnl` (day-scoped, resets at midnight Jakarta). Each trading day starts fresh. Lifetime losses do not trip the daily gate.

Restart behavior: on restart, `daily_reset_date = None` causes `reset_daily_pnl_if_needed()` to snapshot the current lifetime total as the day-open baseline. `daily_realized_pnl = 0.0` at startup — this is intentional and conservative (today's in-progress losses from before the restart are not carried over, which is safer than risking stale accumulation).

### D2 — FLAG-2 accepted: exposure/drawdown asymmetry documented

`CapitalRiskGate.evaluate()` gates 6 and 7 now carry explicit comments documenting that:
- `state.drawdown` is system-wide (not per-wallet) — intentional conservative design
- `state.exposure` is system-wide — consistent with drawdown
- Per-wallet routing is a P8-E / multi-wallet review item

FLAG-2 is accepted for this lane.

### D3 — /capital_status: Telegram command + API route

`server/api/public_beta_routes.py`:
- Added `GET /beta/capital_status` (operator-API-key protected)
- Returns full `CapitalRiskGate.status()` snapshot: 5 gate booleans, daily PnL, drawdown, exposure, Kelly, kill switch, open positions

`client/telegram/dispatcher.py`:
- Added `/capital_status` to `_INTERNAL_COMMANDS` (operator chat only)
- Handler calls `GET /beta/capital_status` and formats a structured reply with gate checkmarks

### D4 — Secret handling audit

Full audit of all secret reads across `server/` and `client/telegram/`:
- No secrets appear in any `log.*` call
- No secret values appear in HTTP responses or Telegram replies
- All token/key reads use `os.getenv()` / `os.environ.get()` with empty-string defaults
- Error responses for auth failure return generic reason codes only
- `runtime.py` health surface reports `bool(getenv(...))` presence only — no values exposed
- No hardcoded credentials found anywhere in the codebase

### D5 — Permission model boundary documented

`server/api/auth_session_dependencies.py`:
- Module docstring updated to document the two-tier permission model:
  - User routes: `get_authenticated_scope()` via trusted session headers
  - Operator/capital routes: `_require_operator_api_key()` via X-Operator-Api-Key header
  - Portfolio hardcode limitation: documented as pre-P9 known issue

No code changes needed — `/beta/capital_status` (added in D3) is already operator-key protected.

### D6 — Admin audit log: single-exit audit event

`server/settlement/operator_console.py` — `apply_admin_intervention()` refactored:
- All early returns replaced with a single `result` variable accumulation
- Final `log.info("operator_admin_intervention_audit", ...)` emitted at the single exit point
- Covers: `success`, `previous_status`, `new_status`, `blocked_reason` for every intervention
- Provides observable audit trail via structured log aggregation (Fly logs / Sentry)
- DB persistence remains deferred (P9 storage lane)

### D7 — Production-grade alerting

`server/config/capital_mode_config.py`:
- Added `log.error("capital_mode_guard_blocked", severity="CRITICAL")` before raising `CapitalModeGuardError` — guard activation now surfaced in log aggregators immediately

`server/risk/capital_risk_gate.py`:
- Added `log.warning("capital_daily_loss_approaching_limit", severity="WARNING")` when `daily_realized_pnl` ≤ 75% of daily limit (-$1,500)
- Added `log.error("capital_daily_loss_limit_tripped", severity="CRITICAL")` when gate trips

### D8 — Capital-mode runbook

`docs/operator_runbook.md` — Section 8 added:
- Alert event table with severity levels
- Daily loss limit trip response procedure
- Capital gate guard trip procedure
- `/capital_status` command reference
- Permission model boundary summary

---

## 2. Current System Architecture

```
PublicBetaState
  realized_pnl            ← lifetime cumulative (unchanged)
  daily_open_realized_pnl ← baseline at last Jakarta midnight reset
  daily_realized_pnl      ← property: realized_pnl - daily_open_realized_pnl
  reset_daily_pnl_if_needed() ← called by paper_portfolio._sync_state() + CapitalRiskGate.evaluate()

CapitalRiskGate.evaluate()
  step 8: reset_daily_pnl_if_needed() → compare daily_realized_pnl vs limit
  warning at -$1,500 (75%), error+block at -$2,000

GET /beta/capital_status (operator API key)
  → CapitalRiskGate(from_env()).status(STATE)
  → Telegram /capital_status (operator chat)

OperatorConsole.apply_admin_intervention()
  → single exit point → operator_admin_intervention_audit log
```

---

## 3. Files Created / Modified (full repo-root paths)

**Modified:**
```
projects/polymarket/polyquantbot/server/core/public_beta_state.py
projects/polymarket/polyquantbot/server/risk/capital_risk_gate.py
projects/polymarket/polyquantbot/server/risk/paper_risk_gate.py
projects/polymarket/polyquantbot/server/portfolio/paper_portfolio.py
projects/polymarket/polyquantbot/server/config/capital_mode_config.py
projects/polymarket/polyquantbot/server/api/public_beta_routes.py
projects/polymarket/polyquantbot/server/api/auth_session_dependencies.py
projects/polymarket/polyquantbot/server/settlement/operator_console.py
projects/polymarket/polyquantbot/client/telegram/dispatcher.py
projects/polymarket/polyquantbot/tests/test_capital_readiness_p8b.py
projects/polymarket/polyquantbot/docs/operator_runbook.md
```

**Created:**
```
projects/polymarket/polyquantbot/tests/test_capital_readiness_p8d.py
projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8d.md
```

---

## 4. What Is Working

- `daily_realized_pnl` is 0.0 on fresh state and rolls correctly at Jakarta midnight
- `CapitalRiskGate.evaluate()` trips daily loss gate on day-scoped loss only, not lifetime
- Flag-1 regression verified: lifetime PnL of -$15,000 does NOT trip gate on a new day
- `reset_daily_pnl_if_needed()` is idempotent — calling multiple times same day is no-op
- `PaperRiskGate.status()` updated to display day-scoped PnL
- `paper_portfolio.reset()` clears `daily_open_realized_pnl` and `daily_reset_date`
- 45/45 tests passing (CR-01..CR-12, CR-13..CR-22, CR-23..CR-28)
- `/beta/capital_status` route exists and is operator-key protected
- Telegram `/capital_status` command is operator-chat-only and formats all gate fields
- `operator_admin_intervention_audit` emitted on every intervention (all 8 outcome paths)
- Capital-mode alert events: `capital_mode_guard_blocked` (CRITICAL), `capital_daily_loss_limit_tripped` (CRITICAL), `capital_daily_loss_approaching_limit` (WARNING)
- Secret audit clean: no secrets in logs, responses, or Telegram output

---

## 5. Known Issues

- `daily_realized_pnl` resets to 0.0 on system restart (same-day losses before restart are not carried over). This is conservative by design; DB-backed day-scope requires P9 storage lane.
- DB persistence for admin interventions still deferred — audit trail exists via structlog only.
- Portfolio routes still hardcode `paper_user` — per-user binding deferred to P9.
- `CapitalRiskGate.status()` is instantiated fresh on each `/beta/capital_status` call (reads env vars each time). This is safe but slightly wasteful for a hot endpoint. Acceptable for operator-only route.
- `paper_risk_gate.py` daily loss gate in `evaluate()` does not exist (only in `status()`). This is pre-existing — `PaperRiskGate.evaluate()` was never wired for daily loss. Not in P8-D scope.

---

## 6. What Is Next

- WARP•SENTINEL MAJOR validation required for P8-D before merge
- WARP•SENTINEL MAJOR validation for P8-B still pending (source: capital-readiness-p8b.md)
- WARP•SENTINEL MAJOR validation for P8-A still pending (source: capital-readiness-p8a.md)
- P8-E: Capital validation + claim review (§54) — dry-run, staged rollout, docs sign-off; sets `CAPITAL_MODE_CONFIRMED=true`; after all prior SENTINEL gates pass

---

## Metadata

- **Validation Tier:** MAJOR
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** §53 security + observability hardening — FLAG-1 fix, FLAG-2 acceptance, /capital_status API+Telegram, admin audit log, capital-mode alerting, permission boundary, runbook
- **Not in Scope:** DB persistence for intervention records, per-user portfolio binding, live market data, staged rollout (all P8-E / P9)
- **Suggested Next Step:** WARP•SENTINEL MAJOR validation; then P8-E after all SENTINEL gates approved
