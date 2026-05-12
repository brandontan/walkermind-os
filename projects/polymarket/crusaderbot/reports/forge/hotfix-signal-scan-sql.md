# WARP•FORGE Report — hotfix-signal-scan-sql

**Branch:** WARP/HOTFIX-SIGNAL-SCAN-SQL
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** pnl_insights SQL query correctness + emergency handler idempotency
**Not in Scope:** signal scan pipeline, execution engine, risk gate, trading logic

---

## 1. What Was Built

Two targeted bug fixes sourced from live Sentry events:

**Bug 1 — CRITICAL (Sentry #1): `FILTER specified, but abs is not an aggregate function`**

Location: `projects/polymarket/crusaderbot/bot/handlers/pnl_insights.py:113–115`

The `avg_loss` column in the `_fetch_insights` query used:
```sql
COALESCE(ABS(AVG(pnl_usdc)) FILTER (WHERE ...), 0)
```
PostgreSQL's `FILTER` clause is only valid on aggregate functions. `ABS()` is a scalar
function wrapping `AVG()`, so the parser saw `ABS(...) FILTER (...)` and raised
`WrongObjectTypeError`. Fix: move the `ABS()` wrapper to outside the `FILTER` clause
so `FILTER` attaches to `AVG()`:
```sql
COALESCE(ABS(AVG(pnl_usdc) FILTER (WHERE ...)), 0)
```

**Bug 2 — MINOR (Sentry #2): `Message is not modified`**

Location: `projects/polymarket/crusaderbot/bot/handlers/emergency.py`

`emergency_callback` called `q.edit_message_text()` unconditionally. Double-clicking any
emergency button (or navigating back to the current screen) triggered Telegram's
`BadRequest: Message is not modified` error — not a crash, but noisy in Sentry.

Fix: introduced a `_safe_edit()` helper that wraps all five `edit_message_text` calls
in the callback. Swallows `"Message is not modified"` silently; re-raises all other
`BadRequest` variants so real errors are not hidden.

---

## 2. Current System Architecture

No architecture change. Both fixes are surgical edits within existing handlers.

Pipeline (unchanged):
```
DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING
```

Affected layer: Telegram bot surface (MONITORING / UI layer). No changes to execution,
risk gate, signal scan, or database schema.

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/bot/handlers/pnl_insights.py`
  — line 113: moved `)` closing `ABS(` to after FILTER clause
- `projects/polymarket/crusaderbot/bot/handlers/emergency.py`
  — added `from telegram.error import BadRequest`
  — added `_safe_edit()` helper (lines ~39–47)
  — replaced 5× `q.edit_message_text(...)` with `_safe_edit(q, ...)`

Created:
- `projects/polymarket/crusaderbot/reports/forge/hotfix-signal-scan-sql.md` (this file)

---

## 4. What Is Working

- `_fetch_insights` SQL query now uses valid PostgreSQL aggregate filter syntax.
  `ABS(AVG(pnl_usdc) FILTER (WHERE ...))` is valid — FILTER on aggregate, ABS on result.
- `SUM(ABS(pnl_usdc)) FILTER (WHERE ...)` at line 101 was already valid and untouched.
- All five `emergency_callback` edit paths are now guarded against no-op edits.
- `BadRequest` variants other than `"Message is not modified"` are still re-raised.

---

## 5. Known Issues

None introduced. Existing deferred issues unchanged.

---

## 6. What Is Next

- WARP🔹CMD review + merge decision for this PR.
- After merge: Sentry #1 (WrongObjectTypeError) and Sentry #2 (BadRequest) should
  stop firing. Verify in Sentry within one hour of deploy.
- Sentry #3 (NetworkError httpx) is a Telegram network blip — no code fix needed.

---

**Suggested Next Step:** WARP🔹CMD review → merge → confirm Sentry issues resolved.
