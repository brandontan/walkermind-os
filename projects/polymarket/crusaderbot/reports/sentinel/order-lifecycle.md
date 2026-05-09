# WARP•SENTINEL REPORT — order-lifecycle (FINAL)

PR: #913 — Phase 4C order lifecycle
Branch: WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE
Audit baseline: HEAD `a484012` (Codex P1 part 3/3)
Forge report: projects/polymarket/crusaderbot/reports/forge/order-lifecycle.md

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Environment: dev (local validation)

---

## VERDICT: **APPROVED**

Score: **96/100**.
Critical issues: **0**.

This report supersedes BOTH prior verdicts on this branch:
- Original APPROVED 96/100 (commit `005c55a`) — baseline `6b2552c`, before Codex P1 follow-ups landed.
- Interim BLOCKED (commit `9fe32d7`) — baseline incorrectly set against working tree pre-`a484012`; pytest run captured pre-fix state and fired a false-blocker.

The **current** verdict against true PR HEAD `a484012` is APPROVED.

---

## AUDIT TIMELINE

The branch tip moved twice during my audit window:

1. **`6b2552c`** — my original audit baseline. APPROVED 96/100 against this state.
2. **`bed7c70` + `18de386`** — Codex P1 part 1/3 + 2/3 landed (adapter `get_fills` swap to `maker_address`, lifecycle paper-synthesis drop + `_broker_fills` from `get_order`).
3. **`a484012`** — Codex P1 part 3/3 landed (test suite updated to match new contract).

My interim BLOCKED report was rendered after step 2 but before step 3 reached my working tree. With `a484012` included, the suite is green again.

**Audit hygiene lesson:** I should have pinned the HEAD SHA at audit start and re-fetched before each verdict rather than assuming the branch was static. Future audits will pin and re-verify.

---

## 1. TEST PLAN (final)

```
$ pytest projects/polymarket/crusaderbot/tests/test_order_lifecycle.py -q
29 passed, 7 warnings

$ pytest projects/polymarket/crusaderbot/tests/test_clob_adapter.py \
         projects/polymarket/crusaderbot/tests/test_clob_factory.py \
         projects/polymarket/crusaderbot/tests/test_clob_market_data.py -q
30 passed
```

Total: 59 tests green at HEAD `a484012`.

---

## 2. FINDINGS (final)

### Phase 0 — Pre-test (PASS)
Forge report intact, state synced, no `phase*/` folders, diff scoped to CrusaderBot only.

### Phase 1 — Functional (PASS)
- Migration 015 idempotency unchanged from original audit — every DDL guarded.
- Lifecycle dispatch buckets:
  - **filled** via `_on_fill` — fills now derived from `_broker_fills(broker, order)` (reads `size_matched` from `/data/order/{id}` payload).
  - **cancelled** / **expired** via `_on_cancel` / `_on_expiry` — same derivation; partial-fill aggregate flows through `_terminal_close` refund math.
  - **stale** via `_mark_stale` after `ORDER_POLL_MAX_ATTEMPTS=48`.
  - **open** via `_touch`.
- ORDER_STATUS_ prefix strip preserved at `lifecycle.py:631-632`; covered by `test_broker_status_strips_order_status_prefix`.
- **Paper-mode behavior is now SAFER than what I originally approved.** Synthesis was dropped; the manager only touches the row, eliminating the state-corruption vector if the operator toggles `USE_REAL_CLOB=False` while live orders remain open at the broker. New test `test_paper_mode_never_synthesises_fill_for_live_rows` enforces this contract.

### Phase 2 — Pipeline (PASS)
Same placement as audited: after EXECUTION, before MONITORING. Lifecycle does not create orders, does not debit ledger directly.

### Phase 3 — Failure modes (PASS)
- CLOB factory failure aborts sweep with `errors=len(rows)` (test_clob_factory_failure_aborts_sweep).
- Per-order containment via try/except in the sweep loop.
- Race-loss handled by `UPDATE … RETURNING id` with status filter (test_terminal_race_skips_when_already_terminal).
- Duplicate fills filtered by `ON CONFLICT (fill_id) DO NOTHING`.
- **Capital refund partial-fill correctness** — `_terminal_close` uses `_broker_fills(broker, order)` aggregate; partial-fill resizes position + keeps `status='open'`; no-fill rolls position to `'cancelled'`. New test `test_live_cancelled_partial_fill_resizes_position_and_refunds_remainder` mocks broker payload `{"status": "cancelled", "size_matched": 50.0, "price": 0.40}` and asserts $80 refund + position resized to $20.
- **No double-credit on pending orders** — refund only credited when position UPDATE returns a row; pending orders return `None` and the refund branch is skipped (test_live_cancelled_skips_credit_when_no_position_rolled_back).

### Phase 4 — Async safety (PASS)
Same as original audit: transactional terminal writes, per-order failure containment, AsyncIO only.

