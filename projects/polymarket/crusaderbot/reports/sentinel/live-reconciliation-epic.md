# WARP•SENTINEL Report — LIVE reconciliation epic (WARP-74)

Branch: `WARP/ROOT/live-reconciliation-epic`
Head audited: `fda88fe` (post conflict-resolution merge commit)
PR: #1613
Role: WARP•SENTINEL (WARP•R00T executing)
Environment: `dev` (hermetic — live-broker proof is a staging gate, not a SENTINEL
  blocker; noted in forge report Known Issues)
Source: `projects/polymarket/crusaderbot/reports/forge/live-reconciliation-epic.md`
Date: 2026-06-04

---

## TEST PLAN

### Environment

| Env | Infra | Risk | Telegram |
|---|---|---|---|
| `dev` | warn only | ENFORCED | warn only |

### Phase scope

- Phase 0 — Pre-Test gates (report, state, structure)
- Phase 1 — Functional per module (Chunk A reconciler, Chunk B kill-cancel, Chunk C drift/router)
- Phase 2 — Pipeline E2E (RISK before EXECUTION; no bypass)
- Phase 3 — Failure modes (API fail / WS / timeout / rejection / partial fill / stale / broker hiccup / dedup)
- Phase 4 — Async safety (race conditions, state corruption, connection hygiene)
- Phase 5 — Risk rules (Kelly / position / loss / drawdown / liquidity / dedup / kill switch)
- Phase 6 — Latency profile
- Phase 7 — Infra (PostgreSQL; Redis n/a for this epic)
- Phase 8 — Telegram alert coverage

---

## FINDINGS

### Phase 0 — Pre-Test

**PASS** on all gates.

