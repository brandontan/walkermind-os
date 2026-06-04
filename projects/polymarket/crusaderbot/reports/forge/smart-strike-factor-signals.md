# SMART STRIKE — factor signals + labeled dataset (WARP-72 Phase 1)

**Role:** WARP•R00T (major build, shadow-only)
**Linear:** WARP-72 (Phase 1 of 4 — factor signals + labeled dataset ONLY)
**Branch:** WARP/ROOT/smart-strike-factor-signals
**Baseline:** WARP-71 audit (`reports/forge/smart-strike-audit.md`) — of the 7 spec factors only TTL was load-bearing; momentum unmeasured (instantaneous `ask_diff` only), volatility (sigma) computed-but-unused (oracle-advisory dead-end), oracle producer-only. No scorer exists.

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** the new factor signals (momentum, exposed volatility) + the labeled factor-vector emission path inside `late_entry_v3` scan + `signal_scan_job` router-selection stamp. Shadow/telemetry only.
**Not in Scope:** the Phase-2 scorer; any selection/router change; any risk-gate, pre-gate, `would_pass`, execution, sizing or Kelly change; settled-outcome (post-close) re-labeling; persistence of the dataset to a DB table.
**Suggested Next Step:** collect the `factor_vector` dataset in paper across BTC/ETH/SOL × 5m/15m for a meaningful sample, then start WARP-72 Phase 2 (data-derived weights). Phase 2 is gated on the labeled sample — hand-tuned weights are rejected.

---

## 1. What was built

A real, tested **7-factor scorable surface** + a **labeled-dataset emitter**, built BEFORE any scorer (you cannot score factors you do not measure — WARP-71). Everything is shadow/telemetry only: it never selects, sizes, gates, or blocks a trade.

1. **Momentum (NEW)** — `domain/signal/momentum.py`. A rolling short-window **repricing velocity** per candidate (signed price-units/second of the YES mid), replacing the instantaneous `ask_diff` lean. Pure `compute_momentum()` + an in-process `MomentumTracker` (intra-tick de-dup so the candle_auto 3-rule scan records one sample, window pruning, idle-key eviction). Returns `None` until ≥2 in-window samples land — an honest "no history yet", never a fabricated zero.
2. **Volatility (EXPOSED)** — per-asset `sigma` (`sigma_for_asset`) is now stamped as `factor_volatility_sigma`. Previously it fed only the dead-end oracle advisory; it is now a first-class scorable input, resolved even when the oracle edge gate is OFF (falls back to `Settings.oracle_sigma_per_sqrt_sec` / module default).
3. **Liquidity / spread / orderbook-depth / TTL (CONFIRMED + EXPOSED)** — already computed in `_evaluate_market` (`clob_liquidity`, `spread = yes_ask+no_ask`, book depth, `seconds_to_close`); now surfaced on the unified `factor_*` namespace. Depth shares the CLOB book-depth source as liquidity (documented, per the audit).
4. **Oracle (KEPT ADVISORY)** — the now-fixed oracle edge is reused as-is for the `oracle_edge` factor + the realized open→close label. Its computation moved a few lines earlier in `_evaluate_market` (before the directional gates) so it — and the full vector — emit for EVERY evaluated candle, not only survivors. Still advisory, still non-blocking, still fail-soft.
5. **Labeled dataset** — `domain/signal/factors.py` `FactorVector`: all 7 factors + candidate shape + the router-selected rule + the realized open→close outcome. Emitted as a structured `factor_vector` log AND stamped as `factor_*` candidate/position metadata, for **every evaluated candle (traded or not)**, decoupled from execution — the same clean source as the oracle advisory. Default-ON flag `FACTOR_VECTOR_SHADOW_ENABLED`.

---

## 2. Current system architecture

```
DATA -> [STRATEGY: late_entry_v3._evaluate_market] -> INTELLIGENCE -> RISK -> EXECUTION
                         |
   (book read OK; factors computed: spread, ask_diff, liquidity, fav_price)
                         |
         +---------------+-----------------------------+
         |  WARP-72 SHADOW observation (fail-soft)     |   <-- NEW, before the
         |  _observe_oracle_edge(...)  (advisory)      |       directional gates
         |  _observe_factor_vector(...):               |       so it fires for
         |    1 momentum  (MomentumTracker rolling)    |       ALL evaluated
         |    2 volatility sigma (now exposed)         |       candles
         |    3 liquidity 4 spread 5 depth 6 TTL       |
         |    7 oracle edge + realized open->close lbl |
         |  -> emit("factor_vector") + factor_* meta   |
         +---------------+-----------------------------+
                         |
   (directional gates UNCHANGED: ask_diff / spread / fav_price) -> SignalCandidate
                         |
   signal_scan_job._scan_late_entry_for_preset:
     candle_auto: precedence dedup (close_sweep>safe_close>flip_hunter) UNCHANGED
       -> mark_router_selection(winner.metadata, rule)  (advisory stamp only)
     single preset: mark_router_selection(cand.metadata, active_preset)
                         |
   pre-gates (UNCHANGED) -> TradeEngine.execute -> 13-step risk gate (UNCHANGED)
```

The factor vector and oracle advisory are the only additions; the capital path (selection → pre-gates → risk gate → execution) is byte-for-byte unchanged in behavior.

