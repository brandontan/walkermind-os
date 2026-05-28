# WARP•R00T REPORT — late-entry-fill-drift-guard

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: fill-time price-band re-check for late_entry_v3 candidates (close_sweep / safe_close / flip_hunter presets)
Not in Scope: confluence_scalper, lib/ strategies, signal_following feed signals (unchanged), activation guards, risk gate (13 steps unchanged after gate 3c)
Suggested Next Step: WARP🔹CMD review. Tier: STANDARD. Source: projects/polymarket/crusaderbot/reports/forge/late-entry-fill-drift-guard.md.

---

## 1. What was built

A fill-time price-band re-check ("gate 3c") in `_process_candidate` that rejects late_entry_v3 candidates whose live fill price has drifted outside the band that was satisfied at scan time.

**Root cause closed.** Late Entry V3 (close_sweep / safe_close / flip_hunter) was emitting candidates against scan-time orderbook prices, then `_process_candidate` fetched `get_live_market_price` and built the TradeSignal with no re-validation. Candle markets oscillate 0.10+ between scan and fill in the final 30s, so the strategy preset's price band became aspirational — actual fills landed at any live price.

**Prod evidence (last 24h, before fix):**

| User                | Preset      | Intended band  | Trades | In-band  | Coin-flip [0.45–0.55] | Cheap (<0.40) | Expensive (>0.70) |
|---------------------|------------:|---------------:|-------:|---------:|----------------------:|--------------:|------------------:|
| 7e6fbd20… (current safe_close, mostly close_sweep era) | mixed | [0.55–0.70) / [0.60–0.70) | 180 | 10 (5.5%) | 84 (47%) | 58 (32%) | 12 (7%) |
| c8db805c… (close_sweep)                                | close_sweep | [0.55–0.70) | 64  | 11 (17%) | 16 (25%) | 20 (31%) | 12 (19%) |

After the fix the strategy still emits candidates, but fills land within the band — or are short-circuited as `skipped_fill_drifted` and the engine never runs.

**Mechanism**:

- `domain/strategy/strategies/late_entry_v3.py:_evaluate_market` now emits `fav_price_min` + `fav_price_max` in `candidate.metadata` alongside the existing `entry_price` / `underdog_mode` fields. Standard mode + underdog mode both write the same two keys, so the gate is mode-agnostic.
- `services/signal_scan/signal_scan_job.py:_process_candidate` gains a new "3c" check between live-price fetch (3b) and `_build_trade_signal` (3): if `cand.metadata` carries both `fav_price_min` and `fav_price_max` and `_live_fill_price` is set, require `fav_price_min ≤ _live_fill_price < fav_price_max`. On miss → `scan_outcome: skipped_fill_drifted` + `telemetry.skip_breakdown[skipped_fill_drifted]`. Gate is metadata-driven and opt-in: candidates without the band keys (signal_following / lib strategies / confluence_scalper) pass through unaffected.

The gate is the same half-open `[min, max)` semantics the strategy already uses, so a candidate that passed scan-time gates *cannot* be rejected at fill time unless the live price moved.

---

## 2. Current system architecture

```
late_entry_v3.scan()
  └─ _evaluate_market()
       ├─ outer gates (window, lean, spread)
       ├─ price gate: entry_price ∈ [fav_price_min, fav_price_max)
       └─ emit SignalCandidate
             metadata: {entry_price, fav_price_min, fav_price_max, underdog_mode, …}

run_close_sweep_fast() / run_once Phase B2
  └─ _process_candidate(row, cand)
       ├─ gate 0  crash-recovery resume (stale 'queued')
       ├─ gate 1  publication dedup
       ├─ gate 1b open-position market dedup
       ├─ gate 1c signal freshness (publication-only)
       ├─ gate 2  _load_market
       ├─ gate 2b target-price drift (publication-only — DB cached)
       ├─ gate 2c user liquidity floor
       ├─ gate 3b live price fetch via get_live_market_price()
       ├─ gate 3c FILL-TIME BAND RE-CHECK    ← NEW
       │           if metadata.{fav_price_min, fav_price_max} present
       │           require _live_fill_price ∈ [min, max)
       │           else skipped_fill_drifted + return
       ├─ gate 3  _build_trade_signal (uses _live_fill_price)
       ├─ gate 4  TradeEngine.execute (13-step risk gate, unchanged)
       └─ gate 5  execution_queue insert + mark_executed
```

The risk gate's 13 steps are untouched. Activation guards (`ENABLE_LIVE_TRADING` / `EXECUTION_PATH_VALIDATED` / `CAPITAL_MODE_CONFIRMED` / `RISK_CONTROLS_VALIDATED` / `SECURITY_HARDENING_VALIDATED`) are untouched. Kelly clamp, position cap, daily loss limit are untouched.

---

## 3. Files created / modified

| Action   | Path |
|----------|------|
| Modified | `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` (metadata adds `fav_price_min` + `fav_price_max`) |
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (`_process_candidate` gate 3c) |
| Modified | `projects/polymarket/crusaderbot/tests/test_late_entry_v3.py` (+2 metadata regression tests) |
| Modified | `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` (+4 gate-3c tests) |
| Created  | `projects/polymarket/crusaderbot/reports/forge/late-entry-fill-drift-guard.md` |

---

## 4. What is working

- **Full suite green**: `pytest projects/polymarket/crusaderbot/tests -q` → 1866 passed, 5 skipped, 0 failures.
- **Targeted suites**:
  - `test_late_entry_v3.py` → all pass incl. 2 new metadata regression tests.
  - `test_signal_scan_job.py` → all pass incl. 4 new gate-3c tests (below-band / at-max-band / inside-band / no-op-without-metadata).
- `ruff check` clean on all 4 modified files.
- `py_compile` clean on both production files.
- Backward compat preserved: signal_following / lib / confluence_scalper candidates carry no band keys → gate 3c no-ops, behaviour unchanged.
- Underdog mode (flip_hunter) handled correctly: candidate uses the cheap-side ask, metadata band is the underdog band, gate re-check uses the same band — single code path.

---

## 5. Known issues

- **Gate 3c logs `skipped_fill_drifted` to structured logs only.** It does *not* roll up into `scan_runs.skip_breakdown` for the fast-scan loop because `run_close_sweep_fast` only persists `scan_runs` when at least one paper order fires (line 1561 — `if tel.paper_orders_created > 0`). Per-tick observability of drift skips lives in stdout / Fly logs. A separate lane could persist a lightweight `scan_runs` row whenever skip_breakdown is non-empty.
- **Existing gate 2b (target-price drift) remains publication-only.** Out of scope for this lane — it compares against DB-cached prices, not live fill price, and applies to feed signals. Two distinct drift surfaces.
- **No env-tunable for the band tolerance.** The gate uses the strategy's existing `fav_price_min/max` exactly. Tightening or loosening the tolerance requires editing the preset config (e.g. `PRESET_SAFE_CLOSE_FAV_PRICE_MIN`). Acceptable — strategy and gate stay in sync.

---

## 6. What is next

- WARP🔹CMD review (Tier STANDARD). Optional SENTINEL gate if the touch on the execution path warrants deeper validation.
- Fly redeploy to activate the gate in prod.
- Post-deploy verification: query `positions WHERE strategy_type='late_entry_v3' AND opened_at >= deploy_ts` and confirm `entry_price` distribution sits inside the active preset's band for ≥95% of rows.
- Optional follow-up: dial in tighter bands (e.g. `safe_close` `[0.60, 0.68)`) now that drift can no longer push fills past the ceiling.

---

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
