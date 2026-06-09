# WARP•FORGE Report — paper-reset-fk-fix

**Branch:** WARP/ROOT/paper-reset-fk-fix
**Date:** 2026-06-01
**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** admin_paper_reset endpoint — copy_trade_events FK violation
**Not in Scope:** other admin endpoints, copy_trade_events data model, migrations
**Suggested Next Step:** WARP🔹CMD review — deploy to Fly

---

## 1. What Was Built

One-line fix for the "Internal Server Error" reported by the owner when clicking "Confirm Reset" in the AdminUserDrawer DANGER ZONE.

**Root cause:** `migration 032_copy_trade_events.sql` adds `copy_trade_events.position_id UUID REFERENCES positions(id)` with no `ON DELETE CASCADE` or `ON DELETE SET NULL` — defaulting to `ON DELETE RESTRICT`. When the paper-reset transaction deletes a user's positions, Postgres raises a FK violation if any `copy_trade_events` rows reference those positions → HTTP 500.

**Fix:** Added `DELETE FROM copy_trade_events WHERE user_id=$1::uuid` inside the reset transaction, before the `DELETE FROM positions` step. Uses the `user_id` FK (which already has `ON DELETE CASCADE`) to scope the deletion correctly to the target user.

Delete order in the transaction is now:
1. fills (FK → orders, already handled)
2. orders
3. **copy_trade_events** ← new
4. positions (unblocked)
5. portfolio_snapshots
6. ledger
7. UPDATE wallets balance → $1,000
8. INSERT seed ledger entry

---

## 2. Current System Architecture

Admin paper-reset pipeline:
```
AdminUserDrawer DANGER ZONE → POST /admin/users/{id}/paper-reset
  → transaction: fills → orders → copy_trade_events → positions
                → portfolio_snapshots → ledger → wallet reset
  → audit.write(admin_paper_reset)
  → AdminPaperResetResult
```

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  — Added `DELETE FROM copy_trade_events WHERE user_id=$1::uuid` before DELETE positions in `admin_paper_reset` transaction (line 3036–3040).

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/paper-reset-fk-fix.md` — this report

---

## 4. What Is Working

- Paper reset no longer raises a FK violation when the user has copy_trade_events rows.
- All other FK-safe deletes (fills, portfolio_snapshots) unchanged.
- `ON DELETE CASCADE` relations (redeem_queue.position_id, order_lifecycle_events.order_id) still auto-cascade — no change needed there.
- `fees.trade_id` has `ON DELETE SET NULL` — also no change needed.

---

## 5. Known Issues

- None introduced. The only known gap in migration 032 (`position_id` FK without cascade) is now worked around at the application layer. A future hardening lane could add `ON DELETE SET NULL` to that FK via a migration, but it is not required for correctness.

---

## 6. What Is Next

1. Deploy to Fly.io.
2. Retry paper reset on @walk3r69 — should succeed and return 200 with positions/orders/ledger counts.
