# WARP•FORGE Report — webtrader-trade-strategy-label

Branch: WARP/webtrader-trade-strategy-label
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Surface the strategy that opened each trade in the WebTrader open/closed trade cards
Not in Scope: Telegram trade rendering, strategy attribution logic (read-only display of existing positions.strategy_type)

---

## 1. What was built

Open and closed trade cards on the WebTrader Portfolio page now show **which strategy opened the trade**.

The data already existed (`positions.strategy_type`, populated in prod: late_entry_v3, trend_breakout, momentum, signal_following, value_investor) but was never returned by the API or rendered. This lane plumbs it through end-to-end:

- Compact strategy label in the trade card meta line (at-a-glance).
- "Strategy" row in the expandable trade detail (full context on tap).
- Friendly labels via `STRATEGY_LABEL` map with a title-cased fallback for any unmapped value.

---

## 2. Current system architecture

```
positions.strategy_type (existing column, mig 041)
  └─ GET /positions SELECT adds p.strategy_type
       └─ PositionItem.strategy_type (backend schema + frontend type)
            └─ PortfolioPage PositionRow
                 ├─ meta line: <strategy chip>  (fmtStrategy)
                 └─ detail:   "Strategy" DetailRow
```

`fmtStrategy()` maps known strategy_type values to readable labels and falls back to a
title-cased de-underscored form for unknown values. Renders nothing when null.

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `/positions` SELECT adds `p.strategy_type`; `PositionItem(... strategy_type=r["strategy_type"])`.
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` — `PositionItem.strategy_type: Optional[str] = None`.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` — `PositionItem.strategy_type?: string | null`.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` — `STRATEGY_LABEL` map + `fmtStrategy()`; strategy chip in meta line; "Strategy" detail row.

Created:
- `projects/polymarket/crusaderbot/reports/forge/webtrader-trade-strategy-label.md` (this file)

---

## 4. What is working

- `npm run build` (`tsc && vite build`) → exit 0, clean
- `py_compile router.py schemas.py` → OK
- Prod data confirmed populated: 827 late_entry_v3, 8 trend_breakout, 6 momentum, 5 signal_following, 2 value_investor (no nulls)
- Strategy shown on both open and closed cards; absent gracefully when strategy_type is null

---

## 5. Known issues

- `late_entry_v3` is shared by both the close_sweep and safe_close presets; the card shows the underlying strategy ("Late Entry V3"), not the preset name — accurate to the strategy used, by design.
- Telegram bot trade messages do not show strategy (out of scope; WebTrader only).

---

## 6. What is next

- WARP🔹CMD: review + merge + fly deploy (STANDARD, paper-safe — read-only display, no trading-logic or schema change).

Suggested Next Step: WARP🔹CMD review + merge. STANDARD tier.
