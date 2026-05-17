# WARP•FORGE Report — crusaderbot-ux-phase1

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** 5 WebTrader UX improvements — hash display, copy trade inputs, portfolio chart, win rate logic, alert center
**Not in Scope:** trading engine, scanner, live trading guards, migrations 030-036, backend auth changes
**Suggested Next Step:** WARP🔹CMD review; deploy to staging and verify in browser (375px + desktop)

---

## 1. What Was Built

Five UX quick-wins bundled into a single PR:

**Item 1 — Wallet Hash Truncate + Copy**
- New `TxHash` component (`webtrader/frontend/src/components/TxHash.tsx`): displays `0x1234...abcd` (first 6 + last 4 chars), inline clipboard icon with green flash on success. Fallback execCommand for non-secure contexts.
- `AddressCard.tsx`: deposit address truncated in display; title attribute preserves full address; existing Copy button unchanged.
- `CopyTradePage.tsx`: wallet_address in task list now rendered via `TxHash` component (replaces custom `truncateWallet` with 8+4 format).

**Item 2 — Copy Trade Input Visibility**
- All inputs and selects in the Copy Trade add-form now use `INPUT_CLS` constant:
  - default: `border border-border-2 bg-surface`
  - focus: `border-gold` + `box-shadow 0 0 0 2px rgba(245,200,66,0.08)`
  - active: `border-border-3`
- Font, size, padding, placeholder text unchanged.

**Item 3 — Portfolio Chart Hover + Grid**
- Period labels updated: `1D / 7D / 30D / All` (removed 1Y). Backend receives `PERIOD_API` mapped params (`7D→1W`, `30D→1M`). Added `"7D"` and `"30D"` aliases to `_CHART_LOOKBACK` in `router.py`.
- `CartesianGrid`: horizontal lines only, `stroke="rgba(245,200,66,0.06)"`, no dashes.
- Custom `ChartTooltip`: equity value + date/time (Locale) + PnL delta from period start, styled with `#0A1628` surface + `rgba(245,200,66,0.14)` border + JetBrains Mono.
- `ChartEntry` type extended with `ts` and `pnlDelta` fields for tooltip use.

**Item 4 — Win Rate Bug Fix**
- Root cause: `close_as_expired()` sets `status='closed'` AND `exit_reason='market_expired'` with `pnl_usdc=0.0`. Previous query counted those as losses.
- Fix: dashboard totals query now excludes `exit_reason='market_expired'` from total, wins, and losses counts using `IS DISTINCT FROM 'market_expired'`.
- Inline comment added in `router.py` explaining settled YES / settled NO / expired logic.

**Item 5 — Alert Center**
- New `AlertCenter.tsx` component: slide-in panel (right side, full height, `min(360px, 92vw)`) with backdrop, header ("ALERT CENTER" in Orbitron), scrollable alert list, empty state ("No alerts yet."), close button.
- Category badges derived from `severity` / `title`: TRADE (gold) / RISK (red) / COPY (cyan) / SYSTEM (ink-2).
- Relative timestamps ("just now", "5m ago", "2h ago", "3d ago").
- `AlertCenterContext` added to `App.tsx`: fetches from `/api/web/alerts`, tracks `lastSeen` timestamp in `localStorage['alertCenter_lastSeen']`, computes `unreadCount`.
- `TopBar.tsx`: bell button now calls `openAlertCenter()` from context; badge shows `unreadCount` from context. Props `notifCount` / `onBellClick` kept for backward compat (now unused).
- `DashboardPage.tsx`: no longer fetches alerts independently; consumes `useAlertCenter()` context. Load function simplified.

---

## 2. Current System Architecture

```
AppShell (App.tsx)
├── AlertCenterContext  ← fetches /api/web/alerts, tracks lastSeen
│   └── AlertCenter.tsx (fixed overlay, z-201)
├── SSEStatusContext
├── All page routes
│   └── TopBar.tsx  ← reads context for unreadCount + open action
│       └── bell button → AlertCenter panel
└── PortfolioPage.tsx
    └── PnlChart (Recharts AreaChart)
        ├── Custom ChartTooltip
        ├── CartesianGrid horizontal only (gold 0.06 opacity)
        └── Period tabs: 1D / 7D / 30D / All
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/TxHash.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AlertCenter.tsx`

**Modified:**
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AddressCard.tsx` — truncate displayed address
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/TopBar.tsx` — AlertCenter context wiring
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/CopyTradePage.tsx` — TxHash + INPUT_CLS
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` — chart tooltip + grid + periods
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx` — use context alerts
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx` — AlertCenterContext provider
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — win rate fix + chart period aliases

**State files:**
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md` (if applicable)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What Is Working

- Vite build: `tsc && vite build` passes, 864 modules, 634KB bundle. No new build errors.
- Python syntax: `router.py` passes `ast.parse` cleanly.
- Hash truncation: `TxHash` component with correct 6+4 format, clipboard copy, green flash.
- Input borders: `border-border-2` / `bg-surface` defaults, gold glow on focus, `border-border-3` on active.
- Chart: horizontal-only grid lines in gold (0.06 opacity), custom tooltip with equity+date+delta, 4 period tabs (1D/7D/30D/All).
- Win rate: `exit_reason IS DISTINCT FROM 'market_expired'` excludes expired positions from total, wins, and losses.
- Alert Center: slide-in panel from right, category badges, relative timestamps, unread count badge, mark-all-read on open, empty state.
- Advanced/essential mode toggle preserved (no changes to AdvancedGate / UiModeContext).
- Scanner terminal animation preserved (no changes to Terminal.tsx).

---

## 5. Known Issues

- Alert Center data is from `system_alerts` (global, not user-scoped). User-specific alerts (TRADE/COPY per user) require a separate lane with DB schema changes.
- `TxHash` on mobile: very long hashes (42+ chars) will display as `0x1234...abcd` which is correct; the tooltip text is the full hash.
- Period "All" maps to `ALL` in backend (no lookback limit); charts may load slowly on large datasets.
- Branch mismatch: session was configured as `claude/crusaderbot-ux-phase1-zClyD` while WARP🔹CMD declared `WARP/CRUSADERBOT-UX-PHASE1`. Work executed on session branch per remote execution environment policy. WARP🔹CMD to note.

---

## 6. What Is Next

WARP🔹CMD review of all 5 items. If any item needs rework, open specific lane for that item only. Full WARP•SENTINEL run not required (STANDARD tier).