- Report `projects/polymarket/crusaderbot/reports/forge/live-reconciliation-epic.md`
  exists; all 6 mandatory sections present; mandatory metadata (Tier, Claim Level,
  Validation Target, Not in Scope, Suggested Next Step) present.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` updated (Last Updated
  2026-06-04 21:40 WIB; reflects #1613 OPEN/HELD + path decision pending).
- Zero `phase*/` folders in repo tree (`grep -rn 'phase[0-9]*/'` — 0 production hits).
- Implementation evidence: 30 new hermetic tests across 4 suites (forge report
  claims 31 — minor count discrepancy, not a blocker); 135 regression tests green.
- Note (non-blocking): forge report header references `claude/cool-hamilton-KaLWA`
  — the original non-compliant branch name before the #1613 compliant re-creation.
  Code is identical per WARP🔹CMD statement and verified by diff. Forge report
  metadata is stale but code is truth.

### Phase 1 — Functional Testing

**PASS** on all modules.

**Chunk A — `reconcile_live_orders` (`live_reconcile.py:332`)**

- Paper/non-live skip: `live_reconcile.py:344` `if not bool(getattr(s, "USE_REAL_CLOB", False)): return {"scanned":0,"skipped_paper":True}` ✓
- Disabled skip: `live_reconcile.py:346` `LIVE_RECONCILE_ENABLED` gate ✓
- DB scan: `mode='live' AND status='unknown' AND strategy_type ~ ^(directional prefixes)` — complete-set intentionally excluded ✓
- Adopt path (`live_reconcile.py:295-303`): unique untracked resting order, price mandatory match (`abs(b_price - exp_price) <= 0.03`), size tolerant of raw vs 1e6 fixed-math — `UPDATE orders SET status='pending', polymarket_order_id=$2... AND status='unknown'` — race-safe with `AND status='unknown'` guard ✓
- Mismatch → page + stamp (`live_reconcile.py:283-294`): never adopts an unrelated order ✓
- Multiple untracked → `_halt_and_page` + kill switch engaged (`live_reconcile.py:305-315`): deliberately fail-safe ✓
- No resting order → page-once + stamp `no_resting_order` (`live_reconcile.py:317-329`): never auto-cancels ✓
- Broker query failure → page + `"error"` (`live_reconcile.py:267-275`): never assumes ✓
- Test evidence: `test_live_reconcile.py` 15 tests cover all branches ✓

**Chunk A — `reconcile_closing_positions` (`live_reconcile.py:549`)**

- Paper skip: `live_reconcile.py:563` ✓
- Startup mode: scans ALL live `status='closing'` rows (no stale filter) ✓
- Periodic mode: excludes `error_msg LIKE '%reconcile_paged%'` rows (alert-fatigue guard) + `closing_at < NOW() - LIVE_CLOSING_STALE_SEC` ✓
- NULL `close_order_id` → page + stamp `paged_no_id` (`live_reconcile.py:454-463`): handles pre-migration rows ✓
- Terminal FILLED → `_finalize_closed` + ledger credit (`live_reconcile.py:495-513`): proceeds from real fills; `RETURNING id` race-safe ✓
- Terminal KILLED + zero fills → `_rollback_closing` to `open` (`live_reconcile.py:531-537`): clean retry path ✓
- Terminal KILLED + partial fill → page `paged_partial_close` (`live_reconcile.py:516-527`): NEVER finalizes an ambiguous partial ✓
- Non-terminal (including in-flight partial) → page + leave `closing` (`live_reconcile.py:487-493`): NEVER premature-finalize ✓
- Broker query failure → page + `"error"` (`live_reconcile.py:468-476`): never assumes ✓

**Chunk B — `kill_switch_exec._broker_cancel_all_orders` (`kill_switch_exec.py:73`)**

- Paper no-op: `kill_switch_exec.py:92` `if not bool(getattr(s, "USE_REAL_CLOB", False)): return {skipped_paper: True}` ✓
- Sequence: set_active(pause) → `_broker_cancel_all_orders()` → `_cancel_pending_orders()` → `_set_system_flag` → `_write_audit_log` → `notify_operator` (`kill_switch_exec.py:114-183`) — broker cancel at step 2 (BEFORE DB cancel step 3) ✓
- Best-effort: `kill_switch_exec.py:103` `except Exception: BLE001` — broker cancel failure captured in dict, never blocks sequence ✓
- Failure escalation: `kill_switch_exec.py:170-176` — if attempted+!cancelled → explicit `"BROKER CANCEL FAILED — resting orders may still be LIVE on Polymarket"` operator page ✓
- `client.aclose()` in `finally` block (`kill_switch_exec.py:107`) ✓
- Test evidence: `test_kill_switch_broker_cancel.py` 5 tests; `test_kill_switch.py` + `test_kill_switch_paths.py` regression green ✓

**Chunk C — `detect_order_drift` (`drift_detector.py:49`)**

- Paper no-op: `drift_detector.py:54` ✓
- Disabled gate: `ORDER_DRIFT_DETECT_ENABLED` (`drift_detector.py:56`) ✓
- Alert-only: zero `INSERT`/`UPDATE` in `drift_detector.py` (grep confirmed) ✓
- broker-only (untracked exposure) + db-only (phantom open) both surface via audit + `notify_operator` ✓
- `client.aclose()` in outer `finally` (`drift_detector.py:131`) ✓
- Test evidence: `test_order_drift_detector.py` 6 tests ✓

**Chunk C — `router._is_infra_degraded` (`router.py:45`)**

- Case-insensitive fragment match (`reason_lower = (reason or "").lower()`) (`router.py:48`) ✓
- INFRA-DEGRADED path: `live_infra_degraded_paper_fallback` audit + `notify_operator` + `logger.critical` (`router.py:108-130`) ✓
- DELIBERATE path: unchanged `live_blocked_fallback_paper` ✓
- Test evidence: `test_router_infra_fallback.py` 4 tests ✓

### Phase 2 — Pipeline E2E

**PASS.**

- RISK before EXECUTION invariant: the new sweeps are APScheduler background
  interval jobs entirely off the hot execution path — they cannot short-circuit
  the risk gate. `test_live_execution_rewire.py` + `test_kill_switch_paths.py`
  regression green (135 pass, 1 skip). ✓
- `complete_set_reconcile` untouched; distinct job id — no interference ✓
- `OrderLifecycleManager.poll_once()` (DB→broker direction) untouched ✓
- The new `reconcile_live_orders` (broker→DB direction) is complementary ✓

### Phase 3 — Failure Modes

**PASS** on all eight vectors.

| Failure mode | Evidence |
|---|---|
| Broker API fail (`get_open_orders` raises) | `live_reconcile.py:267` `except Exception: BLE001` → page, returns `"error"`, never raises |
| Broker API fail (`get_order`/`get_fills` raises) | `live_reconcile.py:468` same pattern |
| WS disconnect | n/a (no WS; CLOB client constructed per sweep, discarded after) |
| Timeout / partial fill in flight | `live_reconcile.py:487` non-terminal → page, never premature-finalize |
| Order rejection (untracked resting) | `live_reconcile.py:283` mismatch → page-once; multiple → halt+page |
| Stale data / `closing_at` NULL | `live_reconcile.py:454` NULL close_order_id → page + stamp; periodic query treats NULL as reconcilable |
| Broker query latency spike | No timeout set per call (deferred to ClobClient internals); per-item isolation (`live_reconcile.py:393`) means one slow order doesn't block others |
| Kill-switch broker cancel fail | `kill_switch_exec.py:103` fail-soft + `kill_switch_exec.py:171` operator page; DB cancel + gate halt proceed regardless |

Per-item isolation proven: `live_reconcile.py:389-396` inner `try/except` inside for-loop; `live_reconcile.py:610-616` same for closing sweep. ✓

### Phase 4 — Async Safety

**PASS.** Zero threading. 60 `async def`/`await` usages in `live_reconcile.py` (grep count).

- Race-safe close finalize: `live_reconcile.py:421` `UPDATE positions ... WHERE id=$1 AND user_id=$4 AND status='closing' RETURNING id` — if concurrent process wins, `updated is None` → `_finalize_closed` returns `False` → no double-close, no double-credit. ✓
- Race-safe adopt: `live_reconcile.py:243` `UPDATE orders ... AND status='unknown'` — if lifecycle poller resolved the order between scan and adopt, UPDATE no-ops. ✓
- Race-safe rollback: `live_reconcile.py:442` `WHERE status='closing'` guard. ✓
- No shared mutable module state between sweeps. ✓
- `client.aclose()` in `finally` blocks in all three top-level sweep functions (`live_reconcile.py:397-401`, `live_reconcile.py:617-621`, `drift_detector.py:131-135`). ✓
- Each `pool.acquire()` via separate `async with` context — no connection held across awaits. ✓

### Phase 5 — Risk Rules

**PASS.** All existing gates UNTOUCHED.

| Rule | Status |
|---|---|
| Kelly fraction `a = 0.25` | Zero Kelly references in any new module ✓ |
| Position <= 10% | Untouched ✓ |
| Daily loss limit -$2k | Untouched ✓ |
| Drawdown > 8% circuit | Untouched ✓ |
| ENABLE_LIVE_TRADING guard | Not bypassed; new sweeps gate on `USE_REAL_CLOB` (upstream of ENABLE_LIVE_TRADING) ✓ |
| Signal deduplication | Untouched ✓ |
| Kill switch | Enhanced (broker cancel added) — never weakened ✓ |
| $10k liquidity floor | Untouched ✓ |
| Slippage guard | Untouched ✓ |

**Migration deploy gate (prior CONDITIONAL finding from #1611 — RESOLVED):**
`live.py:487-508` — `closing_at`/`close_order_id` UPDATE is now:
- Kept OUT of the atomic `'closing'` claim
- Wrapped in `try: ... except Exception as _exc: BLE001 — telemetry write must not break close`
- Comment explicitly: "If the code deploys before the migration, a missing column here only logs — the core close can never be bricked by deploy ordering"
- The reconciler treats NULL `closing_at` as reconcilable (periodic query `closing_at IS NULL` branch)
**Deploy before migration 082 is now safe.** ✓

### Phase 6 — Latency

**PASS.**

All new sweeps are APScheduler interval jobs with `max_instances=1, coalesce=True`:
- `live_unknown_order_reconcile`: every 300s
- `live_closing_reconcile`: every 300s
- `live_closing_reconcile_startup`: one-shot at boot
- `order_drift_detect`: every 600s
- `live_order_reconcile` (#1612, merged): every 120s

None of these jobs sit on the hot ingest (<100ms) / signal (<200ms) / exec (<500ms) path. ✓

### Phase 7 — Infra

**PASS.**

- PostgreSQL: uses `get_pool()` throughout; all queries parameterized ($1/$2/…); no raw string interpolation. ✓
- Migration 082: `ALTER TABLE positions ADD COLUMN IF NOT EXISTS` × 3 — idempotent, nullable, additive. `CREATE INDEX IF NOT EXISTS` partial index for performance. Explicitly safe to apply before OR after deploy. ✓
- Redis: not touched by this epic. ✓
- No new external services introduced. ✓
- `ruff check` clean (forge report confirmed); `py_compile` clean (verified locally). ✓

### Phase 8 — Telegram Alert Coverage

**PASS.**

Seven distinct alert events with Telegram formatting:

1. `live_reconcile.py:257-263` — `⚠️ LIVE RECONCILE` — token unresolved; page-once
2. `live_reconcile.py:287-292` — `⚠️ LIVE RECONCILE — size/price mismatch` — lone untracked order doesn't match; page-once
3. `live_reconcile.py:308-313` — `🛑 LIVE RECONCILE — UNTRACKED EXPOSURE, TRADING HALTED` (+ kill failed variant `🚨🚨 HALT DID NOT ENGAGE`) — multiple untracked resting orders; halt+page
4. `live_reconcile.py:320-327` — `⚠️ LIVE RECONCILE — verify on exchange` — no resting order; page-once
5. `kill_switch_exec.py:170-181` — `🚨 KILL SWITCH ACTIVATED` + `⚠️ BROKER CANCEL FAILED — resting orders may still be LIVE` conditional suffix
6. `router.py:111-130` — `🚨 LIVE INFRA DEGRADED — fell back to PAPER` — distinct from deliberate fallback
7. `drift_detector.py:111-127` — `⚠️ ORDER DRIFT DETECTED` — broker-only / db-only counts + id samples

All pages via `notifications.notify_operator()` which is best-effort (wrapped in `try/except`); operator page failure never blocks the underlying action. ✓

---

## CRITICAL ISSUES

**None found.**

---

## STABILITY SCORE

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 19/20 | Fail-safe design throughout; three complementary reconcilers with distinct ownership; conservative adopt guard; deploy-gate fix proven at code level. -1 live-broker proof deferred (acceptable: hermetic + staging gate is the declared next step) |
| Functional | 20% | 19/20 | 30 new hermetic tests cover every branch across 4 suites; all 8 recovery branches proven (adopt / mismatch-page / halt+page / no-resting-page / finalize / rollback / partial-page / non-terminal-page); forge report test count off by 1 (30 actual vs 31 claimed) |
| Failure modes | 20% | 20/20 | Zero silent failures; `except Exception: BLE001` on every external call; `client.aclose()` in every `finally`; per-item isolation inside all for-loops; kill-cancel failure surfaced with explicit operator page |
| Risk rules | 20% | 20/20 | Kelly/capital/guards completely untouched; kill switch enhanced not weakened; migration deploy gate fully fail-soft; no capital-path mutation in reconcile sweeps |
| Infra + Telegram | 10% | 9/10 | 7 distinct alert events with HTML formatting; correct pool usage; parameterized queries; migration idempotent. -1 live-broker integration not yet exercised on Fly |
| Latency | 10% | 10/10 | All sweeps on background APScheduler intervals; none on hot execution path; `max_instances=1, coalesce=True` on all jobs |

**Total: 97/100**

---

## GO-LIVE STATUS

**VERDICT: APPROVED**

Score 97/100. Zero critical issues. All three WARP-73 P0 gaps are closed:

- P0 #1 (`'unknown'` order orphan) — conservative adopt/halt/page logic proven hermetically; never fabricates, never double-adopts.
- P0 #2 (stranded `'closing'` position) — terminal-only recovery (finalize/rollback/page); NEVER premature-finalizes a non-terminal or partial close; deploy before migration 082 is safe.
- P0 #3 (kill switch no broker cancel) — broker cancel runs before DB cancel; best-effort; explicit operator escalation on failure.

**Prior CONDITIONAL finding (WARP•SENTINEL #1611, score 84) — RESOLVED:**
The migration-082 deploy gate that blocked approval in #1611 is fixed: `live.close_position` now wraps the `closing_at`/`close_order_id` UPDATE in `try/except BLE001` with explicit comment documenting it as non-fatal and migration-order-safe. The core close path (`claim → SELL → finalize`) never references the new columns; a missing column only logs.

**Remaining observational notes (non-blocking, no merge conditions):**

1. Closing reconciler engaging the kill switch (`live_reconcile.py:305-315`): when >1 untracked resting orders are found on a token, `_halt_and_page` is called. This is a deliberately fail-safe choice — confirmed untracked exposure warrants a halt. Material runtime authority, correct direction. Documented in forge report.
2. Forge report branch reference stale (`claude/cool-hamilton-KaLWA`): pre-dates the compliant branch re-creation. Code on `WARP/ROOT/live-reconciliation-epic` is verified identical per WARP🔹CMD and code review.
3. 30 vs 31 test count: forge report claims 31 new hermetic tests; actual count is 30 across 4 suites. Minor discrepancy; 30 tests pass and provide full branch coverage.

**Pre-merge operator action (not a SENTINEL gate — owner decision):**
Apply migration `082` to Supabase production before the first Fly deploy that includes this branch. The code is deploy-safe WITHOUT the migration (fail-soft); the migration must land BEFORE the first live `reconcile_closing_positions` sweep runs to enable full crash-recovery. After merge + migration: staging run to satisfy acceptance criteria (simulated crash → no orphan; STOP cancels resting GTC).

---

## FIX RECOMMENDATIONS

**No critical fixes required.** Priority ordered for completeness:

1. **(None — CRITICAL)** Zero critical issues.
2. **(LOW — polish)** Update forge report branch reference from `claude/cool-hamilton-KaLWA` to `WARP/ROOT/live-reconciliation-epic` on next maintenance pass. Not required for merge.
3. **(LOW — docs)** Forge report test count (31 vs 30). Correct on next maintenance pass. Not required for merge.
4. **(ADVISORY — future lane)** `'unknown'` instant-fill not auto-reconstructed: when no resting order exists, we page for manual reconcile. A future lane could attach a market-trade scan keyed to the signer to auto-recover the instant-fill case. Documented in forge Known Issues. Out of scope for this epic.
5. **(ADVISORY — future lane)** `close_order_id` blind window: a crash in the sub-millisecond gap between `post_order` returning and the `close_order_id` UPDATE leaves a `closing` row with no id → pages (never assumes). Acceptable; documented.

---

## TELEGRAM PREVIEW

### Alert events and format

```
#1 Unknown order token unresolved:
⚠️ LIVE RECONCILE
Unknown order <order_id> market=<market_id> — token unresolved; reconcile manually.

