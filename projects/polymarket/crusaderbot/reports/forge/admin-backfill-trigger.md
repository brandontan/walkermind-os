# admin-backfill-trigger — mobile-runnable deposit-wallet backfill

Role: WARP•R00T | Branch: WARP/root-admin-backfill-trigger
Date: 2026-06-11 Asia/Jakarta
Origin: live go-live support (owner funding flow). Gap found in prod: `backfill_deposit_wallets()` was referenced only as a boot-time WARNING (`main.py:89-107`) with NO trigger — no endpoint, no scheduler job, no admin control. An owner on mobile (no Fly SSH console) could never run it, so `wallets.polymarket_deposit_wallet` stayed NULL, which blocks (a) the deposit watcher from watching a user's own Polymarket deposit wallet and (b) per-user live execution (funder resolution).

## 1. What was built

A WebTrader admin-console trigger for the existing `backfill_deposit_wallets()` resolver:

- **Backend** `POST /api/web/admin/backfill-deposit-wallets` (`webtrader/backend/router.py`): admin-gated (`_AdminUser`), rate-limited 5/min (each row drives an SDK round-trip), audited (`admin_backfill_deposit_wallets`). Returns `{scanned, filled, skipped, ok}`. `ok` is False ONLY on the SDK-abort shape (`scanned>0 ∧ filled==0 ∧ skipped==0`) so an empty fill from a runtime without the Polymarket SDK is not misread as "nothing to do". Moves NO funds — resolves + stores wallet addresses only.
- **Frontend** `webtrader/frontend/src/lib/api.ts` `backfillDepositWallets()` + `pages/AdminPage.tsx` "Maintenance" section with a one-tap **Backfill deposit wallets** button, busy state, and a result line (scanned/filled/skipped or the SDK-abort hint).

The underlying `wallet/deposit_wallet.backfill_deposit_wallets()` is unchanged — idempotent (only NULL rows), sequential (#1730 advisory), fail-soft per row.

## 2. Current system architecture (relevant slice)

Operator (mobile) → WebTrader admin console → POST /admin/backfill-deposit-wallets → `backfill_deposit_wallets()` (decrypt HD pk → Polymarket SDK resolve → write `polymarket_deposit_wallet`) → audit. Downstream: deposit watcher (`scheduler._build_watched_addresses`) now has the user's Polymarket deposit wallet in its watch set; per-user execution (`domain/execution/per_user_clob`) can assert/resolve the funder.

## 3. Files created / modified

- projects/polymarket/crusaderbot/webtrader/backend/router.py — modified (+1 endpoint)
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts — modified (+1 client method)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx — modified (Maintenance section + handler/state)
- projects/polymarket/crusaderbot/tests/test_admin_backfill_trigger.py — created (5 tests)
- projects/polymarket/crusaderbot/reports/forge/admin-backfill-trigger.md — this report
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md, state/CHANGELOG.md — synced

## 4. What is working

- 5 hermetic tests: happy path ok=True + audited; partial-skips ok; nothing-to-do (scanned 0) ok; SDK-abort shape ok=False; audit payload = summary.
- Full suite **3418 passed / 11 skipped** (+5 on 3413). ruff clean. Frontend tsc + vite build clean.
- `_require_admin` 403 gating already proven in test_admin_console (shared dependency).

## 5. Known issues

- The backfill needs the Polymarket SDK present in the Fly runtime; if absent the run aborts at row 1 and the button reports `ok=false` with the abort hint (no silent success). The SDK is in `pyproject` (`polymarket-client`), so prod has it.
- Whether a user's EXISTING (already-sent) Polymarket deposit then flips gate 4 depends on the deposit watcher being alive and its cold-start lookback (`DEPOSIT_SCAN_LOOKBACK_BLOCKS`, ~28h) covering the deposit block — separate from this lane (watcher health is an infra item).

## 6. What is next

- Deploy (CD on merge). Operator taps Backfill in the admin console once the deposit watcher is confirmed ticking.

Validation Tier   : STANDARD (admin ops trigger; no capital/risk/order/guard change; no fund movement)
Claim Level       : NARROW INTEGRATION (admin endpoint + button around an existing idempotent resolver)
Validation Target : endpoint delegates to backfill_deposit_wallets, admin-gated, audited, ok-flag heuristic, button wiring
Not in Scope      : backfill_deposit_wallets internals (unchanged), deposit watcher health, risk/guards/order flow
Suggested Next    : WARP🔹CMD review → merge on CI green (WARP•R00T authority)
