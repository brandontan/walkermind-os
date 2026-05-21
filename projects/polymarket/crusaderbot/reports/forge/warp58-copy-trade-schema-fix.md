# WARP-58 — Fix `domain/signal/copy_trade.py` copy_targets schema mismatch

**Branch:** `WARP/warp58-copy-trade-schema-fix`
**Issue:** #1263
**Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Generated:** 2026-05-21 16:16 Asia/Jakarta

---

## 1. What was built

Repaired the legacy domain copy-scan engine at `projects/polymarket/crusaderbot/domain/signal/copy_trade.py` so its SQL agrees with the canonical `copy_targets` schema produced by migration `009_copy_trade.sql`.

The fix is a pure column-rename + predicate swap inside `CopyTradeStrategy.scan()`:

- `SELECT … wallet_address …` → `SELECT … target_wallet_address …`
- `WHERE user_id=$1 AND enabled=TRUE` → `WHERE user_id=$1 AND status='active'`
- Three downstream dict reads of `t["wallet_address"]` re-keyed to `t["target_wallet_address"]` (Polymarket Data API call, warning log, `SignalCandidate.extra["target"]`).

The legacy `UPDATE copy_targets SET last_seen_tx=$1 WHERE id=$2` is left untouched: `last_seen_tx` is a `001_init.sql` column that migration 009 explicitly preserves (009 only adds new columns and relaxes the legacy NOT NULL on `wallet_address`). It is keyed on `id` (PK), not on the renamed columns, so it remains correct.

WARP-57 SENTINEL Round-1 had already fixed the MVP write path (`bot/handlers/mvp/copy_wallet.py`) to canonical columns; WARP-58 closes the matching read-path drift in the domain scanner that `scheduler.py:26` imports as `CopyTradeStrategy`.

## 2. Current system architecture (relevant slice)

```
DATA  ──┐
        │  Polymarket Data API (get_user_activity)
        ▼
STRATEGY
  domain/signal/copy_trade.py        ← FIXED (legacy scanner, scheduler.py:26)
    └─ SELECT copy_targets WHERE status='active'
       FETCH leader trades → emit SignalCandidate

  domain/strategy/strategies/copy_trade.py    (unchanged — reads copy_trade_tasks)
    └─ _load_active_copy_targets() → copy_trade_tasks WHERE status='active'

INTELLIGENCE → RISK → EXECUTION → MONITORING
```

`copy_targets` (canonical, mig 009):
`id, user_id, target_wallet_address, scale_factor, status, trades_mirrored, created_at` + retained legacy `wallet_address` (nullable) and `last_seen_tx`.

Two independent strategy entry points coexist (per state KNOWN ISSUES, WARP-26 advisory): the legacy domain scanner against `copy_targets` (this fix) and the new domain strategy against `copy_trade_tasks`. Convergence is out of scope for WARP-58.

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/domain/signal/copy_trade.py`

Created:
- `projects/polymarket/crusaderbot/reports/forge/warp58-copy-trade-schema-fix.md`

State updates:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (surgical, scope-bound)
- `projects/polymarket/crusaderbot/state/WORKTODO.md` (entry for WARP-58)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append-only lane entry)

Not modified (explicitly out of scope per issue #1263):
- `bot/handlers/setup.py` (legacy `wallet_address`/`enabled` writer — `bot/` excluded)
- `bot/handlers/copy_trade.py`, `bot/handlers/mvp/copy_wallet.py` (`bot/` excluded; MVP already canonical)
- `migrations/`, `api/`, `scheduler.py`
- `domain/strategy/strategies/copy_trade.py` (queries `copy_trade_tasks`, not `copy_targets` — already canonical)
- `tests/test_copy_trade.py` (targets the new strategy + bot/keyboards, not the legacy domain scanner)

## 4. What is working

- `python -m py_compile domain/signal/copy_trade.py` clean.
- `python -m py_compile` also clean on `domain/strategy/strategies/copy_trade.py` and `scheduler.py` (consumer chain).
- `grep -n "wallet_address\|enabled" domain/signal/copy_trade.py` returns only `target_wallet_address` matches — zero legacy column references remain in the file.
- `grep -rn "copy_targets" domain/ --include="*.py"` returns only the two corrected SQL strings in this file plus the unrelated `_load_active_copy_targets` function name in the new strategy (function name, not a table reference).
- The repaired SELECT matches the canonical index `idx_copy_targets_user_status (user_id, status)` declared in migration 009 — the hot-path query is now index-aligned.

## 5. Known issues

- pytest is not installed in this remote execution container, so the regression-test arm of the STANDARD checklist could not be exercised here. The fix is a pure column rename + WHERE predicate swap with no behaviour change beyond reading the canonical schema; py_compile + AST parse on the touched file is the verification available in this environment. WARP🔹CMD should run `pytest tests/test_copy_trade.py` locally / in CI before merge to confirm no incidental import-time coupling.
- The legacy `domain/signal/copy_trade.py` scanner and the new `domain/strategy/strategies/copy_trade.py` strategy still both register against `CopyTradeStrategy` (scheduler.py:26 imports the legacy class; the new class registers via `domain/strategy/strategies/__init__.py`). Reconciliation of the two scanners onto a single table is the open MEDIUM-4 follow-up flagged by WARP-57 SENTINEL — explicitly out of WARP-58 scope.
- `bot/handlers/setup.py` still writes the legacy `wallet_address` + `enabled` shape. Out of scope (issue #1263 excludes `bot/`); should be picked up by the MEDIUM-4 / `bot/` cleanup lane.

## 6. What is next

- WARP🔹CMD review of PR for WARP/warp58-copy-trade-schema-fix.
- After merge: Fly.io redeploy so the running scheduler imports the fixed scanner — the `copy_targets` SELECT will then return the canonical rows the MVP copy-wallet path has been writing since WARP-57.
- Follow-up lane: MEDIUM-4 from WARP-57 SENTINEL (swap MVP copy-wallet writes to `copy_trade_tasks`, converging both scanners) — separate task, separate branch.

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : `domain/signal/copy_trade.py` reads `target_wallet_address` + `status='active'`; no `enabled` or `wallet_address` column references remain in `domain/` for `copy_targets`.
Not in Scope      : `bot/` handlers, `migrations/`, `api/`, `scheduler.py`, activation guards, MEDIUM-4 dual-scanner convergence.
Suggested Next    : WARP🔹CMD review.
