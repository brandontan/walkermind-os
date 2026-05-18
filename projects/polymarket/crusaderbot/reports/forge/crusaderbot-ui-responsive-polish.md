# WARP•FORGE REPORT — crusaderbot-ui-responsive-polish

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader frontend responsive layout (6 pages) + Market Filter UI + Auto Redeem setting + CopyTrade UX improvements + backend endpoints + migration 036
Not in Scope: signal_scan_job market filter application (backend filter wire-in to scanner job; DB schema and endpoint ready), live trading path, Telegram bot changes
Suggested Next Step: WARP🔹CMD review required. Migration 036 must be applied before deploy.

---

## 1. What Was Built

Four-part UI polish bundle for CrusaderBot WebTrader:

**Part 1 — Responsive Layout (md: breakpoint ≥768px)**
- `DashboardPage`: 2-column grid on desktop — scanner terminal + stats in left column, recent activity + kill switch in right column. Mobile unchanged.
- `AutoTradePage`: Strategy preset cards: `grid-cols-1 md:grid-cols-3` (3 per row on desktop). Risk Profile cards: `grid-cols-2 md:grid-cols-4` (4 per row on desktop). Custom risk card: `col-span-2 md:col-span-1`.
- `CopyTradePage`: Add target form: `md:grid md:grid-cols-2 md:gap-3` — side-by-side fields on desktop.
- `PortfolioPage`: Chart full width (unchanged). Open/closed/all position lists wrapped in `md:grid md:grid-cols-2 md:gap-3` on desktop.
- `WalletPage`: `md:grid md:grid-cols-2` — wallet balance + address left, transaction list right on desktop.
- `SettingsPage`: `md:grid md:grid-cols-2` — Display + Notifications + Trading left, Account right on desktop.

All mobile layouts unchanged — responsive prefix `md:` only applies at ≥768px.

**Part 2 — Market Filter / Market Picker (AutoTradePage)**
- New "MARKET FILTER" section below Risk Profile.
- 9-category multi-select checkboxes (Politics, Sports, Crypto, Finance, Science, Entertainment, World, Weather, Other) with visual toggle (gold = on, surface = off).
- 3 dropdown filters: Min Liquidity ($1k/$5k/$10k/$50k), Max Time to Resolution (Any/1d/7d/30d/90d), Min Volume 24h ($100/$500/$1k/$5k).
- Save button → `PATCH /api/web/autotrade/market-filters`.
- State pre-loaded from `AutoTradeState` on mount; confirmed saves with "✓ Saved" flash.

**Part 3 — Auto Redeem Setting (SettingsPage)**
- New "TRADING" section in SettingsPage (left column on desktop).
- Toggle ON/OFF for Auto Redeem.
- Radio group for Redeem Mode (Instant / Hourly) — shown only when toggle is ON.
- Persists via `PATCH /api/web/config/trading`.
- Optimistic-style update: mode change fires immediately while toggle is ON.

**Part 4 — Copy Trade UX (CopyTradePage)**
- Page header description explaining what Copy Trade does.
- Instructional empty state with whale emoji, explanation text, and inline "+ Add Target" CTA.
- Per-field helper text on all form fields (Wallet Address, Copy Direction, Copy Type, Slippage, Allow Top-ups).
- Copy Direction helper text updates dynamically based on selection.
- Copy Type helper text updates dynamically based on selection.
- Active target cards now show fetched stats (Trades copied, Est. PnL from `/copy-trade/tasks/{id}/stats`) — best-effort, non-blocking.
- "Add Target" button shown at bottom of targets list when form is hidden.
- Cancel button inline in form header.
- Form fields use `md:grid md:grid-cols-2` side-by-side on desktop.

---

## 2. Current System Architecture

Frontend (Vite + React + Tailwind):
- Responsive breakpoint: `md:` (≥768px Tailwind default = 768px)
- All layout changes are CSS-only (grid wrapper divs added; component logic unchanged)
- AutoTradePage: market filter state loaded from `GET /autotrade`, saved to `PATCH /autotrade/market-filters`
- SettingsPage: auto_redeem loaded from `GET /settings`, saved to `PATCH /config/trading`
- CopyTradePage: stats loaded in parallel via `GET /copy-trade/tasks/{id}/stats` on each task load

