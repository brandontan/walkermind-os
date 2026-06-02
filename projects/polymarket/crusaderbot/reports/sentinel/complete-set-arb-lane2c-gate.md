# WARP•SENTINEL — complete-set-arb Lane 2C-1 (gate re-scope + kill switch)

**Branch:** `WARP/ROOT/complete-set-arb-lane2c-gate`
**Tier:** MAJOR · **Claim:** FOUNDATION · **Env:** dev
**Verdict:** APPROVED · **Score:** 96/100 · **Critical:** 0

Owner-requested focus: prove `COUNT(DISTINCT LEAST(id, COALESCE(paired_position_id,
id)))` is mathematically identical to the old `COUNT(*)` for all existing un-paired
rows, and verify zero impact on directional trade concurrency. Audited against code.

## TEST PLAN

`_open_position_count` (gate step-7 concurrency cap) changed from `COUNT(*)` to a
set-aware `COUNT(DISTINCT LEAST(...))`. Prove: (1) exact identity on the current
(all-un-paired) dataset, (2) zero behavioural change for directional trades,
(3) correct counting once sets exist, (4) kill switch defaults OFF.

## PHASE 0 — PRE-TEST

- Report at correct path, 6 sections + metadata — `reports/forge/complete-set-arb-lane2c-gate.md` → PASS
- `PROJECT_STATE.md` updated (Lane 2C-1 COMPLETED + NEXT → 2C-2) → PASS
- No `phase*/` folders; change in `domain/risk/gate.py` + `config.py` → PASS
- Evidence: `gate.py:96-117` + `tests/test_complete_set_gate_rescope.py` → PASS

## FINDINGS

### 1. SQL identity on un-paired rows — PASS (proven)
For any row with `paired_position_id IS NULL`:
`COALESCE(paired_position_id, id)` = `COALESCE(NULL, id)` = `id`; `LEAST(id, id)` =
`id`. So the counted expression is `id` for every un-paired row. `positions.id`
is the PRIMARY KEY → NOT NULL and unique. Therefore:
- never NULL → `COUNT(DISTINCT …)` drops no rows (its NULL-skipping cannot bite);
- all values distinct → `COUNT(DISTINCT id)` = number of rows = `COUNT(*)`.
**Exact identity for any all-un-paired dataset** — which is the entire current
production state (mig 078 not yet applied; column defaults NULL; no writer until
Lane 2C-2). The WHERE clause (`user_id` + `status IN ('open','pending_settlement')`)
is unchanged, so the row set counted is identical.

### 2. Zero impact on directional concurrency — PASS
Directional INSERTs never set `paired_position_id` — `paper.execute`
(`paper.py:58-71`) and the live INSERT path omit the column → it defaults NULL.
So every directional position is un-paired → Finding 1 applies → step-7
`cur >= max_concurrent` (`gate.py:347`) evaluates byte-identically. No directional
trade can be admitted or rejected differently. `_open_position_count` is a
gate-private helper used only at step 7 (no other caller) → blast radius is step 7.

### 3. Correct counting once sets exist — PASS
- Open set (A.paired=B, B.paired=A, both open): row A → `LEAST(A,B)=min(A,B)`;
  row B → `LEAST(B,A)=min(A,B)` → same key → counted ONCE (set = 1 unit). ✓
- Lone open leg (sibling already closed/filtered out): single row → one distinct
  `min` value → counts 1 (no under-count in the transient state). ✓
- Sibling row deleted: `ON DELETE SET NULL` (mig 078) nulls the surviving leg's
  `paired_position_id` → treated as un-paired → counts 1; no dangling reference. ✓
- `LEAST(uuid, uuid)` uses PostgreSQL's total UUID ordering → deterministic, both
  legs compute the same minimum regardless of scan order. ✓

### 4. Step 8 (correlated exposure) untouched — PASS
Deliberately unchanged (`gate.py:359-370`). Each leg's `size_usdc` is its own
cost, so `SUM(size_usdc)` over a set already equals the true combined cost (not
2×); counting a hedged anti-correlated set at full cost is conservative (stricter
than its real risk) — the safe direction. No silent loosening.

### 5. Kill switch — PASS
`COMPLETE_SET_ARB_ENABLED: bool = False` (`config.py`) defaults OFF; test
`test_complete_set_arb_disabled_by_default` pins it. No reader until Lane 2C-2 →
the whole path is dormant.

## STABILITY SCORE

Arch 20/20 · Functional 20/20 (identity proven; 24 tests incl. concurrency +
config regressions) · Failure modes 19/20 · Risk 20/20 (zero directional impact,
conservative) · Infra/Latency N/A. **Total: 96/100.** −4: the set-counting
behaviour (Findings 3) is proven by reasoning + a source-pin test, not by a
real-DB integration test (hermetic only). Recommended once mig 078 is applied
(Lane 2C-2).

## GO-LIVE STATUS

APPROVED. The change is provably inert on the current dataset and conservative
once sets exist. It authorizes nothing executable — the scan branch, set gating,
exit handling, and LIVE are Lane 2C-2 / Lane 3.

## CRITICAL ISSUES

None found.

## FIX RECOMMENDATIONS (non-blocking)

- M-1: add a real-DB integration test for the set-counting (open set = 1, lone
  leg = 1, mixed directional + set) when migration 078 is applied in Lane 2C-2.
- M-2 (perf, negligible): `COUNT(DISTINCT expr)` sorts/hashes vs `COUNT(*)`; on a
  per-user open set (typically < 20 rows) the cost is immaterial — no action.

## NOTES

WARP•SENTINEL does not merge. Per Mr. Walker, WARP•CMD merges on APPROVED. This
verdict commit triggers a fresh CI run — merge on green. WARP•R00T acted as
SENTINEL under owner authorisation.
