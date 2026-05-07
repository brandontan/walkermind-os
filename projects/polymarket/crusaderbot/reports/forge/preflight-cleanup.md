# WARP•FORGE Report — preflight-cleanup

**Branch:** WARP/CRUSADERBOT-PREFLIGHT-CLEANUP
**PR:** #899
**Date:** 2026-05-08 03:39 Asia/Jakarta (reclassified 2026-05-08 04:00 Asia/Jakarta)
**Tier:** STANDARD (reclassified from MINOR — see header note below)
**Claim Level:** NARROW INTEGRATION (reclassified from NONE)
**Validation Target:** ruff F401 clean across the 7 listed files; copy_trade handler helpers carry user_id type annotations; dispatcher.py phase-prefixed comment dropped; migration 013 converts copy_trade_events.copy_target_id FK referential action from ON DELETE CASCADE to ON DELETE SET NULL (real persistence-behaviour change — see section 2 + migration notes); ROADMAP.md R12d/R12e/R12f rows + detail entries match actual executed lane names.
**Not in Scope:** no risk-logic changes (`domain/risk/gate.py` was touched only to remove unused F401 imports — no behavioural change), anything touching execution path, activation guards (EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / ENABLE_LIVE_TRADING / etc), demo polish, R12 final Fly.io deployment.
**Suggested Next:** WARP🔹CMD review and merge. No SENTINEL — STANDARD does not require SENTINEL.

> **Tier reclassification note (2026-05-08 04:00 Asia/Jakarta).** Original task block declared this lane MINOR / Claim NONE. Codex auto-review on PR #899 correctly flagged that migration 013 is a real persistence-behaviour change and "no behavioural change" wording was internally inconsistent. WARP🔹CMD ratified reclassification to **STANDARD / NARROW INTEGRATION** per AGENTS.md severity classification authority. No scope change — same six work items in this PR. SENTINEL is NOT required for STANDARD; CMD review path remains the gate.

---

## 1. What was built

The lane bundles six items pre-flight-of-demo: an F401 unused-import sweep (15 imports across 7 files), three deferred P3b minor follow-ups (MIN-01 / MIN-02 / MIN-03), a ROADMAP naming-drift fix that closes a long-deferred KNOWN ISSUES entry, and a state-file sync. The single behaviour-affecting change is **migration 013**, which converts the `copy_trade_events.copy_target_id` foreign-key referential action from `ON DELETE CASCADE` to `ON DELETE SET NULL`. All other items are non-runtime cleanup.

**F401 unused-import cleanup (15 imports across 7 files).** All 15 ruff F401 findings on the lane scope removed; project-scoped `ruff check projects/polymarket/crusaderbot/` is clean. Pre-existing F401 leakage in `lib/` (shared-library code, 5 occurrences across 4 files — see `[KNOWN ISSUES]` in PROJECT_STATE.md and the deferred `WARP/LIB-F401-CLEANUP` lane in WORKTODO.md) is not in scope for this PR per WARP🔹CMD scope-boundary hold; that cleanup will be opened post-demo as a separate MINOR lane to preserve project-boundary discipline.

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

**MIN-03 — copy_trade_events.copy_target_id nullable FK.** New migration `migrations/013_copy_trade_events_nullable_fk.sql` converts the FK referential action from `ON DELETE CASCADE` to `ON DELETE SET NULL`. See section 2 + the migration notes block below for full behavioural impact.

**ROADMAP R12d/R12e/R12f naming alignment.** Both the `Build Path` table rows and the `R12 — Detailed Lane Plan` entries in `state/ROADMAP.md` now match the actual executed lane names recorded in `PROJECT_STATE.md` and `WORKTODO.md`:

