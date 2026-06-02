# WARP•SENTINEL — Complete-Set Arb Lane 3A (live position metadata)

**Branch:** `WARP/ROOT/complete-set-arb-lane3a-live-metadata`
**PR:** #1566
**Validation Tier:** MAJOR (modifies the live execution / order path — AGENTS.md)
**Audit scope:** the additive persistence of `active_preset` + `strategy_metadata`
on the live position INSERT; confirm NO change to order submission, activation
guards, sizing, or capital flow, and that the live path stays dead by default.
**Default assumption:** UNSAFE until every check passes.

---

## PHASE 0 — PRE-TEST

- Forge report present, correct path/naming, 6 sections + metadata, tier MAJOR
  with an explicit SENTINEL validation handoff — PASS
- `state/PROJECT_STATE.md` + `CHANGELOG.md` updated (MAJOR, SENTINEL-required) — PASS
- No `phase*/` folders; domain/execution structure intact — PASS
- Implementation evidence present for the claimed surface — PASS

Phase 0: PASS.

---

## FINDINGS (evidence = file:line)

### 1. Additive-only — no execution-behaviour change — PASS

The entire diff is: two new keyword params on `live.execute` (`active_preset`,
`strategy_metadata`, both defaulting `None`, `live.py:101-102`), two columns added
to the `INSERT INTO positions` (`live.py:337-346`), and the router forwarding both
(`router.py:63-65`). Confirmed UNCHANGED: `assert_live_guards` (live.py:51-82), the
CLOB `post_order` submission, order-type (FOK/GTC) handling, slippage/limit-price
math, the `orders` INSERT/idempotency, and the ledger debit. No order is submitted
differently; a live position simply gains the per-position context paper already
writes.

### 2. INSERT placeholder/arg alignment — PASS (critical on a live write)

`live.py:339-346`: `VALUES ($1,$2,$3,$4,$5,$6,$6,$7,$8,'live','open',$9,$10,$11,
$12::jsonb)` against 12 args in order — `user_id$1, market_id$2, order_id$3,
side$4, size_usdc$5, limit_price$6 (entry+current), tp_pct$7, sl_pct$8,
strategy_type$9, market_question$10, active_preset$11, json.dumps(meta)/NULL$12`.
Count and ordering correct; `$6` is intentionally reused for `entry_price` +
`current_price` (pre-existing). No off-by-one.

### 3. Exact paper parity — PASS

`paper.py:58-70` writes the same columns in the same order with `$12::jsonb` and
`json.dumps(strategy_metadata) if strategy_metadata else None`. The live path now
matches byte-for-byte in shape — closing the asymmetry, not inventing new
behaviour. Both columns pre-exist (active_preset mig 062, strategy_metadata mig
076) — no migration, no schema risk.

### 4. Guards / dead-by-default — PASS

The live path remains gated by `assert_live_guards`: 5 default-OFF flags
(`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`,
`RISK_CONTROLS_VALIDATED`, `SECURITY_HARDENING_VALIDATED`) + `USE_REAL_CLOB` +
`role==admin` + `trading_mode==live`. This lane touches none of them. No real
capital can move from this change.

### 5. Safety improvement (active_preset) — PASS

`OpenPositionForExit.active_preset` (registry.py:233) drives the
close_sweep/safe_close/flip_hunter force-exits. Pre-fix, a live candle position
would carry `active_preset=NULL` and silently skip its forced exit — a real
latent stranding risk for live candle trading. Now persisted → the exit watcher
can identify the preset. Net safety-positive.

### 6. Tests — PASS

44 pass (`test_live_execution_rewire.py` + `test_candle_auto_router.py`). The 2
new tests pin both columns reaching the INSERT (`active_preset` $11 / second-to-last
arg, `strategy_metadata` `$12::jsonb` / last arg) and the NULL path for both. ruff
+ py_compile clean.

---

## CRITICAL ISSUES

None found.

---

## STABILITY SCORE

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 20 | Exact paper parity; minimal additive diff |
| Functional | 20 | 20 | Both columns + NULL path verified, placeholder alignment correct |
| Failure modes | 20 | 19 | Additive; no new failure surface (no order/guard change) |
| Risk/capital | 20 | 20 | Guards untouched; live path dead by default; no capital flow change |
| Infra+TG | 10 | 9 | No migration (columns exist); N/A elsewhere |
| Latency | 10 | 10 | No added I/O |
| **Total** | **100** | **98** | |

---

## GO-LIVE STATUS

**VERDICT: APPROVED** — Score 98/100, zero critical issues.

A minimal, paper-parity, additive change that persists `active_preset` +
`strategy_metadata` on live positions. No change to order submission, activation
guards, sizing, or capital flow; the live path remains dead behind the default-OFF
guards. It closes a real latent stranding gap (NULL `active_preset` skipping live
force-exits) and unblocks Lane 3B. Safe to merge.

Note: this only persists metadata. The actual LIVE two-leg execution primitive
(`book_complete_set_live`, FOK + naked-leg auto-unwind + idempotent recovery) is
Lane 3B and will get its own MAJOR SENTINEL audit.

---

## FIX RECOMMENDATIONS

None required for merge.

---

## NEXT GATE

Return to WARP🔹CMD for the merge decision. Per the LIVE-touch policy, owner
confirms the merge (SENTINEL does not merge).