---

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/signal/momentum.py` — rolling momentum signal + tracker.
- `projects/polymarket/crusaderbot/domain/signal/factors.py` — `FactorVector`, realized-outcome label, router-selection stamp, fail-soft emit.
- `projects/polymarket/crusaderbot/tests/test_warp72_factor_signals.py` — 16 tests.

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` — `_timeframe_from_slug`, `_observe_factor_vector`, `_factor_vector_enabled`; `_evaluate_market` computes the oracle advisory + factor vector before the directional gates (emit for all evaluated candles) and stamps `factor_*`; `evaluated_rule` threaded through `scan()`.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — `evaluated_rule=preset` into `_scan_one_late_entry`; `mark_router_selection` on the deduped candle_auto winner + single-preset candidates (advisory; selection logic untouched).
- `projects/polymarket/crusaderbot/config.py` — `FACTOR_VECTOR_SHADOW_ENABLED: bool = True`.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `state/WORKTODO.md`, `state/CHANGELOG.md` — state sync.

---

## 4. What is working

- 16/16 new tests pass. Relevant existing suites green (no regression): `test_late_entry_v3`, `test_oracle_edge_wiring`, `test_candle_auto_router`, `test_signal_scan_job`, `test_close_sweep_spread_gate`, `test_complete_set_edge_metric`, `test_tob_freshness_gate` — 197 pass. `ruff` clean on all changed files.
- Momentum: pure velocity math (sign, window exclusion, ≥2-point requirement), tracker sampling, intra-tick de-dup, prune, idle-key eviction, and end-to-end populate-across-scans all verified.
- Emit-for-all-evaluated-candles verified: a candidate **rejected** by the `ask_diff` gate still produces its dataset row (decoupled from execution).
- Volatility sigma exposed and present even with the oracle OFF; oracle realized open→close label rides through when the advisory edge is wired.
- Flag verified: `FACTOR_VECTOR_SHADOW_ENABLED=false` silences both the emission and the `factor_*` metadata with zero capital-path effect.

### Sample of emitted factor vectors (real `factor_vector` events, hermetic run)

`router_selected_rule` is `null` below because these were captured via a direct `strat.scan()` call; in production `signal_scan_job` stamps it on the deduped winner. `momentum` is `null` on a first observation (one sample) by design.

```
A) close_sweep — TRADED favorite (oracle off)
   evaluated_rule=close_sweep  fav_side=YES entry_price=0.66 ask_diff=0.45
   momentum=null (1 sample)  volatility_sigma=0.0001  liquidity_usdc=75.8
   spread=0.87  orderbook_depth_usdc=75.8  ttl_sec=19.99  complete_set_edge=0.13
   oracle_edge=null  realized_outcome=null  candle_open=1779249900 close=1779250200

B) safe_close — REJECTED coin-flip (ask_diff 0.01 < 0.05; NOT traded, STILL emitted)
   evaluated_rule=safe_close  ask_diff=0.01  volatility_sigma=0.0001
   liquidity_usdc=66.2  spread=1.03  ttl_sec=19.99  oracle_edge=null  realized_outcome=null

C) flip_hunter — oracle advisory wired (realized open->now label)
   evaluated_rule=flip_hunter  oracle_edge=0.37  oracle_would_pass=true
   oracle_delta=0.004808  realized_outcome=UP  realized_delta=0.004808
   outcome_source=oracle_open_to_now  volatility_sigma=0.0001  ttl_sec=19.99
```

---

## 5. Known issues

- **Realized label is open→now, not settled open→close.** It is resolved from the oracle buffer at observation time (`oracle_price_to_beat` = candle open, `oracle_price` = now). In the final-seconds windows this is the de-facto settlement on the same Chainlink source the market resolves against; in wider windows (flip_hunter 60–180s) it is an approximation. `outcome_observed_rem_sec` + `candle_close_epoch` are stamped so a Phase-2 settled-labeler can upgrade it via `oracle.price_at(close_epoch)`. `outcome_source` is explicit (`oracle_open_to_now`).
- **Label requires the oracle.** With the oracle off, `realized_outcome` is `None` (factors still emit). Phase 2's dataset depends on `ORACLE_ENABLED` + `ORACLE_EDGE_GATE_ENABLED` being on in paper.
- **Momentum resolution is scan-cadence bound.** Samples accumulate only while a market is in its entry window; close_sweep's 35s window at the ~15s fast loop yields ~2 samples (a 2-point velocity), flip_hunter/safe_close yield more.
- **Dataset sink is structured logs + metadata**, matching the oracle advisory's "clean source." No DB table was added (out of scope); Phase 2 ingests from logs / position `strategy_metadata`.

---

## 6. What is next

- WARP🔹CMD review of this Phase-1 lane (STANDARD / NARROW INTEGRATION).
- Paper observation to accumulate the labeled `factor_vector` dataset.
- WARP-72 Phase 2 (separate lane): derive scorer weights from this dataset (which strategy wins under which factor conditions); shadow only; hand-tuned weights rejected. Then Phase 3 (shadow A/B vs the precedence router) and Phase 4 (data-gated cutover, router kept as flagged fallback). No selection change until the scorer demonstrably beats the router on realized outcomes.

---

**Pipeline:** DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION — unchanged; RISK still runs before EXECUTION. **Guards:** `ENABLE_LIVE_TRADING` and the 13-step risk gate untouched. **Kelly:** untouched (a=0.25). **Concurrency:** asyncio only (module tracker touched from one event loop).