#2 Size/price mismatch (lone untracked order, not ours):
⚠️ LIVE RECONCILE — size/price mismatch
Unknown order <order_id> market=<market_id>:
the lone untracked resting order on the token does not match our size/price
— NOT adopting. Reconcile manually.

#3 Multiple untracked resting orders — HALT (kill-switch engaged):
🛑 LIVE RECONCILE — UNTRACKED EXPOSURE, TRADING HALTED
Unknown order <order_id> market=<market_id> token=<token>
— N untracked resting orders match; manual reconcile required.

  (if kill-switch itself fails):
🚨🚨 HALT DID NOT ENGAGE — STOP THE BOT MANUALLY 🚨🚨
[above detail]

#4 No resting order found (instant-fill or never landed):
⚠️ LIVE RECONCILE — verify on exchange
Unknown order <order_id> market=<market_id> side=<side> size=$<size_usdc>
No resting order on the token. Confirm it never filled (or reconcile the fill)
on Polymarket, then clear the row.

#5 Kill switch activated (with broker cancel result):
🚨 KILL SWITCH ACTIVATED
Reason: <reason>
By: <triggered_by>
[if broker cancel failed:]
⚠️ BROKER CANCEL FAILED — resting orders may still be LIVE on Polymarket.
Cancel manually on the exchange NOW.

