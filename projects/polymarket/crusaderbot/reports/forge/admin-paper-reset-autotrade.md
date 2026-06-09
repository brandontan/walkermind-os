# WARP•FORGE Report — admin-paper-reset-autotrade

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Admin panel per-user paper-reset and auto-trade toggle
**Not in Scope:** Live-mode user reset, Telegram bot, risk gate, scanner, CLOB integration
**Suggested Next Step:** WARP🔹CMD review → merge → Fly.io deploy

---

## 1. What Was Built

Two new operator controls added to the WebTrader admin panel:

**Auto-trade ON/OFF toggle** — operator can flip per-user `auto_trade_on` flag from the admin drawer without touching the database directly. Calls the existing `set_auto_trade()` function (SSE-aware) via the PATCH `/admin/users/{user_id}` endpoint.

**Paper reset** — new `POST /admin/users/{user_id}/paper-reset` endpoint. Deletes all paper positions, orders, fills (FK cascade), portfolio_snapshots, and ledger entries for a user. Resets wallet balance to $1,000 USDC. Inserts a seed ledger entry (`type=deposit, note="admin reset"`). Returns a summary count of deleted rows. Blocked for live-mode users (HTTP 400).

---

## 2. Current System Architecture

No architecture change. The two features plug into the existing WebTrader backend router pattern:
- Auto-trade toggle reuses `set_auto_trade()` from `users.py` (already SSE-aware)
- Paper reset runs as a single DB transaction in the request handler; no new domain module needed
- Frontend: both controls live inside `AdminUserDrawer` modal, guarded by confirmation state

Rate-limited via existing `per_user_rate_limit` decorator (10 calls / window for paper-reset).

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` — added `auto_trade_on: Optional[bool]` to `AdminUserUpdate`; added `AdminPaperResetResult` schema
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `admin_user_update` extracts and applies `auto_trade_on`; new `admin_paper_reset` endpoint
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` — added `AdminPaperResetResult` interface, `auto_trade_on` to `AdminUserPatch`, `paperResetUser` call
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AdminUserDrawer.tsx` — auto-trade toggle button + Danger Zone paper-reset section with confirmation modal
- `projects/polymarket/crusaderbot/tests/test_admin_console.py` — 5 new hermetic tests appended

**Created:** this report

---

## 4. What Is Working

- PATCH `/admin/users/{user_id}` now accepts and applies `auto_trade_on: bool`
- Explicit `null` for `auto_trade_on` is rejected with HTTP 400 (same pattern as existing NOT NULL fields)
- POST `/admin/users/{user_id}/paper-reset` transactionally resets paper state and returns row counts
- Live-mode users are blocked from paper-reset (HTTP 400)
- Missing user returns HTTP 404 for both endpoints
- Admin drawer shows "Auto Trade ON / OFF" toggle buttons alongside existing Pause/Resume controls
- Danger Zone section shows reset button → confirmation prompt → executes reset → shows result summary
- All 56 tests pass (51 pre-existing + 5 new)

---

## 5. Known Issues

None. Pre-existing TypeScript module-not-found errors in the cloud environment (missing `node_modules`) are environment-only — not introduced by this task.

---

## 6. What Is Next

- WARP🔹CMD review and merge decision
- Fly.io deploy to activate both features on running instance
- Optional: add paper-reset to WORKTODO audit log after first field use
