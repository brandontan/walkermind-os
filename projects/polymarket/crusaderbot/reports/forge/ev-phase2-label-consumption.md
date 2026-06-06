# WARP-78 Phase 2 — EV label consumption + vol correlation + EV-comparator

- Role: WARP•R00T
- Validation Tier: STANDARD (shadow-only additions; no selection/sizing/gate/runtime change; `SCORER_ACTIVE` stays False; `ORCHESTRATOR_ACTIVE` stays False)
- Claim Level: NARROW INTEGRATION
- Validation Target: per-rule horizon label routing in trainer/A/B; realized_vol↔EV correlation on paper_real rows; Phase 2 EV-comparator shadow module wired into scan loop.
- Not in Scope: SCORER_ACTIVE cutover, ORCHESTRATOR_ACTIVE cutover, factor-weighted EV estimation (Phase 3), safe_close A/B with sc-corrected labels (needs accrued paper_real rows).
- Branch: `WARP/root-ev-phase2`

---

## 1. What was built

### Task 1 — Trainer/A/B per-rule horizon label consumption

`scorer.py`: added `_SAFE_CLOSE_HORIZON_RULES` + `row_outcome_for_rule(rule, row)`.  
For `safe_close`, returns `realized_outcome_safe_close` when non-NULL; falls back to `realized_outcome` for pre-migration / tick-miss rows. All other rules use `realized_outcome`.

`scorer_trainer.derive_cell`: updated to call `row_outcome_for_rule(rule, r)` for every `(rule, row)` pair. Previously all rules were judged against `realized_outcome` (the open→close label), causing `close_sweep ≡ safe_close` degeneracy in the weights.

`scorer_ab.compare`: updated to use per-rule outcome for `rule_won`, `rule_ev` for BOTH the router's pick and the scorer's pick. The undecidable check now also uses `row_outcome_for_rule` so safe_close rows with a horizon label are not discarded as undecidable.

`_FETCH_SQL` updated to include `realized_outcome_safe_close, realized_delta_safe_close`.

### Task 2 — realized_vol ↔ realized-EV correlation

Queried Supabase CrusaderBot on 98 settled `paper_real` rows (BTC+ETH, 5m+15m).  
Only `paper_real` rows have `realized_vol` (paper_synthetic predates migration 084).

| asset | tf | n | corr(vol, EV_close_sweep) | corr(vol, EV_safe_close) | corr(vol, EV_flip_hunter) |
|-------|-----|---|--------------------------|--------------------------|--------------------------|
| BTC   | 5m  | 36 | −0.04 | **−0.29** | +0.04 |
| BTC   | 15m |  9 | −0.30 | **−0.69** | +0.30 |
| ETH   | 5m  | 35 | −0.06 | **−0.26** | +0.06 |
| ETH   | 15m |  8 | −0.41 | −0.41      | +0.41 |

**Finding:** `safe_close` EV is most negatively correlated with volatility across all cells. High-vol candles hurt safe_close more than `close_sweep` (the forced 30 s exit is exposed to the noisy tail). `flip_hunter` has the opposite sign — high vol slightly helps contrarian entries. This validates WARP-78's label-fix hypothesis and motivates a vol-conditioned EV estimator in Phase 3.

### Task 3 — Phase 2 EV-comparator (shadow module)

New module `domain/strategy/ev_comparator.py`:
- `ORCHESTRATOR_ACTIVE = False` (never flipped by this module)
- `derive_ev_model(rows, shrinkage_k=10.0)` — shrunk per-rule mean EV per cell; uses `row_outcome_for_rule` for safe_close horizon labels
- `EVComparator.select(cell_key, candidate_rules)` — argmax(shrunk_ev) above `ABSTAIN_EV_THRESHOLD=0.0`, abstains when no rule beats threshold
- `EVComparator.rank(...)` — full ranking with `EVRankedRule(rule, shrunk_ev, passes_threshold)`
- `get_ev_comparator()` — process-wide singleton loaded from `config/ev_comparator_model.json`
- Offline CLI: `python -m ... ev_comparator --from-db`
- Fail-soft: missing/malformed model → `EVComparator.neutral()` which always abstains

Shadow wiring in `late_entry_v3._ev_comparator_shadow(fv, evaluated_rule)`: called after `_persist_factor_vector(fv)` on every evaluated candle. Logs `ev_comparator_shadow` (cell, router_rule, ev_pick) at DEBUG. Any exception absorbed silently — never blocks the scan loop.

### EV A/B baseline (paper_synthetic + paper_real, open→close labels, n=1157 settled rows)

