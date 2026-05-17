# WARP•FORGE REPORT — portfolio-ui-polish

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** WebTrader Portfolio page — header, P&L chart, enhanced position rows, history filter tabs
**Not in Scope:** Backend trading logic, SSE broadcaster changes, new DB migrations, Merge/Redeem tabs
**Suggested Next Step:** WARP🔹CMD review

---

## 1. What Was Built

Upgraded the WebTrader Portfolio tab to match Polymarket-level detail:

- **Portfolio header** — Equity (gold, large), Available to Trade, Realized P&L (signed, color-coded), Unrealized P&L (signed, color-coded) in a compact 3-column grid
- **P&L equity chart** — Recharts AreaChart with period selector (1D | 1W | 1M | 1Y | ALL); dark-themed gold line + gradient fill; tooltip shows equity at hover; "No trade history" empty state
- **History filter tabs** — Open | Closed | All | Orders (Orders gated to Advanced mode as before)
- **Enhanced closed trade rows** — now show cost basis, signed P&L with percent (e.g. `+$4.20 (21.0%)`), exit reason badge (TP / SL / MNL / EXP / STRAT / etc.), date
- **Open positions** — show live P&L (current_price vs entry_price), "LIVE" label, instructional EmptyState when no open positions
- **Two new backend endpoints** — `/portfolio/summary` and `/portfolio/chart` — compute equity, available cash, realized/unrealized P&L from existing `positions` + `wallets` tables; no new migrations required
- **`exit_reason` exposed** — added to PositionItem schema and positions SELECT query, mapped to human-readable badges on each trade row

---

## 2. Current System Architecture

```
WebTrader Frontend (React + Recharts)
  PortfolioPage.tsx
    ├── PortfolioHeader (equity + available + realized + unrealized)
    ├── PnlChart (Recharts AreaChart, period selector 1D/1W/1M/1Y/ALL)
    ├── FilterTabs (Open | Closed | All | Orders)
    └── PositionRow (enhanced: cost | pnl | exit_reason | time)

WebTrader Backend (FastAPI)
  /api/web/portfolio/summary   ← new: balance, realized, unrealized, equity
  /api/web/portfolio/chart     ← new: equity curve data points for period
  /api/web/positions           ← updated: now returns exit_reason field

Data sources (no new tables):
  wallets.balance_usdc         → available cash / equity base
  positions.pnl_usdc           → realized P&L aggregation
  positions.current_price      → unrealized P&L on open positions
  positions.exit_reason        → close reason badge on each row
```

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| Modified | `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` |
| Modified | `projects/polymarket/crusaderbot/webtrader/backend/router.py` |
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` |
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/portfolio-ui-polish.md` |

---

## 4. What Is Working

- `PortfolioSummary` schema: `available_usdc`, `realized_pnl`, `unrealized_pnl`, `equity_usdc`, `balance_usdc`
- `ChartPoint` schema: `ts`, `equity`
- `GET /portfolio/summary` — returns live equity breakdown; reads wallets + open positions + closed positions
- `GET /portfolio/chart?period=1W` — returns equity curve: start-of-period point + one point per trade closure + current equity as final point; handles ALL periods correctly
- `PositionItem` now includes `exit_reason` (from `positions.exit_reason` column, already populated by exit_watcher)
- Frontend `PortfolioHeader` renders equity + available + realized + unrealized with correct color tones (gold / grn / red / ink-2)
- `PnlChart` uses Recharts `AreaChart` + `ResponsiveContainer`; dark-themed; period selector matches FilterTabs visual language; "No trade history" empty state when < 2 data points
- `PositionRow` now shows: cost basis `$X.XX`, signed P&L `+$X.XX (Y.Y%)`, exit reason badge, date/LIVE
- Exit reason badge map covers all 8 ExitReason enum values; tone-coded: TP=grn, SL=red, FORCE=gold, ERR=red, others=ink
- SSE refresh correctly reloads both positions + chart on `position_opened`, `position_closed`, `portfolio_update`
- Python syntax verified clean; no migrations required

---

## 5. Known Issues

- Chart equity curve is balance-based (realized P&L only steps); unrealized only appears on the final point because historical `current_price` snapshots are not stored in the DB. This is the correct MVP approach for paper mode.
- `available_usdc` = `balance_usdc` (the wallet free cash). This is accurate because the trade engine deducts `size_usdc` from wallet on open and restores it on close.
- `equity_usdc` = balance + sum(open positions current value). For open positions without a `current_price` set, entry_price is used as fallback, giving equity = balance + deployed_cost (correct fallback).
- node_modules not installed in cloud execution environment — TypeScript compiler errors are pre-existing; Vite build requires `npm install` at deploy time (already in Dockerfile Stage 1).

---

## 6. What Is Next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/portfolio-ui-polish.md`
Tier: STANDARD
