# WARP•FORGE — late_entry_v3 favored-price ceiling (stop the high-price bleed)

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: late_entry_v3 entry gate — add an env-tunable favored-price
ceiling so the strategy stops taking expensive favored-side entries that lose money.
Not in Scope: Kelly / position / loss / drawdown fences (untouched), exit_watcher /
flip-stop logic, fav_price_min, live-trading guard. Paper-only.
Suggested Next Step: WARP•SENTINEL (MAJOR) or WARP🔹CMD direct review + deploy; then
monitor net PnL + win-rate over the next candle batches to confirm the bleed stops.

## 1. What was built

Owner reported "open trade only 5 seconds / profit anomaly". Investigation (Supabase,
all late_entry_v3 trades) proved:
- **No 5-second bug.** Recent trades hold 26-31s (TP/SL) or ~6min (resolution/expired);
  0 trades under 10s in the last 3h. The `_past_end` bug is still fixed.
- **Real issue: negative strategy edge.** Last 3h = 60 sl_hit (-$265) vs 32 tp_hit
  (+$148) ≈ -$114 net. Root cause found by bucketing every closed trade by favored
  entry price:
  - fav_price 0.55-0.69 -> winning zone (+$278)
  - fav_price < ~0.55 (coin-flip) and > ~0.70 (expensive) -> both bleed (-$338)
  - fav_price 0.70-0.93 alone = -$188 across 94 trades, win-rate 17-31%. These are the
    "-99% SL" losses the owner saw (e.g. ETH YES @ 0.835 -> resolves down -> exit 0.005).
    Entering the favored side at a high price = tiny upside, ~100% downside; at this
    payoff the strategy needs ~49% win-rate to break even and is well below it there.

Fix: lower the favored-price ceiling from 0.93 to **0.70** and make it env-tunable
(`LATE_ENTRY_FAV_PRICE_MAX`), mirroring the existing `fav_price_min` pattern so it can
be retuned via a Fly secret without a redeploy.

## 2. Current system architecture

scan() resolves min_ask_diff / window / fav_price_min / **fav_price_max** (caller
override -> config -> module default), threads them into `_evaluate_market`. The entry
gate already had `fav_price < fav_price_min` and `fav_price >= FAV_PRICE_MAX` checks;
the ceiling is now parameterised. No change to side selection, sizing, RISK, or exits.
The two close_sweep preset call sites pass `fav_price_min` only, so the new ceiling
applies automatically via the config default (0.70).

## 3. Files created / modified

- projects/polymarket/crusaderbot/config.py
  (new `LATE_ENTRY_FAV_PRICE_MAX: float = 0.70`, env-overridable)
- projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py
  (module default `FAV_PRICE_MAX` 0.93 -> 0.70; `fav_price_max` threaded through scan()
   + `_evaluate_market`; gate uses the param; scan_summary log adds fav_price_max)
- projects/polymarket/crusaderbot/tests/test_late_entry_v3.py
  (positive-entry fixtures moved 0.70 -> 0.65 to sit inside the new band; 2 new boundary
   tests: rejects fav 0.72, enters fav 0.68; stale 0.93 comments updated)
- projects/polymarket/crusaderbot/reports/forge/late-entry-fav-price-ceiling.md (this report)

## 4. What is working

- py_compile / ast.parse clean on config.py, late_entry_v3.py, test_late_entry_v3.py.
- Threading verified: caller override -> config -> module fallback all resolve fav_price_max.
- Boundary semantics: `fav_price >= 0.70` rejected; 0.68 enters. Backed by the
  bucket-level PnL evidence above.
- pytest not runnable in this environment (no pytest installed); tests updated by
  reasoning + ast parse only.

## 5. Known issues

- The near-0.50 coin-flip zone (fav 0.46-0.55, -$129) is NOT addressed here — it would
  need raising fav_price_min, which changes the strategy's core thesis and risks
  starving entries. Left for a separate decision.
- The deeper truth remains: directional win-rate is sub-50%; the ceiling removes the
  worst-EV trades but does not by itself make the strategy positive-edge. Monitor.
- Ceiling value 0.70 is data-chosen but tunable via `LATE_ENTRY_FAV_PRICE_MAX` if live
  results suggest 0.66 (drop the breakeven 0.65-0.70 band) or higher.

## 6. What is next

- WARP•SENTINEL (MAJOR) or WARP🔹CMD review; deploy; watch net PnL / win-rate.
- If still net-negative after the ceiling, evaluate raising fav_price_min and/or
  tightening the entry window.
