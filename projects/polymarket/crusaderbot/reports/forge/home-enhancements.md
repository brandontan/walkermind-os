# WARP•FORGE Report — home-enhancements

## 1. What Was Built

Four owner-requested improvements shipped as one lane:

**A. Signal scanner "more alive"** — always-visible compact status strip on the Home page showing: live scanner dot (pulse when auto_trade_on), last scan timestamp (from SSE `scanner_tick`), daily signals count (`signals_today`), and current tick candidate count. Not gated behind AdvancedOnly — visible to all users.

**B. Open positions expanded by default in Home** — `PositionCard` gains a `defaultExpanded?: boolean` prop (defaults `false`, preserving existing behaviour everywhere except Home where it is passed as `defaultExpanded`). `PortfolioPage` `PositionRow` threaded through the same prop so it reaches the card.

**C. Recent activity slide** — horizontal scroll rail below open positions showing the 5 most-recently closed trades. Each tile: P&L (coloured), side badge, exit reason label. Data from existing `GET /positions?status=closed&limit=5` — no new endpoint needed. Hidden if list is empty.

**D. Exit price TP/SL bug fix** — `exit_watcher.evaluate()` was returning `current_price=cur` (live sampled market price at poll time) for TP_HIT and SL_HIT exits. Because the exit watcher polls every 60 s, the market can move far past the threshold between ticks, causing massively inflated exit prices and unrealistic P&L (user-reported: +1244% on a TP that should have been ~+29%). Fix: two pure helpers `_tp_exit_price` and `_sl_exit_price` compute the mathematically exact price at which the threshold is crossed and are used as the paper fill price.

**E. Trade size "IN" label** — size in PortfolioPage meta row prefixed with a dim "IN" chip to clarify the figure is the entry investment amount in USD.

---

## 2. Current System Architecture

No structural changes. The exit_watcher domain function remains pure (no DB reads, no locks, no external calls). Backend router gains one extra COUNT query inside the existing `pool.acquire()` block. Frontend adds one state variable + one SSE-driven UI strip with no new API surface.

```
exit_watcher.evaluate()
  → _tp_exit_price / _sl_exit_price (new pure helpers)
  → ExitDecision(current_price = exact_threshold_price)

DashboardPage (frontend)
  → SSE scanner_tick → lastTick, lastSignals (existing)
  → /dashboard → signals_today (new field)
  → /positions?status=closed&limit=5 → recentClosed (existing endpoint, new call)
  → <ScannerStrip /> (new inline component)
  → <RecentActivityCard /> (new inline component)

PositionCard
  → defaultExpanded prop → useState(defaultExpanded ?? false)
```

---

## 3. Files Created / Modified

| Path | Change |
|---|---|
| `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` | Added `_tp_exit_price` + `_sl_exit_price` helpers; TP_HIT + SL_HIT cases in `evaluate()` now use them |
| `projects/polymarket/crusaderbot/tests/test_exit_watcher.py` | Updated 2 assertions: TP approx 0.50→0.48, SL approx 0.32→0.36 |
| `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` | Added `signals_today: int = 0` to `DashboardSummary` |
| `projects/polymarket/crusaderbot/webtrader/backend/router.py` | Added `signals_today` COUNT query in `/dashboard` handler |
| `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` | Added `signals_today: number` to `DashboardSummary` interface |
| `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionCard.tsx` | Added `defaultExpanded?: boolean` prop |
| `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` | Threaded `defaultExpanded` through `PositionRow`; added "IN" label to size |
| `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx` | Scanner status strip + recent activity slide + `defaultExpanded` on open positions |

---

## 4. What Is Working

- All 1762 tests pass (38 exit_watcher tests explicitly verified post-fix).
- `_tp_exit_price("yes", 0.40, 0.20)` = 0.48 ✓ (was returning live price 0.50).
- `_sl_exit_price("yes", 0.40, 0.10)` = 0.36 ✓ (was returning live price 0.32 at poll time — which happened to be below SL trigger but is non-deterministic in general).
- `signals_today` query is a single COUNT with a 24h interval — negligible cost; falls back to `0` on error.
- Scanner strip is always visible (not AdvancedOnly); uses existing `data.auto_trade_on` and SSE `lastTick`/`lastSignals` state — no new wires required.
- Recent activity fetched once on mount + inside `refreshAll` — no polling loop added.
- `defaultExpanded` defaults to `false` in PositionCard — no regression on Portfolio page or other consumers.

---

## 5. Known Issues

- `signals_today` counts rows in `positions` opened in the last 24 h by `user_id`. If a user has zero positions ever, the COUNT returns 0 (correct). If the bot opens positions on behalf of users not identified by JWT user_id, those would not appear — but that is not the current flow.
- The "IN" label uses `text-ink-4 text-[8px]` — very dim by design so it does not crowd the number. If the design token `ink-4` is not defined in the Tailwind config it falls back to `text-ink-3`; visually acceptable either way.
- No "NO side" TP/SL exit price formula has been tested against live NO positions; the `_tp_exit_price`/`_sl_exit_price` formulas for `side == "no"` follow the same `_return_pct` inverse convention already in the codebase and are covered by the existing test suite's NO-side cases.

---

## 6. What Is Next

- WARP🔹CMD deploy: `git push` → Fly.io CD auto-deploy fires on main push.
- Monitor: After deploy, verify a new TP/SL close produces a realistic exit price and P&L in the WebTrader portfolio view.
- Migration 054 (`max_drawdown_pct`) is already applied to production (done earlier this session). Gate/engine changes from lane #4 (daily-loss-drawdown) are still pending WARP🔹CMD review.

---

## Metadata

- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** exit_watcher TP/SL exit pricing + WebTrader Home page UX (scanner strip, expanded positions, recent activity, size label)
- **Not in Scope:** Portfolio page analytics backend, SL/TP on live (non-paper) positions, Telegram bot UI
- **Suggested Next Step:** WARP🔹CMD review → merge → deploy
