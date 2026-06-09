# WARP•FORGE Report — disable-complete-set-edge-gate

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `config.MIN_COMPLETE_SET_EDGE` default — disable gate via operator escape hatch
**Not in Scope:** gate logic removal, strategy changes, risk gate modifications

---

## 1. What Was Built

One-line config change: `MIN_COMPLETE_SET_EDGE` default lowered from `0.005` to `0.0`, which activates the documented operator escape hatch (`_min_edge > 0` short-circuit in `_process_candidate` step 3b-0a).

Root cause investigation confirmed via Supabase `scan_runs` telemetry: every `late_entry_v3` candidate since the `complete-set-edge-gate` deployment (2026-05-30 15:16 UTC, commit `16c0fae`) has been rejected with `skipped_negative_arb`. The scan_runs from 17:31–19:36 UTC show the pattern unambiguously — `skip_breakdown = {"skipped_negative_arb": N}` where N equals `candidates_emitted` on every scan that caught the entry window.

**Why the gate blocks everything:** The gate requires `complete_set_edge = 1.0 - (yes_ask + no_ask) >= 0.005`. On Polymarket, market makers price YES + NO such that `yes_ask + no_ask > 1.00` (the spread/fee keeps the combined ask above $1.00). This makes `complete_set_edge` consistently negative on liquid markets. The 0.005 threshold is calibrated for a textbook complete-set arbitrage condition that does not exist on active Polymarket CLOB books. The two trades that did pass (18:40 and 19:36 UTC) caught thin-book moments that are anomalous, not the design state.

**Why the gate is wrong for a directional strategy:** `complete_set_edge` measures whether buying BOTH legs simultaneously would yield a profit — a pure arb metric. Late_entry_v3 enters ONE leg directionally. The arb efficiency of the market is irrelevant to the directional payout. The existing gates (ask_diff ≥ 3%, fav_price [0.50–0.95], leg spread, TOB freshness, 13-step risk gate) already protect against bad entries.

Setting `MIN_COMPLETE_SET_EDGE=0` activates the escape hatch the code explicitly documents for this scenario.

---

## 2. Current System Architecture

No architecture change. The gate code remains intact in `_process_candidate` step 3b-0a — the `if _min_edge > 0` branch simply short-circuits when `_min_edge = 0.0`. The gate can be re-enabled at any time via env var `MIN_COMPLETE_SET_EDGE=<positive value>` without a code change.

---

## 3. Files Created / Modified

| File | Change |
|---|---|
| `projects/polymarket/crusaderbot/config.py` | `MIN_COMPLETE_SET_EDGE: float = 0.005` → `0.0` (line 551) |
| `projects/polymarket/crusaderbot/reports/forge/disable-complete-set-edge-gate.md` | This report |

---

## 4. What Is Working

- `py_compile` clean on `config.py`
- `ruff check` clean on `config.py`
- Gate short-circuits when `_min_edge = 0.0` (existing code path, no new logic)
- All other gates remain active: ask_diff, fav_price, leg_spread, TOB freshness, complete_set_edge metric still STAMPED in metadata (observability preserved), 13-step risk gate

---

## 5. Known Issues

None introduced. The underlying metric (`complete_set_edge` stamp in candidate metadata) is preserved — operator dashboards and future lanes can still read it. Only the hard-reject threshold is disabled.

If Fly.io env var `MIN_COMPLETE_SET_EDGE` is set to any positive value in the app secrets, it will override this default. Verify secrets do not have a residual `MIN_COMPLETE_SET_EDGE=0.005` override.

---

## 6. What Is Next

1. **Merge + deploy** → trading should resume within the first candle cycle after deployment
2. **Monitor scan_runs** for `skipped_negative_arb` count to confirm it drops to zero
3. **Long-term:** If a complete-set edge filter is desired for directional strategies, it should be calibrated empirically from `metadata["complete_set_edge"]` distribution across actual trades (expected to be in -0.10 to -0.02 range on normal Polymarket books). A meaningful threshold would be something like `MIN_COMPLETE_SET_EDGE = -0.15` (block only egregiously overpriced markets).

**Suggested Next Step:** WARP🔹CMD merge + Fly.io deploy.

---

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
