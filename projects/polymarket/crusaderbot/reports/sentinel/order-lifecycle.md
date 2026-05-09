# WARP•SENTINEL REPORT — order-lifecycle

PR: #913 — Phase 4C order lifecycle
Branch: WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE
Forge report: projects/polymarket/crusaderbot/reports/forge/order-lifecycle.md
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Environment: dev (local validation, infra ENFORCED for risk + activation only)

Verdict: **APPROVED** — Score 96/100, zero critical issues.

---

## 1. TEST PLAN

Phases executed against PR head `6b2552c` (5 commits on top of `cb92066` Phase 4B base).

- Phase 0 — Pre-test: report integrity + state sync + structure
- Phase 1 — Functional: migration idempotency + lifecycle dispatch (5 buckets)
- Phase 2 — Pipeline: lifecycle placement (after EXECUTION, before MONITORING)
- Phase 3 — Failure modes: broker errors, missing broker_id, race-loss, partial-fill
- Phase 4 — Async safety: per-order containment, transactional writes
- Phase 5 — Risk rules + activation guards (`USE_REAL_CLOB`, `ENABLE_LIVE_TRADING`)
- Phase 6 — Latency: poll interval, batch SELECT shape
- Phase 7 — Infra: APScheduler concurrency, DB transactions
- Phase 8 — Telegram: alert events for filled / cancelled / expired / stale

Code reads: `domain/execution/lifecycle.py`, `migrations/015_order_lifecycle.sql`,
`scheduler.py`, `integrations/clob/{__init__,adapter,mock}.py`, `config.py`,
`tests/test_order_lifecycle.py`, `wallet/ledger.py`.

Test execution: `pytest projects/polymarket/crusaderbot/tests/test_order_lifecycle.py`
+ Phase 4A regression suite (`test_clob_adapter`, `test_clob_factory`,
`test_clob_market_data`).

---

## 2. FINDINGS

### Phase 0 — Pre-test (PASS)

- Forge report at correct path with all 6 mandatory sections + metadata
  (Validation Tier / Claim Level / Validation Target / Not in Scope /
  Suggested Next Step) — `reports/forge/order-lifecycle.md:1-7`.
- `state/PROJECT_STATE.md` updated with Phase 4C in-progress entry +
  next-priority pointing at this audit.
- No `phase*/` folders introduced. No shims, no compatibility re-exports.
- Diff scope clean: 14 files, all under `projects/polymarket/crusaderbot/`.

### Phase 1 — Functional (PASS)

- **Migration 015 idempotency** — every DDL guarded:
  `ALTER TABLE orders ADD COLUMN IF NOT EXISTS` (×7),
  `CREATE INDEX IF NOT EXISTS idx_orders_lifecycle_open`,
  `CREATE TABLE IF NOT EXISTS fills`,
  `CREATE INDEX IF NOT EXISTS idx_fills_order` / `idx_fills_ts`. Operator
  rollback block included.
  — `migrations/015_order_lifecycle.sql:27-65, 70-82`.
- **Bucket dispatch** — `_resolve_one` routes broker status into the five
  declared buckets:
  filled → `_on_fill` (`lifecycle.py:208-215`),
  cancelled → `_on_cancel` (`lifecycle.py:221-225`),
  expired → `_on_expiry` (`lifecycle.py:221-225`),
  open + attempts<MAX → `_touch` (`lifecycle.py:233-234`),
  open + attempts≥MAX → `_mark_stale` (`lifecycle.py:227-232`).
- **`ORDER_STATUS_` prefix strip** verified at
  `lifecycle.py:631-632` and exercised by
  `tests/test_order_lifecycle.py::test_broker_status_strips_order_status_prefix`
  (covers MATCHED / canceled / EXPIRED variants).
- **Test outcomes**:
  - `test_order_lifecycle.py`: 29 passed, 0 failed (`pytest -q`).
  - 4A regression: `test_clob_adapter` + `test_clob_factory` +
    `test_clob_market_data` → 30/30 green. No regression from
    `post_order` signature widening.

