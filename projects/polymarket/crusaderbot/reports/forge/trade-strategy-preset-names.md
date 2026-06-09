# WARP•FORGE Report — trade-strategy-preset-names

Branch: WARP/trade-strategy-preset-names
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Trade cards show the preset name the user selected (e.g. "Close Sweep") instead of the underlying strategy class
Not in Scope: per-position preset persistence (no schema change), Telegram notification labels

---

## 1. What was built

Follow-up to webtrader-trade-strategy-label (#1380). The trade cards showed the underlying
strategy class label ("Late Entry V3"); owner wants the preset name they selected
("Close Sweep"). Updated the WebTrader `STRATEGY_LABEL` map to map each stored
`positions.strategy_type` (strategy class) to its preset display name from `bot/presets.py`:

- `late_entry_v3` → **Close Sweep** (only the close_sweep preset uses this class — exact)
- `confluence_scalper` → Crypto Scalper
- `trend_breakout` → Trend Breakout
- `momentum` → Contrarian
- `value_investor` → Value Hunter
- `copy_trade` → Whale Mirror
- `signal` → Signal Sniper, `signal_following` → Signal Following, `pair_arb` → Pair Arb, `ensemble` → Smart Mix

Unknown values still fall back to a title-cased de-underscored form.

---

## 2. Current system architecture

```
positions.strategy_type (strategy class)
  └─ GET /positions → PositionItem.strategy_type
       └─ PortfolioPage fmtStrategy() → STRATEGY_LABEL (preset display names)
            ├─ meta chip
            └─ "Strategy" detail row
```

Display-only mapping. No schema, migration, or trading-logic change.

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` — `STRATEGY_LABEL` now maps strategy classes → preset display names.

Created:
- `projects/polymarket/crusaderbot/reports/forge/trade-strategy-preset-names.md` (this file)

---

## 4. What is working

- `npm run build` (`tsc && vite build`) → exit 0, clean
- `late_entry_v3` (827 prod positions, the owner's active preset) now renders "Close Sweep" — exact, since that class backs only the close_sweep preset

---

## 5. Known issues

- `positions.strategy_type` stores the strategy class, not the preset. For classes shared by
  more than one preset (e.g. signal_following), the label is a best-effort representative
  name. The owner's case (late_entry_v3 → Close Sweep) is unambiguous and exact.
- A fully accurate long-term fix would persist the selected preset per position (new column +
  write path + can't backfill history) — deferred unless requested.

---

## 6. What is next

- WARP🔹CMD: review + merge + fly deploy (STANDARD, paper-safe — display-only).

Suggested Next Step: WARP🔹CMD review + merge. STANDARD tier.
