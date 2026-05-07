# WARP•FORGE Report — preflight-cleanup

**Branch:** WARP/CRUSADERBOT-PREFLIGHT-CLEANUP
**Date:** 2026-05-08 03:39 Asia/Jakarta
**Tier:** MINOR
**Claim Level:** NONE — pure cleanup, no behavioural change
**Validation Target:** ruff F401 clean across the 7 listed files; copy_trade handler helpers carry user_id type annotations; dispatcher.py phase-prefixed comment dropped; migration 013 converts copy_trade_events.copy_target_id FK to ON DELETE SET NULL; ROADMAP.md R12d/R12e/R12f rows + detail entries match actual executed lane names.
**Not in Scope:** anything in domain/risk/, anything touching execution path, activation guards (EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / ENABLE_LIVE_TRADING / etc), demo polish, R12 final Fly.io deployment.
**Suggested Next:** WARP🔹CMD review and merge.

---

## 1. What was changed

**F401 unused-import cleanup (15 imports across 7 files).** All 15 ruff F401 findings on the lane scope removed; full-repo `ruff check .` now clean.

| File | Removed |
|---|---|
| `bot/dispatcher.py` | `from telegram import Update` |
| `bot/handlers/dashboard.py` | `from decimal import Decimal`; inline `from ...integrations.polymarket import get_market` inside `close_position_cb` |
| `cache.py` | `Optional` from `typing` |
| `config.py` | `Field` from `pydantic` |
| `domain/risk/gate.py` | `timedelta` from `datetime`; `Optional` from `typing` |
| `scheduler.py` | `timezone` from `datetime`; `Any` from `typing`; `set_tier` from `.users`; `get_wallet` from `.wallet.vault` |
| `services/signal_scan/signal_scan_job.py` | `logging`, `struct`, `datetime`, `timezone` (4 imports) |

**MIN-01 — copy_trade handler helper annotations.** Added `from uuid import UUID` to `bot/handlers/copy_trade.py` and annotated the three sub-command handler helpers:

- `_handle_add(update: Update, user_id: UUID, args: list[str]) -> None`
- `_handle_remove(update: Update, user_id: UUID, args: list[str]) -> None`
- `_handle_list(update: Update, user_id: UUID) -> None`

`user_id` is the `users.id` UUID returned by `_ensure_tier` (asyncpg decodes UUID columns to `uuid.UUID`); previously bare, now typed. Deeper DB helpers (`_list_active_targets`, `_insert_active_target`, `_deactivate_target`) are out of scope per the "3 handler helpers" wording — left untouched.

**MIN-02 — dispatcher phase comment.** `bot/dispatcher.py:64` `# P3b copy-trade strategy command surface.` → `# Copy-trade strategy command surface.` (phase-id prefix dropped; comment now describes the surface, not the lane that introduced it). Other phase-prefixed comments in the same file (R12f / P3c / R12) were left untouched per scope gate — only the deferred MIN-02 finding tied to the closed P3b lane was in scope.

**MIN-03 — copy_trade_events.copy_target_id nullable FK.** New migration `migrations/013_copy_trade_events_nullable_fk.sql` converts the FK from `ON DELETE CASCADE` to `ON DELETE SET NULL`. The column itself was already nullable in `migrations/009_copy_trade.sql` (no `NOT NULL` on the definition), so the meaningful "nullable FK" semantic change is the referential action: append-only `copy_trade_events` rows now survive parent `copy_targets` deletion as orphan rows with `NULL copy_target_id`, instead of being cascade-deleted alongside the target. Per-follower dedup is unaffected — `UNIQUE (copy_target_id, source_tx_hash)` remains intact for active targets. Migration is idempotent (guarded by a `pg_constraint.confdeltype = 'c'` check) and runs on startup via the existing `migrations/` runner path.

**ROADMAP R12d/R12e/R12f naming alignment.** Both the `Build Path` table rows and the `R12 — Detailed Lane Plan` entries in `state/ROADMAP.md` now match the actual executed lane names recorded in `PROJECT_STATE.md` and `WORKTODO.md`:

