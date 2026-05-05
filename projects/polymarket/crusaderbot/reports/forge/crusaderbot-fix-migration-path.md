# WARP•FORGE — CrusaderBot Migration Runner Path Fix

Branch: `WARP/CRUSADERBOT-FIX-MIGRATION-PATH`
Tier: MINOR
Claim Level: FILE MOVE ONLY — zero logic change
Date: 2026-05-06 09:00 Asia/Jakarta

---

## 1. What was built

Relocated migration `008_strategy_tables.sql` from `infra/migrations/` into the directory that `database.run_migrations()` actually scans (`migrations/`). Pure rename — no content edit, no runner change, no schema change. Closes the runtime gap where 008 (P3a strategy tables) was on disk but never applied at startup.

Out of scope for this lane: 009_copy_trade.sql does not exist on `main` — it lives on the open P3b branch (PR #877). 009 will be moved into the correct directory as a follow-up commit on that branch before P3b merges. Confirmed with WARP🔹CMD prior to execution.

## 2. Current system architecture

Migration runner contract (unchanged):

```
projects/polymarket/crusaderbot/database.py:45-55
  run_migrations() -> sorted(Path(__file__).parent / "migrations").glob("*.sql")
```

Resulting on-disk layout after this change:

```
projects/polymarket/crusaderbot/migrations/
  001_init.sql
  002_safety.sql
  003_live_safety.sql
  004_deposit_log_index.sql
  005_position_exit_fields.sql
  006_redeem_queue.sql
  007_ops.sql
  008_strategy_tables.sql   <- relocated

projects/polymarket/crusaderbot/infra/migrations/
  (empty)
```

Boot-time sequence: pool init → `run_migrations()` iterates `migrations/*.sql` lex-sorted → 001 through 008 applied in order. 008 contains `CREATE TABLE IF NOT EXISTS` for `strategy_definitions`, `user_strategies`, `user_risk_profile` (idempotent — safe on re-boot).

## 3. Files created / modified (full repo-root paths)

Renamed (git mv, similarity 100%, content byte-identical):
- `projects/polymarket/crusaderbot/infra/migrations/008_strategy_tables.sql` → `projects/polymarket/crusaderbot/migrations/008_strategy_tables.sql`

Created:
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fix-migration-path.md` (this report)

Modified (state sync only):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

No source code touched. No migration content touched.

## 4. What is working

- `git diff --stat` confirms zero-byte delta on the migration file (rename only, similarity 100%).
- `migrations/` directory now lists 001–008 in correct numeric / lexical order.
- `infra/migrations/` no longer holds 008 (directory empty).
- 008 is now reachable by `run_migrations()`; on next boot it will execute `CREATE TABLE IF NOT EXISTS` blocks and register itself in whatever applied-tracking the runner uses.
- No existing test fixtures referenced the old path — search confirmed.

## 5. Known issues

- `infra/migrations/` directory remains empty on disk. Left in place — removal is out of scope and may be wanted for future infra-only artifacts (e.g., one-off ops scripts not run by the boot migrator).
- 009_copy_trade.sql is still placed under `infra/migrations/` on branch `WARP/CRUSADERBOT-P3B-COPY-TRADE` (PR #877). That branch must rebase on this fix and apply the equivalent move before merge, otherwise the copy-trade tables will not be applied at startup. Tracking: WORKTODO entry preserved.
- This fix does not retroactively run 008 against any already-running environment — only fresh boots benefit. Idempotent SQL (`IF NOT EXISTS`) makes that safe in either case.

## 6. What is next

- WARP🔹CMD review (MINOR → direct merge expected).
- After this merges, the P3b branch (PR #877) needs an equivalent `git mv` for 009_copy_trade.sql before SENTINEL runs against PR #877 on Issue #878. That move can be a single commit on the existing P3b branch — no rework needed.
- Then P3b SENTINEL → merge → P3c → P3d.

---

## Metadata

- Validation Tier: MINOR
- Claim Level: FILE MOVE ONLY — zero logic change
- Validation Target: `migrations/` contains 001–008 in order; `infra/migrations/` does not contain 008; file content byte-identical to pre-move.
- Not in Scope: runner code changes; migration content edits; 009_copy_trade.sql (lives on PR #877 branch); cleanup of empty `infra/migrations/` directory; retroactive run of 008 against existing environments.
- Suggested Next Step: WARP🔹CMD merge → instruct P3b owner to rebase PR #877 and move 009_copy_trade.sql into `migrations/` as a single follow-up commit before SENTINEL.
