# WARP•FORGE — Retire copy_targets Table

**Branch:** WARP/R00T-copy-targets-migration
**Date:** 2026-05-26 20:15 WIB
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION

---

## 1. What was built

Closed WARP-57 MEDIUM-4: retired the `copy_targets` legacy table by migrating all
remaining Python write/read sites to the canonical `copy_trade_tasks` table, and
adding migration 058 to backfill any remaining DB rows then DROP TABLE copy_targets.

Root cause of MEDIUM-4: the old `/copytrade add|remove|list` command path and the
legacy settings wizard (`setup.py`) still wrote to `copy_targets`, while the
production copy-trade scanner (`domain/copy_trade/repository.py`) and the MVP
handler (`bot/handlers/mvp/copy_wallet.py`) read from `copy_trade_tasks`. The two
tables were silently disconnected — `/copytrade add` entries were never executed.

## 2. Current system architecture

```
/copytrade add <wallet>  →  _insert_active_target()
                               └── INSERT INTO copy_trade_tasks (was copy_targets)
/copytrade remove <wallet> →  _legacy_deactivate_target()
                               └── UPDATE copy_trade_tasks SET status='paused'
/copytrade list            →  _legacy_list_active()
                               └── SELECT FROM copy_trade_tasks WHERE status='active'
setup.py copy target flow  →  copy_trade_tasks (list/add/remove)

copy-trade scanner reads:  domain/copy_trade/repository.py → copy_trade_tasks ✓
MVP copy_wallet handler:   bot/handlers/mvp/copy_wallet.py → copy_trade_tasks ✓
domain/strategy/strategies/copy_trade.py → copy_trade_tasks ✓ (already migrated)
```

All paths now converge on `copy_trade_tasks`. `copy_targets` table dropped.

## 3. Files created / modified

- Created: `projects/polymarket/crusaderbot/migrations/058_drop_copy_targets.sql`
  (backfill copy_targets → copy_trade_tasks, DROP TABLE copy_targets)
- Modified: `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py`
  (_legacy_list_active, _insert_active_target, _legacy_deactivate_target — all
  redirected from copy_targets to copy_trade_tasks; INSERT uses task_name default)
- Modified: `projects/polymarket/crusaderbot/bot/handlers/setup.py`
  (_handle_copy_target_input — list/add/remove all redirected to copy_trade_tasks)
- Modified: `projects/polymarket/crusaderbot/tests/test_copy_trade.py`
  (3 mock SQL pattern strings updated: copy_targets → copy_trade_tasks,
   target_wallet_address → wallet_address)
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 1792 tests pass (no regression)
- ruff clean on all modified files
- All 3 write sites now target copy_trade_tasks
- Migration 058 is idempotent: INSERT … ON CONFLICT DO NOTHING; DROP TABLE IF EXISTS
- Column mapping: target_wallet_address→wallet_address, status active/inactive→active/paused,
  task_name auto-generated as "copy-0xAbCd…1234"

## 5. Known issues

- Migration 058 must be applied to Supabase before deploy
- The legacy `/copytrade` 8-step wizard and setup.py text-flow are low-usage paths
  (MVP copy_wallet.py is the primary UX) — no further refactor needed

## 6. What is next

- Apply migration 058 to Supabase + fly deploy
- Lane 2: WebTrader wallet page (deposit + withdraw UI)

---

**Validation Target:** copy_targets → copy_trade_tasks migration
**Not in Scope:** copy_trade_tasks schema changes, copy-trade execution logic
**Suggested Next Step:** WARP🔹CMD review + merge; apply migration 058; fly deploy
