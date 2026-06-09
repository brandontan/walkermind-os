# WARP•R00T paper-default-hardening — Lane 2/3

Date: 2026-05-28
Role: WARP•R00T (FORGE-style)
Lane: 2 / 3 (audit → **paper-default-hardening** → live-readiness-final)
Tier: STANDARD
Claim Level: NARROW INTEGRATION

---

## 1. What was built

Belt-and-suspenders enforcement of the **PAPER-default-for-new-users** invariant
identified in Lane 1 (`reports/forge/system-ready-audit.md`):

- **F-MEDIUM-1** — every `INSERT INTO user_settings` in production code now
  writes `trading_mode='paper'` **explicitly** instead of relying solely on
  the schema column default. Two write sites in `users.py`
  (Telegram new-user + lazy-create in `get_settings_for`) and one new write
  site in `webtrader/backend/auth.py` (email-signup, parity with Telegram).
- **F-LOW-1** — `webtrader/backend/auth.py:signup_email` no longer silently
  `pass`-es on `_bootstrap_new_user` exceptions; replaced with
  `logger.exception(...)` per CLAUDE.md HARD RULE "no silent failures."
- **F-LOW-2** — new hermetic regression suite
  `tests/test_paper_default_invariant.py` pins the invariant at two layers:
  (a) functional test asserting the INSERT call shape and lazy-create path,
  (b) source-level regex guard that fails if any future edit drops the
  literal `trading_mode='paper'` from a `user_settings` INSERT.

PAPER remains the only mode any user gets at creation, regardless of
`ENABLE_LIVE_TRADING`'s value. The LIVE-flip path (8-gate
`live_checklist.evaluate()` + typed CONFIRM) is unchanged.

## 2. Current system architecture

```
upsert_user (Telegram)               ┐
auth.signup_email (WebTrader)        ┤── users INSERT (role='user')
                                     │── user_settings INSERT
                                     │     (user_id, trading_mode='paper')  ← explicit
                                     ▼
                              _bootstrap_new_user
                                (wallet + seed + auto_trade_on=FALSE)

get_settings_for (lazy path)
   missing row → INSERT (user_id, trading_mode='paper')  ← explicit
```

LIVE flip path (unchanged):

```
/setup picker | /enable_live | dashboard toggle
        │
        ▼
live_checklist.evaluate()  (5 activation flags + tier + 2FA + subaccount + strategy)
        │ all pass
        ▼
type CONFIRM  →  defense-in-depth re-check  →  UPDATE user_settings SET trading_mode='live'
```

## 3. Files created / modified

- `projects/polymarket/crusaderbot/users.py` — explicit `trading_mode='paper'`
  in two user_settings INSERTs (lines 75-83, 267-275).
- `projects/polymarket/crusaderbot/webtrader/backend/auth.py` — added
  `logging` import + `logger`; explicit user_settings INSERT inside the
  signup transaction; replaced silent `except Exception: pass` with
  `logger.exception(...)` (lines 4, 16-18, 151-172).
- `projects/polymarket/crusaderbot/tests/test_paper_default_invariant.py`
  — **new** hermetic test file (5 tests): upsert_user INSERT shape,
  get_settings_for lazy INSERT shape, users.py source regex guard,
  webtrader source regex guard, no-silent-pass guard.

## 4. What is working

- Targeted regression: `tests/test_users.py` + `tests/test_paper_default_invariant.py` →
  10 passed.
- Full suite: `pytest projects/polymarket/crusaderbot/tests/ -q` → **1859 passed,
  1 skipped, 0 failures**.
- `python -m py_compile` clean on both modified modules.
- `ruff check` clean on all touched files.
- New tests intentionally fail-closed if a future edit removes the explicit
  `'paper'` write or restores the silent `pass`.

## 5. Known issues

- `services/user_service.py:get_or_create_user` remains orphaned (no live
  callers; only a comment reference at `services/redeem/redeem_router.py:162`).
  Not modified in this lane — pure dead code, cleanup deferred to a future
  lane. The lazy-create branch in `get_settings_for` already covers any
  hypothetical revival of this path.
- The schema column default (`migrations/001_init.sql:73`) is preserved as
  the outermost defense; only the implicit-only reliance is removed.

## 6. What is next

- **Lane 3** — `WARP/ROOT/live-readiness-final`: state-file sync
  (`PROJECT_STATE.md`, `LIVE_READINESS.md`, `PRODUCTION_CHECKLIST.md`,
  `WORKTODO.md`, `CHANGELOG.md`) reflecting Lanes 1 + 2 completion and
  re-stating the owner-only final go-live sequence. No code change.

---

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: PAPER-default invariant at INSERT call shape + source level + lazy-create branch
Not in Scope: schema migration changes; LIVE-flip flow; `services/user_service.py` cleanup
Suggested Next Step: WARP🔹CMD review → merge → open Lane 3.