### Phase 2 — Pipeline (PASS)

Lifecycle sits after EXECUTION (`live.execute()` creates order rows) and
before MONITORING (audit + Telegram fan-out). `OrderLifecycleManager`
never creates new orders, never debits the ledger directly — it only
reconciles broker state into existing rows. Pipeline locked-order
contract preserved.

### Phase 3 — Failure modes (PASS)

- **CLOB factory failure** aborts sweep with `errors=len(rows)` instead
  of crashing the scheduler tick — `lifecycle.py:117-122`; covered by
  `test_clob_factory_failure_aborts_sweep`.
- **Per-order containment** — `try/except` wraps each
  `_resolve_one` call, logs with `exc_info=True`, increments error
  counter, continues sweep — `lifecycle.py:128-141`.
- **Missing `polymarket_order_id`** — defensive: touched each cycle,
  marked stale once budget spent, never spams broker —
  `lifecycle.py:194-203`.
- **Race-loss on terminal write** — `UPDATE … RETURNING id` with status
  filter on `STATUS_OPEN`; `None` return short-circuits side effects —
  `lifecycle.py:266-272` (filled), `lifecycle.py:402-407`
  (cancel/expiry); covered by `test_terminal_race_skips_when_already_terminal`.
- **Duplicate fill rows** — `INSERT INTO fills … ON CONFLICT (fill_id)
  DO NOTHING` — `lifecycle.py:560-569`.
- **Capital refund partial-fill correctness** — `_terminal_close`
  reconciles broker fills BEFORE position update:
  `_aggregate_fills(fills, fallback={})` → `filled_notional` clamped to
  `size_usdc` → `refund = size_usdc - filled_notional` —
  `lifecycle.py:369-379`. Partial-fill resizes the position
  (`SET size_usdc, entry_price`) and keeps `status='open'`; no-fill
  rolls position to `'cancelled'` — `lifecycle.py:415-444`. Covered by
  `test_live_cancelled_partial_fill_resizes_position_and_refunds_remainder`.
- **No double-credit on pending orders** — refund only credited when
  position UPDATE returns a row (`pos is not None`); pending orders
  that never reached the position-insert path return `None` and the
  refund branch is skipped — `lifecycle.py:449-457`. Covered by
  `test_live_cancelled_skips_credit_when_no_position_rolled_back`.

### Phase 4 — Async safety (PASS)

- All DB writes inside the terminal-close path live inside a single
  `conn.transaction()` block — `lifecycle.py:394-457`.
- Per-order failures cannot break the sweep; the outer `try/finally`
  guarantees `client.aclose()` runs even on per-order exceptions —
  `lifecycle.py:143-148`.
- No `threading`. AsyncIO only via APScheduler `AsyncIOScheduler`.
- No mutable shared state across orders inside the sweep loop.

### Phase 5 — Risk + activation guards (PASS)

- `USE_REAL_CLOB` default `False` — `config.py:120`. Lifecycle paper-mode
  branch synthesises a fill after one cycle and never invokes
  `clob_factory(s)` (factory raises `AssertionError` in
  `test_paper_mode_does_not_call_broker`).
- `ENABLE_LIVE_TRADING` is **not** read by lifecycle for activation —
  the manager only reconciles existing rows. The pre-existing code
  default `True` at `config.py:134` is overridden to `false` in
  `fly.toml [env]` (line 38) — already documented in PROJECT_STATE
  KNOWN ISSUES; not introduced by this PR.
- Kelly cap (a=0.25): not in scope — lifecycle does not size new
  trades.
- Refund math uses `Decimal`, never `float`, for ledger amounts —
  `lifecycle.py:369-379, 449-457`.

### Phase 6 — Latency (PASS)

