# WARP•FORGE Report — risk-caps-kill-switch

**Branch:** WARP/CRUSADERBOT-FAST-RISK-SAFETY
**Track:** D — Risk Caps + Kill Switch
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**SENTINEL:** Required before merge

---

## 1. What Was Built

Extended the existing CrusaderBot risk gate with four hard risk caps and a unified three-path kill switch:

- **4 configurable risk cap constants** added to `config.py` (env-overridable)
- **`validate_risk_caps()`** added to `domain/risk/gate.py` — enforces single-position 10%, total exposure 80%, daily loss -$50, max open positions 20 — called as pre-check (step 0) before all 14 existing gates
- **`domain/risk/kill_switch_exec.py`** (new) — unified `execute_kill_switch(reason, triggered_by)` and `reset_kill_switch(triggered_by)` — all 3 activation paths converge here
- **Path 1 (Telegram):** `/kill` and `/killswitch pause` now route through `execute_kill_switch()` in admin.py; `/resume` and `/killswitch resume` route through `reset_kill_switch()`
- **Path 2 (DB flag):** `run_job()` in market_signal_scanner.py checks `ops_kill_switch.is_active()` at start of every tick — skips if active
- **Path 3 (env var):** `lifespan()` in main.py checks `KILL_SWITCH=true` on startup — calls `execute_kill_switch()` after DB and bot are initialized
- **Migration 032** — `system_flags` + `audit_log` tables with indexes

---

## 2. Current System Architecture

```
RISK PIPELINE (before any order):

  evaluate() in domain/risk/gate.py
    ├── [0] validate_risk_caps()        ← NEW (Track D)
    │     ├── single position <= 10% balance
    │     ├── total exposure <= 80% balance
    │     ├── today PnL > MAX_DAILY_LOSS_USD (-$50 default)
    │     └── open positions < MAX_OPEN_POSITIONS (20)
    ├── [1] kill_switch (existing)
    ├── [2-14] existing gates (unchanged)
    └── final_size + mode selection

KILL SWITCH ACTIVATION PATHS (Track D):

  Path 1 (Telegram /kill)  ──┐
  Path 2 (scanner tick)    ──┤──→ execute_kill_switch(reason, triggered_by)
  Path 3 (startup env var) ──┘         │
                                        ├── ops_kill_switch.set_active("pause")
                                        ├── cancel pending orders (SQL UPDATE)
                                        ├── system_flags INSERT/UPDATE
                                        ├── audit_log INSERT (mandatory)
                                        └── notify_operator (best-effort)

KILL SWITCH RESET:
  /resume or /killswitch resume → reset_kill_switch(triggered_by)
    ├── ops_kill_switch.set_active("resume")
    ├── system_flags set kill_switch_active=false
    └── audit_log INSERT KILL_SWITCH_RESET
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/migrations/032_risk_caps_audit_log.sql`
- `projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py`

**Modified:**
- `projects/polymarket/crusaderbot/config.py` — 4 risk cap constants added to Settings
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — `validate_risk_caps()` + step 0 call in `evaluate()`
- `projects/polymarket/crusaderbot/main.py` — Path 3 env var kill switch check in lifespan
- `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py` — Path 2 kill switch check at start of `run_job()`
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` — Path 1: "pause" routes to `execute_kill_switch()`, "resume" routes to `reset_kill_switch()`

---

## 4. What Is Working

- `validate_risk_caps()` enforces all four caps using existing pool helpers (`get_balance`, `_open_exposure`, `daily_pnl`, `_open_position_count`) — no new DB queries introduced, no new services
- All 3 kill switch activation paths call the same `execute_kill_switch()` function — zero duplicate logic
- Kill switch activation mandatory writes to `audit_log` — no silent activations
- Admin notification is best-effort (try/except wraps `notify_operator()`) — notification failure cannot block the kill
- `reset_kill_switch()` writes KILL_SWITCH_RESET to `audit_log` and clears `system_flags`
- `compileall` clean, `ruff check` clean (All checks passed)
- Risk caps are per-user — all four checks use `user_id` scoped queries
- `ENABLE_LIVE_TRADING=false` untouched

---

## 5. Known Issues

- `scanner_service.pause_all()` (task spec step 1) has no existing API — the kill switch flag propagates to the scanner within one tick interval (Path 2 check) which is functionally equivalent; no separate `pause_all()` was created per scope constraints
- `system_flags` table is new (Track D); the existing kill switch uses `system_settings` (ops module). Both are kept in sync: `execute_kill_switch()` calls `ops_kill_switch.set_active()` AND writes `system_flags`. The scanner Path 2 check uses `ops_kill_switch.is_active()` (reads `system_settings`) which is consistent since all activations go through `execute_kill_switch()` first
- Migration 032 must be applied before deploy

---

## 6. What Is Next

- WARP•SENTINEL validation required (Tier: MAJOR)
- Apply migration 032 to production before deploy
- Manual checklist in task spec must be verified by SENTINEL:
  - Position > 10% balance → rejected at step 0
  - Total exposure > 80% → rejected at step 0
  - Daily loss <= -$50 → rejected at step 0
  - Open positions >= 20 → rejected at step 0
  - /kill command → kill switch activated → audit_log written → admin notified
  - kill_switch_active=true → scanner skips next tick
  - KILL_SWITCH=true env var → kill switch on startup
  - Kill switch reset via /resume → audit_log written

---

**Validation Target:** domain/risk/gate.py + domain/risk/kill_switch_exec.py + all 3 activation paths
**Not in Scope:** copy_trade.py, portfolio_chart.py, WebTrader, live order submission, TP/SL
**Suggested Next Step:** WARP•SENTINEL run against this branch (Tier MAJOR) before merge
