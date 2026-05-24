# WARP•FORGE Report — Late Entry V3 ask-reading fix + threshold calibration

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: why late_entry_v3 emitted 0 candidates in prod, and the two fixes that make it trade (best-ask selection + ask-diff threshold).
- Not in Scope: profitability of the edge (separate observation lane once it trades); other gates (FAV_PRICE_MAX 0.93 / MAX_SPREAD 1.05 unchanged).
- Suggested Next Step: WARP•SENTINEL validation, deploy, then watch first fills + tune further if needed.

---

## 1. What was built

Owner: "make sure it trades." Diagnosed against prod: `scan_runs` showed
`late_entry_v3:filter_or_no_match` every tick (0 candidates, NOT a risk-gate rejection),
i.e. the gates inside `scan()` filtered everything. Live CLOB probe of an in-window 5m
candle found TWO causes:

1. **`_best_ask` read the wrong price.** Polymarket CLOB `/book` returns `asks` sorted
   DESCENDING (worst first) — `asks[0]` was the HIGHEST ask (~0.99). So both sides priced
   ~1.0 → `ask_diff ≈ 0` and `fav_price ≥ FAV_PRICE_MAX` → always filtered. Fix: scan all
   ask levels and take the **minimum positive price** (true best ask), order-independent.
2. **`MIN_ASK_DIFF=0.30` far too strict.** BTC/ETH 5m/15m candles sit ~0.50/0.50 (real
   best asks YES 0.50 / NO 0.51, diff 0.01); a 0.30 lean essentially never occurs. Lowered
   to **0.05** (~5c lean ≈ the reference "min edge 2%"), still skipping pure coin-flips.

## 2. Current system architecture

No pipeline change. `_best_ask(book)` now returns `min(price)` over `asks` (skips
non-positive/malformed). `MIN_ASK_DIFF` 0.30→0.05. All other gates and the risk-gate
sizing path are unchanged. Entry still: final ≤35s, favored = higher best-ask side,
require `ask_diff ≥ 0.05`, `0 < (yes_ask+no_ask) ≤ 1.05`, `fav_price < 0.93`.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py (_best_ask min-price; MIN_ASK_DIFF 0.30->0.05)
- projects/polymarket/crusaderbot/tests/test_late_entry_v3.py (threshold test → 0.02 skip; new small-lean entry test; new _best_ask ordering test)

State:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- Full suite: 1750 passed, 1 skipped. py_compile clean.
- Verified against live CLOB: best asks YES 0.50 / NO 0.51 (diff 0.01) — explains the
  prior 0 fills; the fix reads these correctly and the 0.05 gate is reachable on a real
  late lean. `_best_ask` now returns the lowest ask given a descending book.

## 5. Known issues

- 0.05 is a first calibration; whether late-lean entries are *profitable* is unknown —
  validate over N fills (separate lane). If still too few fills, next lever is MAX_SPREAD
  (1.05) or the window (35s), or lowering MIN_ASK_DIFF further.
- The 15s fast loop still writes no `scan_runs`, so its candidate/rejection counts aren't
  in telemetry — fills are observable via `positions` (strategy_type='late_entry_v3').

## 6. What is next

- WARP•SENTINEL validation, then Fly redeploy.
- Watch `positions` for the first `late_entry_v3` fill (≤35s to close, favored side);
  confirm fill rate is sane, then assess win-rate/PnL before any further loosening.