- Poll interval `ORDER_POLL_INTERVAL_SECONDS=30` —
  `config.py:161`.
- Single batched SELECT per sweep with partial index
  `idx_orders_lifecycle_open` keeping the scan cheap as the orders
  table grows — `migrations/015_order_lifecycle.sql:38-40`.
- Per-order conn.acquire is acceptable at current scale (Tier-3
  population still small); no SLA budget assertions in tests, but
  no obvious bottleneck.

### Phase 7 — Infra (PASS)

- APScheduler `order_lifecycle` job registered with
  `max_instances=1, coalesce=True` —
  `scheduler.py:475-477`. Backed-up ticks cannot stack.
- `_job_tracker_listener` records SUBMITTED / EXECUTED / ERROR into
  `job_runs` so lifecycle ticks are observable from `/ops`.
- DB migration runner is alphabetical; `015_…` lands after `014_…` on
  every boot, idempotently.

### Phase 8 — Telegram (PASS)

Four lifecycle alert events wired (4 of the 7 system-wide events; the
remaining 3 belong to deposit / signal / risk lanes outside this PR):

- `order_filled` user alert — `lifecycle.py:303-310`.
- `order_cancelled` user alert (with partial-fill refund line when
  applicable) — `lifecycle.py:312-325, 472-482`.
- `order_expired` user alert — `lifecycle.py:327-340`.
- `STALE ORDER` operator page — `lifecycle.py:509-518`.

All notify paths wrapped in `_safe_notify_user` / `_safe_audit` so
Telegram outages never abort the sweep — `lifecycle.py:573-590`.

---

## 3. CRITICAL ISSUES

**None found.**

Non-blocking observations (do NOT affect verdict):

1. **Forge test-count drift** — forge §5 claims "23 hermetic + 1
   importorskip = 24 tests"; actual file contains 29 tests (28
   hermetic + 1 importorskip-gated). Cosmetic doc drift only —
   recommend post-merge fix-forward. Source:
   `tests/test_order_lifecycle.py` count via
   `grep -c "^def test_\|^async def test_"`.
2. **Branch verification mismatch in harness env** —
   `git rev-parse` initially returned `claude/order-lifecycle-phase-4c-2CBpc`
   (Claude Code auto-generated dev branch); the actual PR head is
   `WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE` (correct WARP/ format).
   Per CLAUDE.md SENTINEL rule "Block based on branch name alone
   (Codex worktree = `work` is normal)", branch-name mismatch alone
   does not block. SENTINEL audit was performed against the actual
   PR head after `git fetch + git checkout WARP/...`.
3. **Cosmetic asyncio warnings** — 7 `pytest-asyncio` warnings on
   sync helper tests (`_broker_status` / `_aggregate_fills`).
   Already documented in forge §5 known-issues.
4. **`_aggregate_fills` returns size=0 on non-empty fills with
   total_size<=0** (`lifecycle.py:668-669`) — defensive fallback,
   but masks a broker bug where every fill returns size=0. Acceptable
   for now; no incident pattern observed.

---

## 4. STABILITY SCORE

| Category               | Weight | Score |
|------------------------|--------|-------|
| Architecture           | 20%    | 19    |
| Functional             | 20%    | 20    |
| Failure modes          | 20%    | 19    |
| Risk + activation      | 20%    | 20    |
| Infra + Telegram       | 10%    | 9     |
| Latency                | 10%    | 9     |
| **TOTAL**              | 100%   | **96** |

Deductions:
- Architecture −1: forge test-count doc drift (29 vs claimed 24).
- Failure modes −1: `_aggregate_fills` size=0 fallback masks pathological
  broker payloads (no surfaced warning log on that path).
- Infra+TG −1: poll job has no jitter (low-impact at 30s, single instance).
- Latency −1: per-order `conn.acquire()` not pooled into a single sweep
  txn (acceptable at current scale).

---

## 5. GO-LIVE STATUS