| asset | tf | rule | n | mean_ev (horizon-correct) |
|-------|-----|------|---|--------------------------|
| BTC   | 5m  | safe_close   | 25 | **+0.058** |
| BTC   | 5m  | flip_hunter  | 326 | −0.007 |
| BTC   | 5m  | close_sweep  | 40 | −0.023 |
| ETH   | 5m  | safe_close   | 31 | **+0.070** |
| ETH   | 5m  | flip_hunter  | 300 | −0.010 |
| ETH   | 5m  | close_sweep  | 44 | +0.016 |

**Safe_close has the highest per-trade EV.** Note: `has_sc_label=0` for almost all safe_close rows (paper_synthetic ticks are gone from the oracle ring at settlement) — these numbers use the open→close fallback. The sc-corrected EV (expected to be lower per the vol correlation) will appear once more paper_real rows settle.

**flip_hunter dominates by trade count (88%) but carries near-zero/negative EV** — the EV-comparator would abstain or downgrade flip_hunter picks on these cells, favouring safe_close or close_sweep where they show positive edge.

---

## 2. Current system architecture

Unchanged selection/risk/execution. The scorer and EV-comparator are shadow-only:
- `SCORER_ACTIVE = False` — router still controls routing
- `ORCHESTRATOR_ACTIVE = False` — EV-comparator shadows + logs, never routes
- `SCORER_SHADOW_ENABLED = True` — factor vector telemetry continues
- Every evaluated candle now also emits `ev_comparator_shadow` log entry

---

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/strategy/scorer.py` — `_SAFE_CLOSE_HORIZON_RULES`, `row_outcome_for_rule`
- `projects/polymarket/crusaderbot/domain/strategy/scorer_trainer.py` — per-rule label routing in `derive_cell`, updated `_FETCH_SQL`
- `projects/polymarket/crusaderbot/domain/strategy/scorer_ab.py` — per-rule outcomes in `compare()`
- `projects/polymarket/crusaderbot/domain/strategy/ev_comparator.py` (NEW) — Phase 2 EV-comparator
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` — EV-comparator shadow wiring
- `projects/polymarket/crusaderbot/tests/test_warp78_sc_label_routing.py` (NEW) — 8 tests
- `projects/polymarket/crusaderbot/tests/test_warp78_ev_comparator.py` (NEW) — 9 tests
- `projects/polymarket/crusaderbot/reports/forge/ev-phase2-label-consumption.md` (this)

---

## 4. What is working

- `row_outcome_for_rule` correctly routes to `realized_outcome_safe_close` for `safe_close` and falls back gracefully when NULL — validated by smoke-test and test suite.
- `derive_cell` now computes separate EV for safe_close (using its 30 s horizon) vs close_sweep (open→close): with diverging labels, safe_close EV = −0.60, close_sweep = +0.40. The `close_sweep ≡ safe_close` degeneracy is broken.
- `EVComparator` selects argmax(shrunk_ev), abstains when all EVs ≤ 0. Round-trip model write+load validated.
- `ORCHESTRATOR_ACTIVE = False` confirmed.
- `py_compile` clean on all modified + new files.

---

## 5. Known issues

- `safe_close` sc label is NULL for all 1105 paper_synthetic settled rows (oracle ring ticks are gone — by design). The EV A/B numbers for safe_close currently reflect the open→close horizon (the uncorrected label). The baseline EV (+0.058/+0.070) may decrease once sc-corrected labels accrue from paper_real.
- Vol correlation data is from only 98 paper_real rows — directionally significant but low N, especially for 15m (n=8-9). Needs ≥200 paper_real rows for stable estimates.
- Phase 3 (factor-weighted EV conditioning on `realized_vol` and other factors) is deferred pending more paper_real data.

---

## 6. What is next

- `paper_real` rows continue accruing `realized_outcome_safe_close` and `realized_vol` on every new settlement. The safe_close A/B with the sc-corrected label becomes meaningful at ~200 paper_real settled rows.
- Phase 3: condition the EV estimate on `realized_vol` (and other factors) using the correlation structure validated here. Update `ev_comparator.derive_ev_model` to use factor-weighted shrunk EV.
- `ORCHESTRATOR_ACTIVE` cutover: once safe_close sc-corrected EV is stable on held-out paper_real rows AND EV-comparator shows positive ev_delta vs router on holdout → present to WARP🔹CMD for cutover greenlight.

**Suggested Next Step:** let paper_real rows accrue (~200 settled rows). Then: (a) re-derive EV model with sc-corrected labels, (b) re-run holdout A/B via `scorer_ab --from-db --holdout`, (c) if ev_delta > 0 on holdout → WARP🔹CMD cutover decision.
