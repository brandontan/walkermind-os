# WARP•FORGE Report — webtrader-redesign

**Branch:** WARP/CRUSADERBOT-WEBTRADER-REDESIGN
**Date:** 2026-05-16
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Visual layer of WebTrader SPA — all 5 authenticated pages + shared components
**Not in Scope:** Backend API, SSE logic, auth flow, database, Telegram bot, deployment
**Suggested Next Step:** WARP🔹CMD review → merge to main → fly deploy alongside autotrade-runtime-fix

---

## 1. What Was Built

Full premium visual redesign of the WebTrader React/TypeScript SPA. Replaced the
Inter-font, amber/muted-grey palette with a Syne + JetBrains Mono typographic system
and a deeper dark palette (midnight black #080A0F, richer card surfaces, gold #F5C842
accent, semantic green/red/blue). All 5 authenticated pages and 5 shared components
were reskinned. All API/SSE/auth logic was preserved verbatim — only the visual layer
changed.

---

## 2. Current System Architecture

```
WebTrader SPA (React 18 + Vite + TypeScript + Tailwind CSS)
├── index.html              — Syne + JetBrains Mono Google Fonts
├── tailwind.config.ts      — new color tokens (bg/surface/card/gold/green/red/blue)
├── src/index.css           — base styles + fadeSlideUp + statusPulse keyframes
├── src/App.tsx             — ambient bg radial gradients (gold top-left, blue bottom-right)
├── src/components/
│   ├── BottomNav.tsx       — gold active indicator bar (20×2px), backdrop-blur
│   ├── PnLCard.tsx         — 2px top accent bar per color type
│   ├── StrategyCard.tsx    — gold border/bg on active state; freq label added
│   ├── PositionTable.tsx   — table → list card format with badge row
│   └── KillSwitchButton.tsx — updated to rounded-2xl, active:scale-95
└── src/pages/
    ├── DashboardPage.tsx   — topbar logo+LIVE+PAPER; hero; 2×2 stat grid; scanner; positions preview
    ├── AutoTradePage.tsx   — updated preset keys (signal_sniper/full_auto/value_hunter)
    ├── PortfolioPage.tsx   — Recharts AreaChart PnL with 7D/30D/ALL; list-format positions
    ├── WalletPage.tsx      — blue gradient hero; list transaction rows
    └── SettingsPage.tsx    — 4 notification toggles; account group; disconnect
```

All existing logic files unchanged:
`src/lib/api.ts`, `src/lib/auth.ts`, `src/lib/sse.ts`, `src/pages/AuthPage.tsx`,
`src/components/TelegramAuth.tsx`, `src/components/CustomizeDrawer.tsx`

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/webtrader/frontend/index.html`
- `projects/polymarket/crusaderbot/webtrader/frontend/tailwind.config.ts`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/index.css`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/BottomNav.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PnLCard.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/StrategyCard.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionTable.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/KillSwitchButton.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/WalletPage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx`

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/webtrader-redesign.md`

---

## 4. What Is Working

- `npm run build` passes with zero TypeScript errors across all 3 build checks
- Design tokens updated: bg=#080A0F, surface=#0D1117, card=#131920, gold=#F5C842, green=#00D68F, red=#FF4D6A, blue=#4D9EFF
- Syne font for all UI text; JetBrains Mono applied to all dollar/numeric values via `font-mono`
- fadeSlideUp page transition + statusPulse animation keyframes in CSS
- Ambient radial gradients (gold top-left, blue bottom-right) in AppShell
- BottomNav: gold active indicator 20×2px bar at top, backdrop-blur(12px)
- Dashboard: topbar with LIVE pulse pill + PAPER badge; hero card; 2×2 stat grid with per-type accent bars; scanner card from `getAlerts()` API; open positions preview (max 2) with "View all →" NavLink
- AutoTrade: preset keys corrected to actual domain keys (`signal_sniper` / `full_auto` / `value_hunter`); display names match spec; active card shows ✓ ACTIVE badge, no Switch button
- Portfolio: Recharts AreaChart with green gradient fill + 7D/30D/ALL toggle (client-side time filter); flat-line empty state with message "No closed trades yet — chart updates on first close"; filter tabs (All/Open/Closed) with gold active state; list-format position items with badge row
- Wallet: blue gradient hero balance card; deposit address card; list transaction rows
- Settings: 4 notification toggles (all wired to single `notifications_on` field — correct mapping per data model); Account group with PAPER badge, username, tier; full-width red Disconnect button
- All financial values use font-mono class
- No horizontal overflow on max-width 430px container

---

## 5. Known Issues

- Recharts bundle adds ~380KB to JS bundle (chunk size warning in Vite — not an error; expected for a charting library)
- Portfolio PnL chart requires positions with `status=closed` and non-null `pnl_usdc` to render. Empty state shown until first closed trade — by design per WARP🔹CMD note
- Strategy preset display names differ from domain preset names (intentional — display-only adaptation per spec). API calls use correct domain keys
- `LedgerEntry.mode` field does not exist in the type — WalletPage hardcodes "Paper" label for transaction origin row. If ledger source tracking is added to the backend schema later, wire it here

---

## 6. What Is Next

- WARP🔹CMD review and merge decision for WARP/CRUSADERBOT-WEBTRADER-REDESIGN
- After merge: fly deploy alongside autotrade-runtime-fix (both changes complement each other)
- Post-deploy: run live Telegram smoke test + open WebTrader on mobile to verify font loading and animation smoothness
- Future: add `mode` field to `LedgerEntry` backend schema + frontend type to show live/paper tag per transaction
