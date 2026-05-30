# Forge Report — WARP/R00T/bankroll-dynamic-sizing

**Date:** 2026-05-30 16:49 Asia/Jakarta
**Role:** WARP•R00T
**Branch:** WARP/R00T/bankroll-dynamic-sizing
**Lane:** 5 of 5 (Polybot directive — defensive guardrails campaign — FINAL LANE)
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** _build_trade_signal scales proposed_size_usdc by EMA-smoothed bankroll multiplier when enabled
**Not in Scope:** Kelly + position caps inside the risk gate (still authoritative, applied after); DB-persisted baseline; cross-user aggregation
**Suggested Next:** WARP🔹CMD review → merge → campaign closure

---

## 1. What was built

Per-user, EMA-smoothed bankroll multiplier that scales the candidate's base `suggested_size_usdc` before it reaches the risk gate. Disabled by default (`BANKROLL_DYNAMIC_SIZING_ENABLED=false`) so the merge is zero-impact until the operator explicitly opts in.

**Why:** the strategy's `suggested_size_usdc` is computed from `capital_allocation_pct × balance` — but it doesn't react to *recent* performance within the bankroll. The dynamic multiplier closes that loop:
- Recent winners get slightly larger entries (bounded by `BANKROLL_MULTIPLIER_MAX`).
- Recent losers get slightly smaller entries (bounded by `BANKROLL_MULTIPLIER_MIN`).
- First observation seeds the baseline → multiplier = 1.0 (no change for a brand-new user or after a restart).

**Risk gate stays authoritative.** The multiplier scales the INPUT to `engine.execute`; Kelly + max-position-pct + per-trade ceiling inside the engine still authoritatively bound the FINAL size. Worst case: a 1.5× multiplier on a 10% position cap → still bounded at 10% (cap wins). Multiplier can't blow past existing risk limits.

**Operator escape hatches (multiple layers):**
- `BANKROLL_DYNAMIC_SIZING_ENABLED=false` (kill switch) — instant revert to current behaviour, no redeploy.
- `BANKROLL_MULTIPLIER_MIN=1.0` + `BANKROLL_MULTIPLIER_MAX=1.0` — runtime bounds collapse to no-op.
- Non-positive / non-finite balance → multiplier 1.0 (safety).
- Any config-read exception → logged WARNING + fall back to base size (AGENTS.md zero-silent-failures rule).

---

## 2. Current system architecture (relevant slice)

```text
services.signal_scan.signal_scan_job (module level)
    ├─ NEW: _bankroll_ema_baseline: dict[user_id, float]
    ├─ NEW: _bankroll_multiplier(user_id, current_balance, *, min, max, alpha)
    │       ├─ fail-safe: non-positive / non-finite balance → 1.0
    │       ├─ fail-safe: no prior baseline → seed at current, return 1.0
    │       ├─ raw_multiplier = current_balance / baseline
    │       ├─ update EMA: alpha * current + (1-alpha) * baseline
    │       └─ clamp(raw_multiplier, [min, max])
    └─ NEW: _bankroll_reset_for_tests()

services.signal_scan.signal_scan_job._build_trade_signal
    ├─ existing: _side, _price, _market_liquidity computed
    ├─ NEW: try lazy-import get_settings
    │       ├─ if BANKROLL_DYNAMIC_SIZING_ENABLED:
    │       │       mult = _bankroll_multiplier(user_id, balance_usdc, ...)
    │       │       if mult != 1.0:
    │       │           _proposed_size = base * Decimal(mult), quantized to cents
    │       └─ except Exception: logger.warning + fall back to base size
    └─ return TradeSignal(..., proposed_size_usdc=_proposed_size, ...)
```

State lifecycle: same as Lane 4 direction window — in-process memory, Fly restart re-seeds at next scan, returning all users to multiplier=1.0 briefly. Acceptable: bounded soft-reset, no per-scan DB write.

---

## 3. Files created / modified (full repo-root paths)

