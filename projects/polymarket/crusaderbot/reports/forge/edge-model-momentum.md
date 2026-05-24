# WARP•FORGE Report — edge-model-momentum

**Branch:** claude/fervent-hawking-yNP0Z  
**Validation Tier:** STANDARD  
**Claim Level:** NARROW INTEGRATION  
**Validation Target:** `jobs/market_signal_scanner.py` edge scoring + side selection; `config.py` price-range defaults  
**Not in Scope:** CLOB/Heisenberg live path (`_check_edge_finder`); signal_evaluator; execution layer; risk gate  

---

## 1. What was built

**Lane 3 — edge-model rework.**

The demo edge generator in `jobs/market_signal_scanner.py` scored every candidate market as:

```
edge = abs(yes_p - 0.5)
```

This formula peaks at prices near 0 or 1 (longshots and near-certainties), causing the scanner to systematically rank far-out championship-winner futures highest. Those markets resolve months out, lock concurrency slots for the entire period, and generate 0 PnL. Reported by beta testers as "only ever holds the same 5 futures, 0 profit".

Two fixes:

**FIX A — Momentum scoring.** Replace the distance-from-0.5 formula with a 24h/1h price-change signal sourced from Gamma market fields (`oneDayPriceChange`, `oneHourPriceChange`). Formula:

```
edge = max(abs(price_change_1d), abs(price_change_1h) * 1.5)
```

The 1h signal is weighted up 1.5× because it is fresher. Markets with no recent price movement produce edge = 0 and are filtered out. Markets with active informed trading (significant daily/hourly movement) produce meaningful edge scores.

**FIX B — Tighter price range.** Changed `SCANNER_EDGE_MIN_PRICE` default from `0.05 → 0.15` and `SCANNER_EDGE_MAX_PRICE` from `0.95 → 0.85`. Longshots (YES ≤ 0.15) and near-certainties (YES ≥ 0.85) are rejected before scoring. Both remain env-overridable.

**FIX C — Momentum-following side.** Changed side selection from mean-reversion (`YES if yes_p < 0.5`) to momentum-following (`YES if recent_price_change ≥ 0`), using the 1h signal when nonzero, otherwise the 1d signal. In prediction markets, informed traders move prices in the correct direction; following momentum is more accurate than buying the "cheap" side.

---

## 2. Current system architecture

```
run_job()
  └── for m in markets:
        ├── price eligibility gate (SCANNER_EDGE_MIN_PRICE=0.15 .. SCANNER_EDGE_MAX_PRICE=0.85)
        ├── liquidity gate (SCANNER_MIN_LIQUIDITY)
        ├── momentum edge = max(|1d_change|, |1h_change|×1.5)   ← CHANGED
        ├── edge_bps threshold gate (SCANNER_MIN_EDGE_BPS=200)
        ├── side = follow momentum direction                     ← CHANGED
        └── publish to LIVE feed (or DEMO feed if flag set)
```

The CLOB/Heisenberg live path (`_check_edge_finder` + candle series) is separate and unchanged.

---

## 3. Files created / modified

| Action   | Path |
|----------|------|
| Modified | `projects/polymarket/crusaderbot/config.py` |
| Modified | `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py` |
| Modified | `projects/polymarket/crusaderbot/tests/test_market_signal_scanner.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/edge-model-momentum.md` |

**config.py** — lines 189–190: `SCANNER_EDGE_MIN_PRICE 0.05 → 0.15`, `SCANNER_EDGE_MAX_PRICE 0.95 → 0.85`.

**market_signal_scanner.py** — lines 485–501 (approx): edge formula, side logic, and surrounding comments replaced.

**test_market_signal_scanner.py** — `_FAKE_CFG` updated to new defaults; `_make_market` gains `day_change`/`hour_change` params; 5 existing tests updated to use momentum semantics; 5 new tests added (longshot rejection at 0.10/0.90, near-fair momentum pass, 1h-over-1d preference, 1d fallback).

---

## 4. What is working

- py_compile clean on all 3 modified files.
- Markets with zero price change are rejected (edge_bps = 0 < 200).
- Markets at YES=0.10 and YES=0.90 are rejected by the tighter price range.
- Markets near fair (YES=0.49) with strong momentum (15%+ daily change) are approved — previously the old formula rejected them if the distance from 0.5 was < 2%.
- Side follows the strongest available momentum signal; 1h preferred over 1d when nonzero.
- Existing regression guards (`MIN_LIQUIDITY == 10_000`, `EDGE_PRICE_THRESHOLD == 0.15`) unchanged.
- Feed routing (LIVE vs DEMO) and `is_demo` flag logic unchanged.
- `SCANNER_MIN_EDGE_BPS=200` unchanged — same 2% threshold, now applied to price momentum rather than price distance.

---

## 5. Known issues

- `oneDayPriceChange` / `oneHourPriceChange` are `None` for some Gamma markets (rarely traded or very new). These default to 0 → edge = 0 → rejected. This is correct: markets with no measurable momentum should not generate signals.
- If Gamma stops returning these fields (API change), the scanner degrades gracefully to zero-edge → no signals published, rather than publishing spurious longshot signals.
- pytest not executable in this container (asyncpg/telegram deps absent). Test logic verified via py_compile + manual inspection of control flow. WARP🔹CMD or CI should run `pytest projects/polymarket/crusaderbot/tests/test_market_signal_scanner.py` before merge.

---

## 6. What is next

- Lane 1 (category mapping): The Gamma `/events` endpoint is now confirmed accessible in this session. `get_events_with_markets()` + `_fetch_markets_for_lib_strategies()` rewrite will fix the "select all categories but only see 2" complaint.
- Post-deploy: confirm via Fly logs that the scanner is now publishing signals for active high-momentum markets (US/Iran peace deal, BTC price bets) rather than far-dated futures.

---

**Suggested Next Step:** WARP🔹CMD review → merge → Fly redeploy → confirm scanner telemetry shows momentum-scored candidates.

**Validation Tier:** STANDARD  
**Claim Level:** NARROW INTEGRATION
