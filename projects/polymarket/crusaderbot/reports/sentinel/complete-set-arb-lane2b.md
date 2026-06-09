# WARP•SENTINEL — complete-set-arb Lane 2B (PAPER booking primitive)

**Branch:** `WARP/ROOT/complete-set-arb-lane2b`
**Tier:** MAJOR · **Claim:** FOUNDATION · **Env:** dev
**Verdict:** APPROVED · **Score:** 95/100 · **Critical:** 0

Owner-requested focus: transaction boundaries · partial idempotency guards ·
zero trading-core leakage. Audited against code (code is truth).

## TEST PLAN

Lane 2B is the PAPER two-leg booking primitive (`book_complete_set_paper`),
shipped UNWIRED. Verify: (1) the booking is atomic all-or-nothing, (2) idempotent
replay never persists a half set, (3) the module cannot affect any existing trade.

## PHASE 0 — PRE-TEST

- Report present, correct path, 6 sections + metadata —
  `reports/forge/complete-set-arb-lane2b.md` → PASS
- `PROJECT_STATE.md` updated (Lane 2B COMPLETED + NEXT PRIORITY → 2C) → PASS
- No `phase*/` folders; module in `domain/execution/` → PASS
- Implementation evidence: `complete_set_exec.py:108` + 7 hermetic tests → PASS

## FINDINGS

### 1. Transaction boundaries — PASS
- All mutations inside ONE `async with conn.transaction()`
  (`complete_set_exec.py:155-207`): 2 order INSERTs (`:156,161`), 2 position
  INSERTs (`:177,183`), 2 cross-link UPDATEs (`:192,196`), 2 ledger debits
  (`:201,205`). Atomic — a failure at any step rolls the whole set back.
- Early returns write nothing: non-positive shares returns before `get_pool()`
  (`:128-133`); duplicate returns inside the txn after two `ON CONFLICT DO
  NOTHING` no-ops (`:166-168`) → empty commit, connection released by the `async
  with` — no dangling state.
- Post-commit side effects are correctly OUTSIDE the txn and non-fatal: `audit.write`
  is wrapped in try/except (`:215-227`) so an audit failure cannot unwind a trade
  that is already committed. Matches AGENTS.md zero-silent-failures (logs the
  exception, does not swallow silently).
- Cross-link relies on the mig-078 `DEFERRABLE INITIALLY DEFERRED` FK so both
  mutual references validate at COMMIT (`:190-199`). Correct given Lane 2A.

### 2. Partial idempotency guards — PASS
- Both legs' keys already seen → `{"status":"duplicate"}`, nothing written
  (`:166-168`).
- Exactly one leg fresh (a half set) → `raise RuntimeError` (`:169-175`) → the
  enclosing transaction rolls back, so a fresh order INSERTed before the raise is
  undone. No half pair can persist.
- Per-leg keys derive from a single base identity (`{key}:yes` / `{key}:no`,
  `:159,164`) and the `orders.idempotency_key` UNIQUE constraint enforces replay
  safety at the DB. Covered by `test_partial_idempotency_raises_to_rollback` and
  `test_duplicate_set_books_nothing`.

### 3. Zero trading-core leakage — PASS
- `grep` for `book_complete_set_paper` / `complete_set_exec` across the package
  returns only the module + its test — zero callers. Nothing in scan, gate
  (`domain/risk/gate.py`), `paper.py`, `router.py`, `live.py`, or the registry
  imports it. It cannot affect any existing directional trade.
- The module only CONSUMES shared infra (`ledger.debit_in_conn`, `get_pool`,
  `audit.write`, `CompleteSetQuote`); it mutates no shared trading-core logic.
- `paper.execute` and the directional path are byte-for-byte unchanged.

### 4. Correctness / async safety — PASS
- Position INSERT mirrors `paper.execute` columns exactly with `tp_pct/sl_pct`
  hard-NULL (hold-to-settlement) (`:84-101`). `entry_price = current_price`
  (`$6` reused). `strategy_metadata` json-dumped with `$::jsonb` cast.
- Per-leg price = `leg_cost / fillable_shares` (`:136-137`); `size_usdc` Decimal,
  `price` float — same typing contract as `paper.execute`.
- No shared mutable module state; each call is transaction-scoped → no races.
- Degenerate guard `shares <= 0` short-circuits before any DB acquire (`:128`).

## STABILITY SCORE

Arch 20/20 · Functional 20/20 (7/7 hermetic tests) · Failure modes 18/20 ·
Risk (txn atomicity + idempotency) 20/20 · Infra N/A · Latency N/A (single txn).
**Total: 95/100.** −5: real DB ROLLBACK is delegated to asyncpg's `transaction()`
(trusted) — the hermetic `_Tx` is a no-op, so rollback is not integration-tested;
the guard LOGIC is tested (no positions inserted on the partial path).

## GO-LIVE STATUS

APPROVED for merge as a FOUNDATION primitive. This does NOT authorize execution,
capital, or LIVE — the path is inert until Lane 2C wires the set-aware gate +
scan + default-OFF flag, and LIVE is Lane 3 (its own SENTINEL gate).

## CRITICAL ISSUES

None found.

## FIX RECOMMENDATIONS (non-blocking)

- M-1 (`:108`): `telegram_user_id` is accepted but unused — reserved for the
  Lane 2C set-level notification. Wire or annotate it in 2C.
- M-2: add an integration smoke test exercising a real `transaction()` rollback
  once migration 078 is applied to Supabase (Lane 2C).
- M-3: apply migration 078 to Supabase BEFORE Lane 2C exercises this path in
  PAPER — the `paired_position_id` UPDATEs require the column.

## NOTES

WARP•SENTINEL does not merge. Per owner instruction the owner executes the merge
on APPROVED. WARP•R00T acted as SENTINEL under owner authorisation.