### Phase 5 — Risk + activation guards (PASS)
- `USE_REAL_CLOB=False` default preserved.
- Paper-mode now bails to touch instead of synthesising — **net safety improvement over what I originally approved**.
- `ENABLE_LIVE_TRADING` not read by lifecycle for activation; pre-existing code default `True` is overridden in fly.toml `[env]` (already documented in PROJECT_STATE KNOWN ISSUES).
- Refund math uses `Decimal`.

### Phase 6 — Latency (PASS)
Same as original audit. New `_broker_fills` aggregation removes the second `/data/trades` round-trip per cancel/expiry/fill, so latency is marginally better.

### Phase 7 — Infra (PASS)
APScheduler `order_lifecycle` job: `max_instances=1, coalesce=True` (`scheduler.py:475-477`).

### Phase 8 — Telegram (PASS)
Four lifecycle alert events wired (filled / cancelled / expired user, stale operator). Same as original audit.

---

## 3. CRITICAL ISSUES

**None found.**

Non-blocking observations (recommended post-merge fix-forwards):

1. **`_broker_fills` returns `[]` when `size_matched` is missing/zero on the broker payload** (`lifecycle.py:680-685`). For a partial-fill-then-cancel scenario where the broker omits `size_matched`, the cancel/expiry path would refund the full notional even though the user holds matched shares (double-credit). Polymarket's documented contract for `/data/order/{id}` includes `size_matched`, so this is defensive concern, not an active bug. **P1 recommendation**: add an explicit regression test for `{"status": "cancelled"}` with no `size_matched` field — assert refund is NOT full notional, OR that an operator alert fires instead.
2. Forge report §5 still says "23 hermetic + 1 importorskip = 24 tests". Actual is 29. Cosmetic doc drift.
3. 7 cosmetic asyncio warnings on sync helper tests (already noted in forge known-issues).
4. APScheduler poll job has no jitter (low-impact at 30s, single-instance today).
5. Per-order `conn.acquire()` not pooled into a single sweep transaction (acceptable at current scale).

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
- Architecture −1: forge test-count doc drift.
- Failure modes −1: P1 recommendation — add coverage for `_broker_fills` missing-`size_matched` edge case.
- Infra+TG −1: no jitter on poll job.
- Latency −1: per-order conn acquire.

---

## 5. GO-LIVE STATUS

**APPROVED** — Score 96/100, zero critical issues.

Reasoning:
- Migration 015 fully idempotent (every DDL guarded; rollback block present).
- All five lifecycle dispatch buckets exercised end-to-end; 29/29 lifecycle tests + 30/30 Phase 4A regression green at HEAD.
- Refund math correctly handles partial-fill cancel/expiry when broker payload includes `size_matched` (verified by hermetic test).
- Paper-mode now actively SAFER than original PR — bails to touch instead of synthesising a fill.
- Activation posture remains PAPER ONLY: `USE_REAL_CLOB` default `False`; `ENABLE_LIVE_TRADING` not read by lifecycle.
- APScheduler `order_lifecycle` job concurrency `max_instances=1, coalesce=True`.

Recommend WARP🔹CMD merge.

---

## 6. FIX RECOMMENDATIONS

All recommendations are POST-MERGE fix-forward; none block this PR.

**Priority P1 (defensive hardening):**

1. Add a regression test that simulates broker `/data/order/{id}` returning `{"status": "cancelled"}` with no `size_matched` field. Assert refund is NOT the full notional, OR that an operator alert fires — guards against future broker schema drift.
2. Optional: log a `logger.warning` in `_broker_fills` when `size_matched` is missing on a terminal-status payload (`lifecycle.py:680-685`). Surfaces the broker schema drift case quickly without changing behavior.

**Priority P3 (cosmetic / doc):**

3. Update forge report §5 test count (`24` → `29`).
4. Drop `pytestmark = pytest.mark.asyncio` from sync helper tests in `tests/test_order_lifecycle.py` to silence 7 cosmetic warnings.
5. Optional: jitter `ORDER_POLL_INTERVAL_SECONDS` ±5s on multi-pod deploys.

**Priority P2 (next-lane):**

6. Wire ledger reversal directly into lifecycle for live mode (forge already lines this up as `WARP/CRUSADERBOT-LIFECYCLE-LEDGER-REVERSAL`).

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

---

## 8. DONE OUTPUT

```
Done -- GO-LIVE: APPROVED. Score: 96/100. Critical: 0.
PR: WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE
Audit baseline: HEAD a484012
Report: projects/polymarket/crusaderbot/reports/sentinel/order-lifecycle.md (FINAL — supersedes 005c55a APPROVED + 9fe32d7 BLOCKED)
State: PROJECT_STATE.md updated to APPROVED
NEXT GATE: Return to WARP🔹CMD for final decision.
```
