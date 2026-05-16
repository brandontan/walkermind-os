# Forge Report — webtrader-v3-and-bot-polish

**Branch:** `WARP/webtrader-v3-and-bot-polish`
**PR:** #1069
**Date:** 2026-05-16 20:06 Asia/Jakarta
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Supersedes:** PR `WARP/CRUSADERBOT-WEBTRADER-REDESIGN` (to be closed by WARP🔹CMD)

## 1. What was built

Atomic delivery of two coupled surfaces in the Tactical Terminal v3.2 design system:

**Web trader (React/Vite/Tailwind):**
- Full port of the v3.2 mock to the existing 6-page React app (auth, dashboard, autotrade, portfolio, wallet, settings).
- New visual system: Anton (display), Orbitron (HUD labels), Rajdhani (body), JetBrains Mono (data). Clip-path HUD geometry, scanline + grain overlay, ambient gold/blue washes, animated sweep + count-up + terminal lines.
- **Advanced Mode toggle** — master switch in Settings that hides technical surfaces (ticker, terminal, market IDs, asymmetric stats, ledger entries, activation guards). Persists via `localStorage["cb_ui_advanced"]`, mirrored to `body.advanced` for any future CSS-only consumers.
- SSE stream, JWT auth, all API endpoints reused unchanged.

**Telegram bot:**
- Command consolidation: removed 4 redundant aliases (`/pnl`, `/close`, `/scan`, `/mode`). Single alias `/trades` kept for user muscle memory.
- New unified emoji palette + `DIV` divider + `_table()` aligned `<pre>` helper in `bot/messages.py`. Five new alert templates (signal / position_open / position_close / daily_summary / health) following the Tactical Terminal tone.
- New shared keyboard helpers in `bot/keyboards/_common.py` (home_row, home_back_row, confirm_cancel_row, pagination_row) reserving `nav:` / `act:` / `cfg:` callback prefix namespaces. Registered `_nav_cb` dispatcher handler at group=-1.
- Two existing keyboards refactored to 2-col mobile-friendly layout (`presets.py`, `settings.py`).

## 2. Current system architecture

```
DATA ─→ STRATEGY ─→ INTELLIGENCE ─→ RISK ─→ EXECUTION ─→ MONITORING
                                                          │
                                                          ├─→ Telegram bot (HTML, EMOJI/DIV palette)
                                                          └─→ WebTrader FastAPI + SSE
                                                              └─→ React SPA (Tactical Terminal v3.2)
                                                                  ├─ UiMode context (advanced toggle)
                                                                  ├─ Shared HUD components
                                                                  └─ 6 pages (3 routes adv-gated)
```

No pipeline change; RISK still runs before EXECUTION; no shims; no Kelly modification; ENABLE_LIVE_TRADING untouched.

## 3. Files created / modified (full repo-root paths)

**Modified**
- `projects/polymarket/crusaderbot/webtrader/frontend/tailwind.config.ts`
- `projects/polymarket/crusaderbot/webtrader/frontend/index.html`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/index.css`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/{Dashboard,AutoTrade,Portfolio,Wallet,Settings,Auth}Page.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/{BottomNav,StrategyCard}.tsx`
- `projects/polymarket/crusaderbot/bot/dispatcher.py`
- `projects/polymarket/crusaderbot/bot/messages.py`
- `projects/polymarket/crusaderbot/bot/keyboards/presets.py`
- `projects/polymarket/crusaderbot/bot/keyboards/settings.py`
- `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py`

**Created**
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/uiMode.ts`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AdvancedGate.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/TopBar.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/Ticker.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/HeroCard.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/StatCard.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/StatsGrid.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/Terminal.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionCard.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/EmptyState.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/Toggle.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/FilterTabs.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/WalletCard.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AddressCard.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/SettingsGroup.tsx`
- `projects/polymarket/crusaderbot/bot/keyboards/_common.py`
- `projects/polymarket/crusaderbot/reports/forge/webtrader-v3-and-bot-polish.md` (this file)

**Removed (hard delete, no shims)**
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PnLCard.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionTable.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/CustomizeDrawer.tsx`

## 4. What is working

- `npm run build` clean — 62 modules, 211 KB JS (gzip 66 KB), 21 KB CSS (gzip 5 KB). Bundle dropped ~370 KB vs main because PortfolioPage no longer imports Recharts.
- `python3 -m pytest projects/polymarket/crusaderbot/tests/ -q` — **1400 passed, 1 skipped, 0 failures**.
- `ruff check .` — no issues.
- Advanced Mode toggle persists across reload; `body.advanced` class flips correctly; `<AdvancedOnly>` / `<EssentialOnly>` wrappers gate all v3.2-spec elements.
- All 6 webtrader pages render with the new HUD aesthetic.
- New `nav:home` callback prefix routed by `dispatcher._nav_cb` returns the user to the dashboard from any nested screen.
- 5 new bot alert templates (`signal_alert_text`, `position_open_text`, `position_close_text`, `daily_summary_text`, `health_alert_text`) ready to be wired by alert call sites.

## 5. Known issues

- `crusaderbot-logo.png` binary still missing — `TopBar` and `AuthPage` `<img onError>` hides the element gracefully. Asset delivery owed by `WARP/startup-logo-fix` PR.
- Three notification toggles on `SettingsPage` (Trade Opened / Trade Closed / Daily Report) all bind to the single `notifications_on` backend flag. Granular per-event preferences need a backend schema extension and an `api.UserSettings` field expansion — out of scope.
- Alert dedup audit (`monitoring/alerts.py`, `exit_watcher.py`) and onboarding state-machine consolidation (`bot/handlers/start.py`) — both originally planned for this PR — are **deferred to follow-up** to keep this PR reviewable. Tests `test_alerts_dedup.py` and `test_onboarding_state.py` are not in this PR.
- Legacy callback prefixes (`p5:`, `setup:`, `dashboard:`, `wallet:`, …) remain registered alongside the new `nav:` namespace. Full migration is gradual.
- Sentry / telemetry instrumentation for the new advanced-mode toggle is not added.

## 6. What is next

- WARP🔹CMD: close `WARP/CRUSADERBOT-WEBTRADER-REDESIGN` after this PR lands (superseded).
- WARP•SENTINEL validation required (tier MAJOR) before WARP🔹CMD merge — focus areas:
  - User-facing trading surfaces (web + bot) — verify no info loss vs main.
  - Telegram dispatcher safety — `_nav_cb` registration at group=-1 must not shadow ConversationHandler states.
  - Frontend build clean across Node 20 + 22 (CI uses 20).
- Follow-up lanes (separate WARP branches):
  - `WARP/bot-alert-dedup-audit` — dedup keys + fail-open + tests for the 7 alert types.
  - `WARP/bot-onboarding-state-canonical` — single `onb_state` key + idempotent /start + /resetonboard hardening + tests.
  - `WARP/webtrader-notif-granular` — backend + frontend wiring for per-event notification preferences.

---

**Validation Target:** WebTrader visual port to v3.2 + Advanced Mode toggle + bot command consolidation + bot template foundation (EMOJI/DIV/_table + 5 alert templates) + new keyboard helper namespace.

**Not in Scope:** Alert dedup hardening, onboarding state consolidation, granular notification toggles, migration 030 production apply, `crusaderbot-logo.png` binary commit, full callback-prefix migration, live trading activation.

**Suggested Next Step:** WARP•SENTINEL validation (MAJOR), then WARP🔹CMD merge decision.