- R12d: `Live Opt-In Checklist` → `Telegram Position UX (live monitor + force close)` (PR #868, STANDARD)
- R12e: `Live → Paper Auto-Fallback` → `Auto-Redeem System` (PR #869, MAJOR, SENTINEL CONDITIONAL 64/100 — resolved PR #879)
- R12f: `Daily P&L Summary` → `Operator Dashboard + Kill Switch + Job Monitor` (PR #874, STANDARD)
- New row: `R12 Live Readiness batch` — Live Opt-In Checklist + Live → Paper Auto-Fallback + Daily P&L Summary, merged together via PR #883 (STANDARD, NARROW INTEGRATION). The originally planned R12d/R12e/R12f content was bundled into this single PR; calling it out explicitly closes the long-deferred ROADMAP-vs-PROJECT_STATE drift instead of leaving it under `[KNOWN ISSUES]`.

**State file sync.**

- `state/PROJECT_STATE.md`: `Last Updated` bumped to `2026-05-08 04:00 Asia/Jakarta`; `Status` line notes the open cleanup lane and tier reclassification; `[IN PROGRESS]` carries the cleanup lane summary at STANDARD; `[KNOWN ISSUES]` pruned of the four resolved-by-this-task entries (F401, MIN-01, MIN-02, MIN-03, ROADMAP R12d/e/f drift).
- `state/WORKTODO.md`: `Last Updated` bumped; the four `Known Issues / Tech Debt` items resolved by this lane checked off with explicit `DONE on WARP/CRUSADERBOT-PREFLIGHT-CLEANUP` markers; remaining items (check_alchemy_ws, services/* dead code, /deposit tier gate) preserved verbatim.
- `state/CHANGELOG.md`: cleanup entry prepended at top of file matching the existing newest-at-top order; reclassification reflected (Tier: STANDARD / Claim: NARROW INTEGRATION).
- `state/ROADMAP.md`: `Last Updated` bumped; rows + detail entries replaced as described above. No phase/milestone sequencing change — R12 final Fly.io deployment remains the next NOT STARTED lane.

---

## 2. Current system architecture (relevant slice)

The lane touches one persistence boundary and a handful of import / annotation / comment surfaces. The relevant slice is the copy-trade strategy persistence schema introduced in `migrations/009_copy_trade.sql`:

```
┌──────────────────────┐        ┌─────────────────────────────────┐
│ copy_targets         │        │ copy_trade_events (audit log)   │
│ id UUID PK           │ 1   N  │ id UUID PK                      │
│ user_id UUID FK      │◄───────┤ copy_target_id UUID FK (NULL OK)│
│ target_wallet_addr   │        │ source_tx_hash VARCHAR(66)      │
│ status               │        │ mirrored_order_id UUID          │
│ ...                  │        │ created_at TIMESTAMPTZ          │
│                      │        │ UNIQUE(copy_target_id, hash)    │
└──────────────────────┘        └─────────────────────────────────┘
   parent (operator-              child (append-only audit row,
   removable copy target)         per-follower dedup boundary)
```

**FK referential action — before vs after migration 013:**

- **Before (009 baseline):** `copy_target_id UUID REFERENCES copy_targets(id) ON DELETE CASCADE` — when an operator deletes a `copy_targets` row (or the user removes a target), every linked `copy_trade_events` audit row is also deleted. Audit history is lost on parent removal.
- **After (013 applied):** `copy_target_id UUID REFERENCES copy_targets(id) ON DELETE SET NULL` — parent deletion sets the child's `copy_target_id` to NULL but preserves the row. Audit history survives target removal as orphan rows.

The column itself was already nullable in 009 (no `NOT NULL`); 013 only changes the referential action. The `UNIQUE (copy_target_id, source_tx_hash)` composite remains intact for active targets — Postgres treats multiple NULLs as distinct, so orphan rows with `NULL copy_target_id` do not collide.

**Migration runner path:** `migrations/` (not `infra/migrations/`) — same path the existing 001–012 sequence uses. Loaded at startup via the existing migration runner.

---

## 3. Files created / modified (full repo-root paths)

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

Report (this file):

- `projects/polymarket/crusaderbot/reports/forge/preflight-cleanup.md`

### Migration notes — 013_copy_trade_events_nullable_fk.sql

| Aspect | Detail |
|---|---|
| Before | `copy_trade_events.copy_target_id` FK with `ON DELETE CASCADE` |
| After | `copy_trade_events.copy_target_id` FK with `ON DELETE SET NULL` |
| Column nullability | already NULL-allowed in 009; unchanged by 013 |
| Behavioural impact | `copy_trade_events` rows preserved on parent `copy_targets` deletion; `copy_target_id` becomes NULL; audit trail is no longer lost when an operator removes / a user disables a copy target |
| Read-side impact | downstream readers that filter by `copy_target_id` must handle NULL (no current reader joins through NULL — see `_already_mirrored` in `domain/strategy/strategies/copy_trade.py:371` which always supplies a concrete UUID); orphan rows are invisible to active-target queries |
| UNIQUE constraint | `UNIQUE (copy_target_id, source_tx_hash)` still active; Postgres treats multiple NULLs as distinct, so orphan rows do not collide |
| Backfill needed | NO — only the constraint changes; existing rows untouched |
| Idempotency | guarded by `pg_constraint.confdeltype = 'c'` existence check (re-runs on a SET-NULL DB are no-ops) |
| Rollback | drop constraint + re-add with `ON DELETE CASCADE` in a future migration 014; no data backfill required since orphan rows from any production application of 013 would still satisfy the CASCADE constraint (they would be deleted on the next parent-delete event) |
| Runner path | `projects/polymarket/crusaderbot/migrations/` — same loader as 001–012 |

---

## 4. What is working

- `ruff check projects/polymarket/crusaderbot/` — "All checks passed!" (verified locally; project-scoped). Repo-root `ruff check .` is **NOT** clean — pre-existing F401 leakage in `lib/` (5 occurrences across `lib/strategies/logic_arb.py`, `lib/strategies/value_investor.py`, `lib/strategies/weather_arb.py`, `lib/strategy_base.py`) is tracked separately under `[KNOWN ISSUES]` and deferred to `WARP/LIB-F401-CLEANUP` per WARP🔹CMD scope-boundary hold (lib/ is shared-library code that may affect other projects; cross-project audit required before cleanup).
- `python3 -m py_compile` — clean on all 8 touched code files (verified locally)
- `git rev-parse --abbrev-ref HEAD` — `WARP/CRUSADERBOT-PREFLIGHT-CLEANUP` (matches declared branch)
- PR #899 — `Lint + Test` run #1 reports green (run #2 + `Trigger WARP CMD Gate` were in progress at last check; webhook subscription will surface CI updates)
- Migration 013 syntax — guarded `DO $$` block, `ALTER TABLE ... DROP CONSTRAINT` + `ADD CONSTRAINT ... ON DELETE SET NULL` pattern matches the idempotent style used in 009's reconciliation block
- Codex auto-review — one P2 finding raised (tier classification), addressed by reclassification to STANDARD / NARROW INTEGRATION; no other findings

---

## 5. Known issues

- **Migration forward + rollback verification deferred to CI / staging.** The local build sandbox could not exercise the migration end-to-end (no Postgres reachable; `_cffi_backend`/`cryptography` binary mismatch on `import telegram` blocks app-side smoke tests). CMD's "verify forward + rollback both work in local test before pushing" gate cannot be satisfied from this sandbox; the static idempotency guard + the symmetric `pg_constraint.confdeltype` check is the strongest static guarantee available, but a Postgres run on staging is the right next gate.
- **Pre-existing lib/ F401 leakage — deferred to `WARP/LIB-F401-CLEANUP` (post-demo MINOR).** Codex follow-up review on PR #899 surfaced 5 F401 occurrences in shared-library code that pre-date this branch and only fail under repo-root ruff (no per-project `pyproject.toml` in `lib/`):
  - `lib/strategies/logic_arb.py:42` — `get_no_price` from `..strategy_base`
  - `lib/strategies/value_investor.py:30` — `get_no_price` from `..strategy_base`
  - `lib/strategies/weather_arb.py:25` — `import json`
  - `lib/strategies/weather_arb.py:29` — `import urllib.request`
  - `lib/strategy_base.py:34` — `field` from `dataclasses`
  WARP🔹CMD held the scope boundary for #899 (CrusaderBot pre-flight) and routed lib/ to a separate follow-up lane to preserve project-boundary discipline. lib/ is shared-library code that may affect other projects (WARP-CodX, future tenants) and a cross-project audit is required before cleanup.
- **`pytest -q` 464/464 not re-run from this sandbox.** Same dependency reason as above — pytest collection fails at import time on `_cffi_backend`. No test files were modified by this lane; the only runtime-touching changes are unused-import removal, parameter annotations on three handler helpers, a phase-comment edit, and a guarded migration. None of those have a plausible path to regress an existing test that was green at PR #897. CI is the gate.
- **Stage A (Fly.io live state verification) not executed.** The parent task included a Stage A live audit of `crusaderbot.fly.dev`. This sandbox has no `flyctl` and the outbound HTTP allowlist returns `403 host_not_allowed` for the Fly host, so Stage A is unrunnable here. WARP🔹CMD authorised "skip Stage A, proceed directly to Stage B cleanup" — Stage A remains an open input for Lane 1B production-hardening scoping.

---

## 6. What is next

- WARP🔹CMD review of PR #899 at the new STANDARD tier
- Optional: smoke-run migration 013 forward + rollback against a staging Postgres before merge to satisfy CMD's verification gate
- After merge: post-merge sync (PROJECT_STATE.md / ROADMAP.md / WORKTODO.md / CHANGELOG.md already reflect the lane closure; verify CI run on `main` is green)
- Lane 1B pre-demo production hardening — the next lane CMD has flagged. Inputs needed from Stage A (Fly.io live state) before Lane 1B can be scoped.

### Validation declaration

- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION — migration 013 narrows its claim to the `copy_trade_events.copy_target_id` FK referential action; no execution path, no risk-gate behaviour, no async-core orchestration, no live-activation flag touched. The remaining work items (F401 / MIN-01 / MIN-02 / ROADMAP / state sync) carry no runtime claim.
- **Validation Target:**
  - `ruff check projects/polymarket/crusaderbot/` clean (verified locally — "All checks passed!"); repo-root `ruff check .` not clean due to pre-existing lib/ F401s tracked under deferred `WARP/LIB-F401-CLEANUP` lane (see Known Issues)
  - `python3 -m py_compile` clean on all 8 touched code files (verified locally)
  - `pytest -q` 464/464 — CI verifies (sandbox cannot collect; see Known Issues)
  - Migration 013 idempotent on re-run; behavioural impact bounded to `copy_trade_events` audit-row retention semantics; UNIQUE composite remains intact
  - `state/ROADMAP.md` R12d/R12e/R12f rows + detail entries match `state/PROJECT_STATE.md` lane truth
  - `state/PROJECT_STATE.md` and `state/WORKTODO.md` both reflect the cleared MIN-01/02/03 + F401 items
- **Not in Scope:**
  - No risk-logic changes — `domain/risk/gate.py` was touched only to remove unused F401 imports (`timedelta`, `Optional`); the 13-step risk gate behaviour, the `GateContext`/`GateResult` dataclasses, the SQL writes to `risk_log`, and all numeric thresholds are unchanged
  - Anything touching execution path, order placement, fill handling, or async-core orchestration
  - Activation guards (`EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `ENABLE_LIVE_TRADING`, `RISK_CONTROLS_VALIDATED`, `SECURITY_HARDENING_VALIDATED`, `FEE_COLLECTION_ENABLED`, `AUTO_REDEEM_ENABLED`)
  - Other phase-prefixed comments in `bot/dispatcher.py` (P3c, R12f, R12) — only the closed-P3b comment was the deferred MIN-02 finding
  - Deeper copy_trade DB helpers (`_list_active_targets`, `_insert_active_target`, `_deactivate_target`) — task scoped MIN-01 to the 3 handler helpers
  - R12 final Fly.io deployment, demo polish, fly secret/runtime audit (Stage A deferred per WARP🔹CMD direction)
- **Suggested Next:** WARP🔹CMD review and merge. SENTINEL not required at STANDARD per AGENTS.md.