| Action | File | Lines | Purpose |
|---|---|---|---|
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` | +99 | `_bankroll_multiplier` + `_bankroll_reset_for_tests` + module state; apply path in `_build_trade_signal` between existing fields and `TradeSignal()` constructor; `ROUND_DOWN` added to existing `decimal` import |
| Modified | `projects/polymarket/crusaderbot/config.py` | +60 | 4 knobs (`BANKROLL_DYNAMIC_SIZING_ENABLED`, `BANKROLL_MULTIPLIER_MIN`/`MAX`, `BANKROLL_EMA_ALPHA`) + 2 validators (bounds: finite + > 0; alpha: finite + in (0, 1]) |
| Created | `projects/polymarket/crusaderbot/tests/test_bankroll_dynamic_sizing.py` | +355 | 34 hermetic tests — 10 helper math + 12 config validators + 5 behavioural integration via `_build_trade_signal` |
| Created | `projects/polymarket/crusaderbot/reports/forge/bankroll-dynamic-sizing.md` | this report | WARP•R00T evidence trail |

---

## 4. What is working

**Verified locally:**
- `python -m py_compile` clean on both modified production files.
- `pytest projects/polymarket/crusaderbot/tests/test_bankroll_dynamic_sizing.py` — **34/34 pass** (0.55s).
- Full campaign regression — Lane 1+2+3+4+5 + neighbor — **241/241 pass** (2.48s).

**Coverage:**
- **Helper math** (10): seed + return 1.0 on first call; scale up on growth (1.2); scale down on drawdown (0.8); upper bound caps at MAX; lower bound floors at MIN; non-positive / NaN / Inf balance → 1.0 fail-safe; EMA drift correctness (alpha=0.05 produces baseline 1010 after one +20% tick); per-user isolation (User A growth doesn't move User B); same-balance second call → 1.0.
- **Config validators** (12): default `ENABLED=false`, default bounds `[0.5, 1.5]`, default alpha `0.05`; both bounds reject `{0, -0.1, NaN, Inf, -Inf}` × `{MIN, MAX}` (10 parametrized); alpha rejects `{0, -0.1, 1.5, NaN, Inf}`; alpha=1.0 accepted (inclusive upper boundary).
- **Behavioural integration via `_build_trade_signal`** (5): disabled → unchanged base size + EMA never seeded; enabled first call → seed at balance, base size unchanged; enabled growth → base × multiplier (capped); enabled drawdown → base × multiplier (floored); zero balance → base size (helper safety fallback).

**Bug caught during regression sweep:** `_build_trade_signal` is module-level scope (not inside `_process_candidate`), so the per-call `log = logger.bind(...)` doesn't exist there. Fixed by using module-level `logger.warning(...)` for the fallback path. Verified: all neighbor `test_signal_scan_job` tests pass.

**Behaviour in production (expected):**
- **Default deploy** (`BANKROLL_DYNAMIC_SIZING_ENABLED=false`): zero behaviour change. Sizing is identical to pre-lane.
- **Operator flips enabled**: first scan per user seeds the baseline → multiplier = 1.0 (no change). Subsequent scans react to balance drift. Conservative `alpha=0.05` makes the baseline drift slowly so the multiplier has a meaningful window to react.
- **Combined with risk gate**: 1.5× multiplier on a 6% balanced-profile position cap → engine clamps to 6%. Multiplier raises the FLOOR for active users, never the CEILING.

---

## 5. Known issues

- **In-memory baseline.** Fly restart re-seeds all users at the next scan, briefly returning everyone to multiplier=1.0 even if they were in drawdown / growth before. Same trade-off as Lane 4 — bounded effect, far cheaper than a DB write per scan tick. A future lane can promote to Redis-backed if production data shows the soft-reset is meaningful.
- **EMA alpha is per-deploy global**, not per-user. Aggressive users might want faster tracking, conservative users slower. Acceptable for a single-tenant operator config — multi-tenant per-user knobs would need a DB column (out of scope here).
- **Ships disabled.** Operator must explicitly flip `BANKROLL_DYNAMIC_SIZING_ENABLED=true` after reviewing how the multiplier interacts with their cohort. Documented as a `[ ]` in the test plan.

---

## 6. What is next

**Lane 5 closes the WARP🔹CMD-approved 5-lane Polybot directive defensive guardrails campaign.**

| # | Lane | Tier | Status |
|---|---|---|---|
| 1 | `WARP/R00T/tob-freshness-gate` | MAJOR-NARROW | ✅ MERGED #1475 + DEPLOYED |
| 2 | `WARP/R00T/close-sweep-spread-gate` | STANDARD-NARROW | ✅ MERGED #1476 + DEPLOYED |
| 3 | `WARP/R00T/complete-set-edge-metric` | MINOR-FOUNDATION | ✅ MERGED #1477 + DEPLOYED |
| 4 | `WARP/R00T/safe-close-direction-limit` | STANDARD-NARROW | ✅ MERGED #1478 + DEPLOYED |
| 5 | `WARP/R00T/bankroll-dynamic-sizing` | MAJOR-NARROW | **THIS PR** — pending review |

After merge, the campaign is complete. WARP🔹CMD may want a WARP•ECHO summary report for stakeholders, or a WARP•SENTINEL audit sweep across the 5 merged lanes for end-to-end integrity confirmation.

---

## Validation declaration

```text
Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : _bankroll_multiplier helper + _build_trade_signal apply path + 4 config knobs + 2 field validators
Not in Scope      : Kelly + position caps inside risk gate (still authoritative); DB-persisted baseline; cross-user aggregation
Suggested Next    : WARP🔹CMD review
```
