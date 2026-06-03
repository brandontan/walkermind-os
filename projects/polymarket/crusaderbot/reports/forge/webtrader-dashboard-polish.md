# WARP•FORGE — webtrader-dashboard-polish

Role: WARP•FORGE — landing the W1 Dashboard "Scanner Panel (NEW)" from a Claude Design handoff (export diff-verified).
Validation Tier: **STANDARD** (WebTrader frontend; no runtime/trading/backend/DB change)
Claim Level: **NARROW INTEGRATION**
Validation Target: the one net-new W1 item — the rich animated `ScannerPanel` from
`W1 Dashboard Preview.html` (change #2 "Scanner Panel (NEW)"), built as
`components/ScannerPanel.tsx` and wired into `DashboardPage`. tsc + vite + clip-class audit.
Not in Scope: backend, trading logic, risk gate, activation guards, DB; the other 5 W1
changes (HeroCard 4-col grid / MarketFeed two-row / PositionCard clip-tab badge /
EmptyState SVG / StatCard hover) — those already shipped in #1573 and are byte-identical
in main (see §4); Telegram lanes.
Suggested Next Step: WARP🔹CMD review/merge (STANDARD, frontend-only). Linear WARP-52.

---

## 1. What was built

The W1 Dashboard design is a before/after with **6 changes**. Diffing the handoff
against current `main` showed **5 of 6 already shipped in #1573** (byte-identical), and
the export's own `DashboardPage.tsx` was actually *older* than main — its only deltas were
the *absence* of the #1573 review hardening (null-safety + two `type="button"`), i.e. it
would have **regressed** merged fixes. So it was diff-rejected.

The **one genuinely net-new item is change #2: "Scanner Panel (NEW)"**. This lane builds it:

- **`components/ScannerPanel.tsx` (NEW)** — a faithful port of the HTML's `ScannerPanel`
  + `SignalCarousel` + `TLine`, written in the repo's Tailwind + clip-token idiom
  (`font-hud`=Orbitron, `font-mono`=JetBrains, `font-sans`=Rajdhani) instead of inline
  styles, so it matches the existing component conventions (`Terminal.tsx` aesthetic):
  - traffic-dot terminal header (`scanner@crusaderbot` + RUNNING/IDLE pulse + ▾/▸ collapse)
  - stats row: SCANNED / PUBLISHED / LAST-TICK (last-tick turns green when < 10s; live 1s clock)
  - green scan-sweep FX bar with "SCANNING" + signals-today count
  - 6 staggered type-in terminal lines (cyan `›` prompts, tone-coded parts) with an
    ACTIVE variant and a bot-OFF variant (mirrors the prior `buildScannerLines` semantics)
  - per-asset market rows: lean arrow + 3px probability bar (tonal glow) + % + countdown + liquidity
  - auto-advancing `FeedSignal[]` carousel (3.8s, pause-on-hover, dot pager, ◂▸ nav,
    progress bar, STRATEGY/TARGET/MARKET-ID detail grid) with direction-aware slide
  - collapsed strip (scanned · published · signals)
- **`pages/DashboardPage.tsx`** — mounts `ScannerPanel` in the right column, **replacing**
  the old `AdvancedOnly` `Terminal` + the separate "Scanner status strip" (the panel
  subsumes both); the dead `buildScannerLines` helper + `Terminal`/`lastSignals` plumbing
  removed. The top full-width `MarketFeed` is **kept** (owner choice — mobile feed strip).
- **`index.css`** — 5 new keyframes (`scanSweep`, `signalIn`, `slideInRight`,
  `slideInLeft`, `barProgress`) + `.animate-scan-sweep`.

## 2. Current system architecture

No architectural change. Same React 18 + Vite + TS + Tailwind SPA, same routing/hooks.
The panel is a presentational component fed by existing API endpoints. Two **new data
reads** were added to `DashboardPage` (both non-critical, fail-soft to placeholders):
`getRuntimeStatus()` → `/status` (`RuntimeStatus`) and `getRecentSignals(6)` →
`/signals/recent` (`FeedSignal[]`). Both join the existing `refreshAll` fan-out (initial
load + 15s poll + SSE `scanner_tick` + visibility refresh), so they refresh on the same
cadence as the rest of the dashboard. The SSE `scanner_tick` still updates `lastTick`
(used as the panel's `lastTickMs` fallback when `RuntimeStatus.scanner_last_tick` is null).

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/ScannerPanel.tsx` — NEW
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx` — mount panel, add /status + /signals/recent fetches, remove Terminal+strip+buildScannerLines
- `projects/polymarket/crusaderbot/webtrader/frontend/src/index.css` — 5 keyframes + .animate-scan-sweep
- `projects/polymarket/crusaderbot/reports/forge/webtrader-dashboard-polish.md` — this report
- State: `state/PROJECT_STATE.md` + `state/CHANGELOG.md` (updated separately, same commit)

## 4. What is working

- `npx tsc --noEmit` → **exit 0** (panel typed against real `RuntimeStatus` / `FeedSignal`
  / `MarketFeedItem`; `target_price: number | null` is null-guarded).
- `npx vite build` → **clean** (only the pre-existing PortfolioPage dynamic/static-import
  advisory, identical on main).
- **clip-class audit:** the panel uses only `clip-card` / `clip-card-sm` / `clip-tab` —
  all defined in `src/index.css`. Fonts map exactly (`font-hud`/`font-mono`/`font-sans`).
- **No invented fields:** every field the design's mock used was verified to exist in the
  real `lib/api.ts` before building — `RuntimeStatus.scanner_scanned/scanner_published/
  scanner_last_tick`, `FeedSignal.market_id/market_question/side/target_price/signal_type/
  published_at`, `MarketFeedItem.asset/label/up_prob/lean/seconds_to_close/liquidity_usdc`,
  `DashboardSummary.signals_today`.
- **Regression avoided (diff-first):** the export's `DashboardPage.tsx` was older than main
  and would have reverted #1573's null-safety + `type="button"` fixes — caught by diffing
  and NOT applied; only the net-new Scanner Panel was built on top of current main.
- **Degrade-safe:** if `/status` or `/signals/recent` fail, the panel renders with `0`/`—`
  placeholders and hides the (empty) market/signal sections — no crash, no fabricated data.

## 5. Known issues

- The Scanner Panel renders per-asset market rows AND the top full-width `MarketFeed`
  remains (owner-chosen). Minor visual redundancy on wide desktop; intentional so mobile
  users keep the always-visible feed strip. Can be revisited if desired.
- The signal carousel's "preset switch" reset keys on `signals.length`; if two presets ever
  return the same number of signals the carousel won't force-reset to card 0 (cosmetic only).
- Not runtime-verified against a live `/status` payload in this environment (no backend in
  the sandbox); validated via tsc + vite + type-contract check against `lib/api.ts`.

## 6. What is next

- WARP🔹CMD review/merge (STANDARD, frontend-only). Tracks Linear WARP-52.
- Optional follow-ups from the same handoff: W3 AutoTrade preview polish (separate preview
  file present in the bundle) and the Telegram keyboard/onboarding polish reports.

---

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: W1 "Scanner Panel (NEW)" — components/ScannerPanel.tsx + DashboardPage wiring
- Not in Scope: backend/trading/guards/DB, the 5 already-shipped W1 changes (#1573), Telegram
- Suggested Next Step: WARP🔹CMD review/merge