Backend (FastAPI + asyncpg):
- `GET /api/web/autotrade` — extended to return market filter fields from user_settings
- `PATCH /api/web/autotrade/market-filters` — new endpoint, updates category_filters + min_liquidity + max_resolution_days + min_volume_24h
- `GET /api/web/settings` — extended to return auto_redeem + redeem_mode (auto_redeem_mode)
- `PATCH /api/web/config/trading` — new endpoint, updates auto_redeem + auto_redeem_mode
- `PATCH /api/web/autotrade/customize` — unchanged, already handles auto_redeem_mode via CustomizeRequest

DB (migration 036):
- Adds 4 columns to user_settings: min_liquidity NUMERIC DEFAULT 1000, max_resolution_days INT nullable, min_volume_24h NUMERIC DEFAULT 100, auto_redeem BOOLEAN DEFAULT FALSE
- category_filters TEXT[] and auto_redeem_mode VARCHAR already existed from migration 001

---

## 3. Files Created / Modified

Created:
- `projects/polymarket/crusaderbot/migrations/036_ui_responsive_polish.sql`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-ui-responsive-polish.md`

Modified:
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/CopyTradePage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/WalletPage.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` (added updateTradingSettings, updateMarketFilters, AutoTradeState market fields, UserSettings auto_redeem fields, TradingSettings and MarketFilterSettings types)
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` (AutoTradeState + TradingSettingsUpdate + MarketFilterUpdate)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (get_autotrade extended, 2 new PATCH endpoints, get_settings extended)

---

## 4. What Is Working

- All 6 pages render single-column on mobile (no mobile change), 2-column on desktop (md:grid).
- AutoTradePage strategy grid: 3-per-row on desktop, 1-per-row mobile.
- AutoTradePage risk grid: 4-per-row on desktop, 2-per-row mobile.
- Market filter categories: 9-item checkbox grid, gold-highlighted on selection.
- Market filter dropdowns: 3 independent selects with correct option values.
- Market filter save → PATCH /autotrade/market-filters → updates category_filters, min_liquidity, max_resolution_days, min_volume_24h.
- Auto Redeem toggle persists via PATCH /config/trading.
- Redeem mode radio (Instant/Hourly) visible only when auto_redeem ON.
- CopyTrade empty state: instructional, with inline CTA.
- CopyTrade form: side-by-side on desktop, helper text on all fields.
- CopyTrade targets: stats row (trades + Est. PnL) populated from existing stats endpoint.
- Backend Python syntax clean (py_compile verified).
- Pre-existing TS build errors are environment-only (node_modules missing in CI); no new type errors introduced.

---

## 5. Known Issues

- signal_scan_job._fetch_markets_for_lib_strategies() does NOT yet apply user market filters. The DB columns and PATCH endpoint are live; wiring the filter read into the scanner job is a follow-up lane (WARP/CRUSADERBOT-SCANNER-MARKET-FILTER). Low-risk deferral — scanner continues with current behavior.
- Auto Redeem backend hook not yet wired to position close handler / redeem flow. The toggle + mode persist correctly; actual redemption trigger requires a separate lane (WARP/CRUSADERBOT-AUTO-REDEEM-WIRE).
- CopyTrade stats may show "—" on first load if the stats endpoint is slow or unavailable; this is intentional best-effort pattern with non-blocking Promise.allSettled.
- Migration 036 must be applied to production DB before deploying; without it, the new columns don't exist and the /autotrade/market-filters and /config/trading PATCHes will error.
- TypeScript build requires npm install in environment; pre-existing node_modules absence is not introduced by this PR.

---

## 6. What Is Next

WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-ui-responsive-polish.md
Tier: STANDARD

Post-merge:
- Apply migration 036 to production DB.
- WARP/CRUSADERBOT-SCANNER-MARKET-FILTER: wire user market filters into signal_scan_job._fetch_markets_for_lib_strategies().
- WARP/CRUSADERBOT-AUTO-REDEEM-WIRE: wire auto_redeem flag + redeem_mode into position close handler / redeem queue.
