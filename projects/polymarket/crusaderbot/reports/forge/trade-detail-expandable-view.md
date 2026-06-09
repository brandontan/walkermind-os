# WARP•FORGE — Expandable trade-detail view (entry/exit/SL/TP/close-reason)

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader position card — tap-to-expand detail showing entry/exit
time + price, SL/TP price, and close trigger. Backend exposes TP/SL on the positions API.
Not in Scope: trading logic, risk fences, exit_watcher, Telegram UI. Display-only.
Suggested Next Step: WARP🔹CMD review + deploy; verify on mobile that a card expands and
that open positions show blank exit time/price.

## 1. What was built

Owner mistook the market name ("May 25, 10:50PM-10:55PM" — the 5-minute candle window)
for a 5-second trade duration. Fix = make trade timing explicit. Each position card is
now tap-to-expand with a detail panel:
- Entry time + entry price
- Exit time + exit price — **blank ("—") while the position is open**, filled on close
- TP price and SL price (derived trigger levels)
- "Closed By": Take Profit / Stop Loss / Expired Time / Market Resolution / etc.

Collapsed view is unchanged (stays simple); a ▾ chevron indicates expandability.

## 2. Current system architecture

GET /api/web/positions now also returns `tp_pct`, `sl_pct`, `tp_price`, `sl_price`.
`tp_price`/`sl_price` are derived server-side by `_tp_sl_price()` in YES-price units
(matching entry_price/current_price), mirroring the PnL formula in
domain/execution/paper.close_position (YES profits as price rises, NO as it falls).
Frontend `PositionCard` gained an optional `detail` prop + internal expand state (tap
toggles; footer buttons stopPropagation). `PositionRow` builds the detail rows.

## 3. Files created / modified

- projects/polymarket/crusaderbot/webtrader/backend/schemas.py
  (PositionItem += tp_pct, sl_pct, tp_price, sl_price)
- projects/polymarket/crusaderbot/webtrader/backend/router.py
  (positions query selects COALESCE(applied_*, *)_pct; new `_tp_sl_price()` helper; maps
   the 4 fields)
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts
  (PositionItem interface += tp_pct/sl_pct/tp_price/sl_price)
- projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionCard.tsx
  (new `detail` prop, expand state, chevron, stopPropagation on detail/footer)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx
  (EXIT_FULL_LABEL, fmtDateTime, fmtCents, DetailRow; PositionRow builds + passes detail)
- projects/polymarket/crusaderbot/reports/forge/trade-detail-expandable-view.md (this report)

## 4. What is working

- ast.parse clean on router.py + schemas.py.
- Open positions: exit time/price render "—" (isOpen branch); fill in on close.
- TP/SL price math is side-aware and consistent with the existing yes-price entry display.
- Expand toggles per-card; footer Cash Out / Force Redeem clicks no longer toggle expand.

## 5. Known issues

- Entry price is shown as "{SIDE} @ {yes_price}¢", matching the EXISTING collapsed-card
  convention (yes-price units). Not changed here to avoid display inconsistency; a future
  lane could switch to side-native price across the whole card.
- pytest / tsc not runnable in this environment (no node_modules / pytest); verified by
  ast parse + reasoning. CI (Lint+Test) is the gate.
- TP/SL prices are null for positions opened without TP/SL (rendered "—").

## 6. What is next

- WARP🔹CMD review + deploy; mobile sanity check of expand + blank-exit-while-open.