**APPROVED** — Score 96/100, zero critical issues, zero blockers.

Reasoning:
- Migration 015 fully idempotent (every DDL guarded; rollback block
  present).
- All five lifecycle dispatch buckets exercised end-to-end in 29
  hermetic tests, all green.
- ORDER_STATUS_ prefix strip (commit 97e81aa) verified — closes the
  silent-stall risk from real CLOB enum-style strings.
- Capital refund correctness on partial-fill cancel/expiry verified
  (commits 4a94acd + a995d52); both broker-fills-before-refund and
  no-double-credit-on-pending paths covered by tests.
- Paper-mode path proven to never invoke the CLOB factory via
  injection assertion (`test_paper_mode_does_not_call_broker`).
- APScheduler `order_lifecycle` job uses `max_instances=1,
  coalesce=True` — no stacked ticks.
- Activation posture remains PAPER ONLY: `ENABLE_LIVE_TRADING` not
  mutated, not read by lifecycle for activation; `USE_REAL_CLOB`
  defaults `False` and gates every real-broker call.
- 4A regression suite 30/30 green — no surface widening regression
  from `post_order(tick_size=, neg_risk=)` or new lifecycle methods.

Recommend WARP🔹CMD merge.

---

## 6. FIX RECOMMENDATIONS

All recommendations are POST-MERGE fix-forward; none block this PR.

Priority P3 (cosmetic / doc):

1. Update `reports/forge/order-lifecycle.md` §5 test count (`24` → `29`).
2. Drop `pytestmark = pytest.mark.asyncio` from sync helper tests in
   `tests/test_order_lifecycle.py:209-251` to silence 7 cosmetic
   warnings — or move helper-function tests into a
   non-asyncio-marked module.

Priority P3 (defensive hardening):

3. In `_aggregate_fills`, log a `logger.warning` when `total_size<=0`
   on a non-empty fill list — `lifecycle.py:668-669`. Surfaces broker
   bugs that today fall through silently.
4. Optional: jitter `ORDER_POLL_INTERVAL_SECONDS` ±5s on multi-pod
   deploys to avoid synchronized broker hammering. Single-instance
   today, so deferred.

Priority P2 (next-lane):

5. Wire ledger reversal directly into lifecycle for live mode (the
   forge already lines this up as
   `WARP/CRUSADERBOT-LIFECYCLE-LEDGER-REVERSAL`). Today the refund
   path is exercised but the live `execute()` ledger debit semantics
   should be audited end-to-end against `_terminal_close` refund math
   on a fresh DB before flipping `USE_REAL_CLOB=True`.

---

## 7. TELEGRAM PREVIEW

Lifecycle user-facing alerts (rendered exactly as the manager emits):

```
✅ *Order filled*
Market `mkt-1`
*YES* 181.8182 @ 0.550
```

```
❌ *Order cancelled*
Market `mkt-1`
*YES* size $100.00
Filled `$20.00` / refunded `$80.00`
```

```
⌛️ *Order expired*
Market `mkt-1`
*YES* size $50.00
```

Operator page (stale order):

```
⚠️ *STALE ORDER*
order_id=`<uuid>` user=`<uuid>`
market=`mkt-1` attempts=`48`
reason: `max poll attempts reached (broker_status=open)`
Reconcile via Polymarket dashboard.
```

Operator commands related to this lane (existing surface):

- `/ops` — dashboard shows `order_lifecycle` job in the job table
  (registered via `setup_scheduler()`).
- `/kill` / `/resume` — pre-existing kill switch from R12 Lane 1B; the
  lifecycle job halts when scheduler is paused.

---

## DONE

```
Done -- GO-LIVE: APPROVED. Score: 96/100. Critical: 0.
PR: WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE
Report: projects/polymarket/crusaderbot/reports/sentinel/order-lifecycle.md
State: PROJECT_STATE.md updated
NEXT GATE: Return to WARP🔹CMD for final decision.
```
