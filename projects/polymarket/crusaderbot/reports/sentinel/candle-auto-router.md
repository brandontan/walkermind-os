# WARP•SENTINEL — candle_auto router (Smart Strike)

**Feature:** `WARP/ROOT/candle-auto-router` (PR #1556)
**Auditor:** WARP•R00T acting as WARP•SENTINEL (owner-authorised)
**Environment:** prod posture = PAPER (LIVE guards default OFF)
**Tier:** MAJOR (trading-core scan + exit path)
**Verdict:** ✅ **APPROVED** — Score 93/100, 0 critical

---

## TEST PLAN

Phase 0 pre-test → safety/bypass audit → functional → failure modes → async safety →
risk-rule integrity → regression. Default assumption: UNSAFE until proven. Code is truth.

## FINDINGS (per phase, evidence cited)

### Phase 0 — Pre-test: PASS
- FORGE report present, correct path, 6 sections + metadata: `reports/forge/candle-auto-router.md`.
- `PROJECT_STATE.md` / `WORKTODO.md` / `CHANGELOG.md` updated. No `phase*/` folders.
- CI green: both `Lint + Test` jobs + `notify` = success on HEAD `120f54e`.

### Safety / bypass audit: PASS (the decisive check for a trading-core change)
- **Zero changes** to `domain/risk/`, `domain/activation/`, `execution/paper.py`,
  `execution/live.py`, `config.py` (`git diff --name-only`). Risk constants, Kelly,
  caps, kill switch, activation guards, paper-default — all untouched.
- Router candidates flow through `_process_candidate` → the full 15-step risk gate,
  identical to single-preset candidates (`signal_scan_job.py:2824, 3285`). No gate
  bypass, no new execution path.

### Phase 1 — Functional: PASS
- Router merge/dedup/precedence (close_sweep > safe_close > flip_hunter), per-rule
  TP/SL stamp from canonical `PRESETS`, per-rule force-exit threading, single-preset
  no-stamp — all pinned by 8 hermetic tests (`test_candle_auto_router.py`).
- `_CANDLE_PRESETS` (3 single rules) preserved for `_resolve_preset_params` dispatch;
  `candle_auto` correctly excluded from it (verified — would otherwise resolve to
  flip_hunter params). `_ALL_CANDLE_PRESETS` gates window-fetch/fast-loop.

### Phase 3 — Failure modes: PASS
- Sub-rule isolation: both `_resolve_preset_params` AND `scan()` now inside the
  per-rule `try` (Gemini review fix) → one rule's failure skips that rule, never the
  whole scan (`test_router_subrule_failure_isolated`).
- Config failure → `_resolve_preset_params` static fallback. `_candle_auto_rule_tpsl`
  per-field None guard + bare-except → `(None,None)` → user tp/sl applies.
- Empty book / no candidate handled upstream in `late_entry_v3.scan()` (unchanged).

### Phase 4 — Async safety: PASS
- Router is sequential per user; `scan()` returns fresh `SignalCandidate` objects per
  market per tick (`late_entry_v3._evaluate_market`), so the `.metadata` mutation on
  the frozen dataclass's dict has no cross-user/aliasing hazard. `seen` dedup is
  per-call local state.

### Phase 5 — Risk-rule integrity: PASS
- Per-rule TP/SL persists as `applied_tp_pct`/`applied_sl_pct`; still bounded by the
  risk gate's position caps (gate unchanged). Override key set ONLY by the router →
  weather/copy/signal candidates fall through to user tp/sl unchanged
  (`test_single_preset_path_no_router_stamp`).

### Phase — Regression: PASS
- Exit fallback triggers only when the preset→force-exit lookup is `None`
  (`exit_watcher.py:202`); the 3 single presets always return a concrete value →
  behaviour identical. Full suite 2286 passed; `test_exit_watcher` +
  `test_close_sweep_fast_exit` + weather metadata tests green.

## CRITICAL ISSUES
None found.

## STABILITY SCORE
- Architecture 20% → 19 (clean additive router; reuses existing metadata thread; no bypass)
- Functional 20% → 19 (merge/dedup/precedence/per-rule exits well covered)
- Failure modes 20% → 18 (sub-rule isolation incl. param resolution; None guards)
- Risk rules 20% → 20 (zero gate/guard/cap change; fully gated)
- Infra+TG 10% → 9 (bot + WebTrader surfaces wired; no infra change)
- Latency 10% → 8 (router does 3× `scan()` per candle_auto tick — see advisory)
- **TOTAL: 93/100**

## GO-LIVE STATUS
**APPROVED for the PAPER posture** (score ≥ 85, 0 critical). LIVE remains owner-gated OFF.

## FIX RECOMMENDATIONS (priority ordered — none blocking)
1. **Pre-LIVE blocker (tracked):** add `strategy_metadata` to `execution/live.py`
   position INSERT so the per-rule force-exit fallback works in LIVE (also fixes
   weather's identical latent gap). Per-rule TP/SL already works in LIVE. Must close
   before the owner flips LIVE. Already in PROJECT_STATE + FORGE Known Issues.
2. **Advisory (load):** `candle_auto` runs `scan()` 3× per tick (one per rule) → ~3×
   the `get_book` fetches per candle market vs a single preset. Bounded by the small
   BTC/ETH/SOL candle universe + 45s window cache, fine at current scale. Future
   optimisation: fetch the window once and evaluate all 3 rules in a single market
   pass.
3. **Advisory (minor):** `_gate_safe_close_direction` keys on `active_preset ==
   "safe_close"` so it doesn't apply to candle_auto's safe-rule trades; the WARP-51
   H3 per-asset concentration sub-limit would supersede it.
4. **Reminder:** combined-router EV is UNMEASURED (no backtest — WARP-51 F-1). Paper
   results are the validation signal before any LIVE capital scaling.

## TELEGRAM PREVIEW
Picker now lists 🔥 Smart Strike (recommended) above the 3 single candle presets +
Weather. Activation writes `active_preset='candle_auto'`, locks category Crypto,
surfaces the 5m/15m + asset toggles (crypto-short). No new alert events.