- R12d: `Live Opt-In Checklist` → `Telegram Position UX (live monitor + force close)` (PR #868, STANDARD)
- R12e: `Live → Paper Auto-Fallback` → `Auto-Redeem System` (PR #869, MAJOR, SENTINEL CONDITIONAL 64/100 — resolved PR #879)
- R12f: `Daily P&L Summary` → `Operator Dashboard + Kill Switch + Job Monitor` (PR #874, STANDARD)
- New row: `R12 Live Readiness batch` — Live Opt-In Checklist + Live → Paper Auto-Fallback + Daily P&L Summary, merged together via PR #883 (STANDARD, NARROW INTEGRATION). The originally planned R12d/R12e/R12f content was bundled into this single PR; calling it out explicitly closes the long-deferred ROADMAP-vs-PROJECT_STATE drift instead of leaving it under `[KNOWN ISSUES]`.

**State file sync.**

- `state/PROJECT_STATE.md`: `Last Updated` bumped to `2026-05-08 03:39 Asia/Jakarta`; `Status` line notes the open cleanup lane; `[IN PROGRESS]` carries the cleanup lane summary; `[KNOWN ISSUES]` pruned of the four resolved-by-this-task entries (F401, MIN-01, MIN-02, MIN-03, ROADMAP R12d/e/f drift).
- `state/WORKTODO.md`: `Last Updated` bumped; the four `Known Issues / Tech Debt` items resolved by this lane checked off with explicit `DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP` markers; remaining items (check_alchemy_ws, services/* dead code, /deposit tier gate) preserved verbatim.
- `state/CHANGELOG.md`: cleanup entry prepended at top of file matching the existing newest-at-top order.
- `state/ROADMAP.md`: `Last Updated` bumped; rows + detail entries replaced as described above. No phase/milestone sequencing change — R12 final Fly.io deployment remains the next NOT STARTED lane.

---

## 2. Files modified (full repo-root paths)

Code:

- `projects/polymarket/crusaderbot/bot/dispatcher.py` — F401 (Update); MIN-02 phase comment
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — F401 (Decimal, get_market)
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py` — MIN-01 annotations + `from uuid import UUID`
- `projects/polymarket/crusaderbot/cache.py` — F401 (Optional)
- `projects/polymarket/crusaderbot/config.py` — F401 (Field)
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — F401 (timedelta, Optional)
- `projects/polymarket/crusaderbot/scheduler.py` — F401 (timezone, Any, set_tier, get_wallet)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — F401 (logging, struct, datetime, timezone)

Migration (new):

- `projects/polymarket/crusaderbot/migrations/013_copy_trade_events_nullable_fk.sql`

State / planning:

- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/ROADMAP.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

Report (new):

- `projects/polymarket/crusaderbot/reports/forge/preflight-cleanup.md` (this file)

---

## 3. Validation Tier / Claim Level / Validation Target / Not in Scope / Suggested Next

- **Validation Tier:** MINOR
- **Claim Level:** NONE — pure cleanup, no behavioural change. No risk-gate, execution, capital, async-core, or live-activation path touched. Migration 013 only changes the referential action on a single FK; it neither adds nor relaxes any uniqueness, nullability, or write path.
- **Validation Target:**
  - `ruff check .` clean (verified — "All checks passed!")
  - `python3 -m py_compile` clean on all 7 touched code files (verified)
  - `pytest -q` 464/464 green expected; CI will verify. The build sandbox this lane was authored in could not collect the suite (missing runtime deps and a `_cffi_backend`/`cryptography` binary mismatch on `import telegram`). No test files were modified by this lane and the only runtime-touching changes are unused-import removal + parameter annotations on three handler helpers + a guarded migration; none of those have a plausible path to regress an existing test that was green at PR #897 (464/464). If CI red-flags anything, escalate.
  - `state/ROADMAP.md` R12d/R12e/R12f rows + detail entries match `state/PROJECT_STATE.md` lane truth
  - `state/PROJECT_STATE.md` and `state/WORKTODO.md` both reflect the cleared MIN-01/02/03 + F401 items
  - Migration 013 is idempotent (guarded `pg_constraint` existence check) and reuses the existing `migrations/` runner path
- **Not in Scope:**
  - Anything in `domain/risk/` (gate.py touched only to remove unused imports — no logic change)
  - Anything touching execution path, order placement, fill handling, or async-core orchestration
  - Activation guards (`EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `ENABLE_LIVE_TRADING`, `RISK_CONTROLS_VALIDATED`, `SECURITY_HARDENING_VALIDATED`, `FEE_COLLECTION_ENABLED`, `AUTO_REDEEM_ENABLED`)
  - Other phase-prefixed comments in `bot/dispatcher.py` (P3c, R12f, R12) — only the closed-P3b comment was the deferred MIN-02 finding
  - Deeper copy_trade DB helpers (`_list_active_targets`, `_insert_active_target`, `_deactivate_target`) — task scoped MIN-01 to the 3 handler helpers
  - R12 final Fly.io deployment, demo polish, fly secret/runtime audit (Stage A of the parent task is unrunnable from this sandbox — flyctl unavailable, outbound HTTPS to crusaderbot.fly.dev blocked — Stage A was deferred per WARP🔹CMD direction)
- **Suggested Next:** WARP🔹CMD review and merge. No SENTINEL — Tier MINOR, SENTINEL not allowed per AGENTS.md.