#6 Live infra degraded — silent paper fallback detected:
🚨 LIVE INFRA DEGRADED — fell back to PAPER
market=<market_id>
A live trade could not reach the exchange (CLOB dependency failure) and was
routed to paper.
reason: <exc>

#7 Open-order drift detected:
⚠️ ORDER DRIFT DETECTED
• N resting order(s) LIVE on the exchange but UNTRACKED in DB (orphan exposure):
  <id1, id2, ...>
• N order(s) marked open in DB but NOT on the exchange (likely filled/cancelled mid-cycle):
  <id1, id2, ...>
```

### Audit actions surfaced

- `live_reconcile_adopted` — broker id re-linked, `unknown→pending`
- `live_reconcile_closed` — stranded close finalized; pnl_usdc in payload
- `live_reconcile_close_rolled_back` — kill-confirmed SELL rollback to `open`
- `order_drift_detected` — broker-only / db-only id lists (capped at 50)
- `KILL_SWITCH_ACTIVATED` — broker_cancel outcome in reason field

### Done output

```
Done -- WARP-74 LIVE reconciliation epic SENTINEL validation complete.
PR: WARP/ROOT/live-reconciliation-epic (#1613)
Report: projects/polymarket/crusaderbot/reports/sentinel/live-reconciliation-epic.md
State: PROJECT_STATE.md updated
NEXT GATE: Return to WARP🔹CMD for final merge decision.
GO-LIVE: APPROVED 97/100. Critical: 0.
```
