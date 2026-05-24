# WARP•FORGE Report — WebTrader Home open positions + realtime + Force Redeem

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: the WebTrader Home "open positions" panel (replacing the signal feed), the realtime SSE + polling-fallback wiring on Home + Portfolio, and the awaiting-redeem / Force Redeem UI.
- Not in Scope: backend (the awaiting_redeem field + POST /positions/{id}/redeem endpoint ship in WARP-FRA / PR #1329); could not click-test in a browser here — validated via tsc + vite build only.
- Suggested Next Step: WARP🔹CMD review; deploy alongside PR #1329 (the endpoint it calls).

---

## 1. What was built

Three owner asks against the WebTrader UI:

1. **Home "Live Market Feed" → Open Positions** (`DashboardPage.tsx`): the right-column
   section that listed signal publications now lists the user's OPEN POSITIONS using the
   shared `PositionRow` (exported from `PortfolioPage`). Header reads "Open Positions (N)".
2. **Realtime** (`DashboardPage.tsx` + `PortfolioPage.tsx`): both pages now subscribe to
   the full position/portfolio SSE set — added `position_updated` (live price/PnL ticks)
   and `portfolio` (cb_portfolio NOTIFY) — and refresh on each. A 15s **polling fallback**
   (`setInterval(refresh, 15000)`) keeps equity/positions fresh even if the SSE stream
   stalls (reconnect gaps / proxy idle-timeouts); SSE remains the fast path.
3. **Force Redeem / awaiting-redeem** (`PositionRow` in `PortfolioPage.tsx`, `api.ts`):
   when `position.awaiting_redeem` is true (won, queued for hourly redeem), the card shows
   a "WON · AWAITING REDEEM" tag and a "⚡ Force Redeem" button that calls the new
   `api.forceRedeem(id)` (POST /positions/{id}/redeem) then refreshes. Wired on both the
   Portfolio open-positions list and the Home list.

## 2. Current system architecture

`PositionRow` is now exported from `PortfolioPage.tsx` and reused by `DashboardPage.tsx`
(single source of truth for the PnL/tone/footer rendering). `api.ts` gains
`PositionItem.awaiting_redeem?: boolean` and a `forceRedeem(positionId)` POST helper.
Realtime: `useSSE` handlers (positions / position_opened / position_closed /
position_updated / portfolio / portfolio_update / scanner_tick) call a combined refresh;
the interval fallback covers SSE outages. No backend code in this PR — it consumes the
WARP-FRA contract.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts (awaiting_redeem field + forceRedeem)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx (export PositionRow; awaiting/Force-Redeem UI; position_updated+portfolio SSE; 15s polling fallback)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx (Home feed → open positions; refreshAll SSE+poll; removed signal-feed state/loaders)

State:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- `tsc --noEmit` clean; `vite build` succeeds (881 modules; the >500kB chunk warning is
  pre-existing, not introduced here).
- Logic validated by types/build; the signal-feed code (getRecentSignals usage,
  feed state) is fully removed from Home with no dangling references.

## 5. Known issues

- Not browser-tested in this environment (no headless UI). Visual/interaction check
  recommended on deploy: Home shows open positions + Force Redeem on a won position,
  equity/PnL updates without manual refresh.
- The Force Redeem button + awaiting label only function once WARP-FRA / PR #1329
  (endpoint + awaiting_redeem field) is merged + deployed.
- Home cards intentionally omit the Cash Out button (kept on Portfolio) to stay compact.

## 6. What is next

- WARP🔹CMD review; merge with / after PR #1329, then Fly redeploy + WebTrader rebuild.
- Verify on-device: Home open-positions panel, live equity/PnL updates, Force Redeem
  settles a won position.
