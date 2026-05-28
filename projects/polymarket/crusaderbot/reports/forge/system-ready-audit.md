# WARP•R00T System-Ready Audit — LIVE & PAPER posture

Date: 2026-05-28
Role: WARP•R00T
Lane: 1 / 3 (audit → paper-default-hardening → live-readiness-final)
Tier: MINOR (read-only audit, no code change)
Claim Level: FOUNDATION

---

## 1. What was audited

End-to-end posture of CrusaderBot for two concurrent operating modes:

- **PAPER** — every new user MUST default to paper trading; no real capital path.
- **LIVE** — owner-only, gated by 5 activation flags + per-user `trading_mode='live'` flip; on-chain capital paths wired (#1402, #1403, #1408).

Scope: activation guards, execution router, live-engine gate, new-user
creation paths (Telegram + WebTrader + admin/API), LIVE-flip flow, kill
switch, custody dispatcher.

## 2. Current system architecture (verified PAPER-safe)

```
NEW USER  ─►  upsert_user (Telegram)   ──┐
              auth.signup_email (Web)  ──┼─► users INSERT (role='user')
              get_or_create_user (API) ──┘     │
                                               ▼
                                       user_settings INSERT
                                       (schema default: trading_mode='paper')
                                               │
                                               ▼
SIGNAL ─► strategy ─► risk gate ─► chosen_mode (paper unless 8-gate flip)
                                               │
                                               ▼
                              execution.router.execute()
                                ├─ chosen_mode='paper' ─► paper engine
                                └─ chosen_mode='live'  ─► assert_live_guards
                                                              │
                                          ┌───────────────────┴── all 8 PASS
                                          ▼
                                  live.execute() ──► CLOB
                                  (USE_REAL_CLOB=True required)
                                          ▲
                                          └── any FAIL ─► audit-log CRITICAL
                                                          + fallback to paper
```

Five owner-only activation guards, all currently `false`:
`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`,
`RISK_CONTROLS_VALIDATED`, `SECURITY_HARDENING_VALIDATED`
(`config.py:174-182`, mirrored in `fly.toml:24-28`).

## 3. Files inspected (read-only)

- `projects/polymarket/crusaderbot/config.py:132-182,376-396`
- `projects/polymarket/crusaderbot/fly.toml:24-28`
- `projects/polymarket/crusaderbot/domain/execution/router.py:1-100`
- `projects/polymarket/crusaderbot/domain/execution/live.py:1-80`
- `projects/polymarket/crusaderbot/domain/activation/live_checklist.py`
- `projects/polymarket/crusaderbot/services/user_service.py`
- `projects/polymarket/crusaderbot/users.py:60-150,255-275,320-340`
- `projects/polymarket/crusaderbot/webtrader/backend/auth.py:120-155`
- `projects/polymarket/crusaderbot/bot/handlers/activation.py:120-260`
- `projects/polymarket/crusaderbot/bot/handlers/setup.py:300-330`
- `projects/polymarket/crusaderbot/bot/handlers/live_gate.py:180-220`
- `projects/polymarket/crusaderbot/migrations/001_init.sql:62-75`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/LIVE_READINESS.md`

## 4. What is working (verified)

**Activation posture (PASS)**

- All 5 LIVE guards default `False` at both `config.py` and `fly.toml`.
- `CUSTODY_MODE='eoa'`, `USE_BUILDER_RELAYER=False`, `SWEEP_ONCHAIN_ENABLED=False`,
  `USE_REAL_CLOB=False` — every capital-touching path inert by default.

**PAPER-default for new users (PASS)**

- `user_settings.trading_mode VARCHAR(10) NOT NULL DEFAULT 'paper'`
  (`migrations/001_init.sql:73`).
- Telegram new-user path `users.py:upsert_user` INSERTs `user_settings (user_id)`
  → schema default applies (lines 75–79).
- WebTrader email-signup path `webtrader/backend/auth.py:141` INSERTs `users`
  then calls `_bootstrap_new_user`; user_settings row created lazily on first
  `get_settings_for` call (`users.py:267-273`) — schema default applies.
- `services/user_service.py:get_or_create_user` (admin/API) INSERTs `users`
  only — user_settings row created lazily by `get_settings_for`.
- `_bootstrap_new_user` configures presets + `auto_trade_on=FALSE`; never
  writes `trading_mode='live'`.

**LIVE-flip path (PASS — hard-gated)**

- Three entry points: `/setup` mode picker, `/enable_live` button, dashboard
  toggle. All three route through `live_checklist.evaluate()` (8 gates: 5
  activation flags + tier + 2FA + active subaccount + configured strategy).
- Typed `CONFIRM` reply required (`activation.text_input`); arbitrary text
  cancels. Defense-in-depth re-evaluates checklist on the CONFIRM reply
  (`live_gate.py:191-199`).
- `setup.py:308-322` fall-through to plain `update_settings(trading_mode='live')`
  is unreachable in practice: `_ensure_user` already proved
  `update.effective_user` is present, so `trading_mode_live_pending_confirm`
  cannot return its single `False` branch.

**Execution router (PASS — defense in depth)**

- `domain/execution/router.py:33-50` calls `live_engine.assert_live_guards`
  before live submission; on raise logs `GUARD_BYPASS_ATTEMPT` at CRITICAL
  and audit-writes `live_blocked_fallback_paper`, then routes to paper.
- `live.execute` re-checks all 5 flags + `USE_REAL_CLOB` + `role=='admin'`
  + `trading_mode=='live'` (`live.py:50-80`).
- Post-submit errors (CLOB accepted) skip paper fallback and re-raise so the
  operator reconciles manually.

**On-chain capital paths (PASS — guarded OFF)**

- Withdraw `integrations/polygon_usdc.py:transfer_usdc()` (#1402, SENTINEL 94).
- Sweep `sweep_usdc_to_master()` + `scheduler._sweep_deposits_onchain` (#1403,
  SENTINEL 94).
- Custody dispatcher `wallet/custody.py` + `SafeCustody` (#1408, SENTINEL 94).
- All triple/double-gated, default OFF; PAPER unaffected.

## 5. Findings (no current LIVE/PAPER risk; Lane 2 hardening candidates)

### F-MEDIUM-1 — PAPER default depends solely on schema column default

**Problem:** Every new-user code path relies on
`user_settings.trading_mode NOT NULL DEFAULT 'paper'` (migration 001:73). No
INSERT statement writes the column explicitly. A future migration that
ALTERs the default would silently flip every new user to live.

**Root cause:** Implicit defense; no code-level enforcement.

**Risk:** MEDIUM (no current impact — schema default is correct; brittleness
only).

**Technical impact:** Hypothetical only — would require a future operator
mistake. Would not bypass `assert_live_guards` (separate defense layer)
but would route signals through the live engine, requiring router
fallback every signal.

**Recommended solution (Lane 2):** Make `trading_mode='paper'` explicit in
both `users.py:76` and `webtrader/backend/auth.py` bootstrap, plus a
regression test pinning the invariant.

**Files affected (Lane 2 candidates):** `users.py`, `webtrader/backend/auth.py`,
new `tests/test_paper_default_invariant.py`.

### F-LOW-1 — silent exception swallow in WebTrader signup

**Problem:** `webtrader/backend/auth.py:151-152`:

```python
try:
    await _bootstrap_new_user(row["id"])
except Exception:
    pass  # bootstrap is best-effort; user row already created
```

Violates CLAUDE.md HARD RULE: "No silent failures — every exception caught
and logged."

**Root cause:** Best-effort bootstrap, no observer.

**Risk:** LOW (bootstrap failure leaves a user without wallet/seed; surfaces
on next API call via lazy `get_settings_for`).

**Recommended solution (Lane 2):** Replace `pass` with `logger.exception(...)`.

**Files affected (Lane 2):** `webtrader/backend/auth.py:151`.

### F-LOW-2 — no regression test for paper-stickiness

**Problem:** Existing `tests/test_users.py` proves paper-capital seed runs,
but no test pins the invariant "new user defaults to PAPER even after
`ENABLE_LIVE_TRADING=True`."

**Risk:** LOW (would only catch regressions, not current bugs).

**Recommended solution (Lane 2):** Add a hermetic test asserting the schema
default + explicit INSERT path both produce `trading_mode='paper'` regardless
of the global guard state.

## 6. What is next

- **Lane 2** — `WARP/ROOT/paper-default-hardening`: implement F-MEDIUM-1 +
  F-LOW-1 + F-LOW-2. Belt-and-suspenders defense, ~3 files + 1 test file.
- **Lane 3** — `WARP/ROOT/live-readiness-final`: state-file sync (no code).
  Update `PROJECT_STATE.md` / `LIVE_READINESS.md` / `PRODUCTION_CHECKLIST.md`
  / `WORKTODO.md` / `CHANGELOG.md` to reflect audit completion.

---

## Verdict

**System IS engineering-ready for LIVE+PAPER co-operation.** Every LIVE path
is gated by 5 owner-only flags, every new user is forced to PAPER by schema
default, every LIVE-flip requires an 8-gate checklist + typed CONFIRM, and
the execution router falls back to paper + audit-logs CRITICAL on any guard
bypass attempt. Three findings noted are brittleness hardening, not current
risks. Final go-live remains owner-operational per
`state/LIVE_READINESS.md` "Final go-live sequence."

Validation Tier: MINOR
Claim Level: FOUNDATION
Validation Target: PAPER-default invariant + LIVE-guard chain end-to-end
Not in Scope: any code change (audit only); Builder-relayer live test
  (requires owner-side creds); fly.io deploy
Suggested Next Step: WARP🔹CMD approves Lane 2 (paper-default-hardening)
  scope before code lane opens.
