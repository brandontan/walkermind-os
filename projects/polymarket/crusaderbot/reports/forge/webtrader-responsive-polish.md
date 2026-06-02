# WebTrader Responsive Polish — Open Positions + AUTO config

**Branch:** `WARP/webtrader-responsive-polish`
**Role:** WARP•FORGE
**Validation Tier:** STANDARD (user-facing UX; frontend-only, no trading core)
**Claim Level:** NARROW INTEGRATION

> Owner request: (1) make the AUTO-page Assets + Timeframe selector more
> minimalist but still elegant and informative; (2) the HOME Open Positions card
> isn't responsive on mobile; (3) ensure WebTrader UI/UX is responsive on
> mobile + desktop.

## 1. What was built

**A. HOME Open Positions — responsive carousel rewrite.** The old
`PositionCarousel` was an auto-advancing `translateX` slider; when caught
mid-transition it showed two half-cards (the previous card's right-aligned
values peeking on the left, the next card's labels on the right), which read as
"broken" on mobile — worse because the HOME cards are `defaultExpanded` (tall).
Rebuilt on **CSS scroll-snap**: a swipe-native horizontal track (`overflow-x-auto
snap-x snap-mandatory`), one full-width snap slide per position, dots synced to
scroll position, and **no passive auto-advance** — so the view always rests
cleanly on a card and can never be caught mid-animation. Native touch momentum on
mobile; dot navigation on desktop. Added a `.no-scrollbar` CSS utility so the
swipe track has no visible scrollbar while staying scrollable.

**B. Position detail — denser on desktop.** The expandable detail panel
(Strategy/Entry/Exit/TP/SL) now lays out single-column on mobile (readable) and
**two-column on desktop** (`md:grid md:grid-cols-2`), halving its height on wide
screens without cramping narrow ones.

**C. AUTO Assets + Timeframe — minimalist redesign.** Replaced the chunky
4-column asset grid (which left an empty 4th cell for 3 assets) + separate
2-column timeframe grid + boxed "Crypto only" tag + verbose footer with a tight,
elegant layout:
- "Markets" header + a subtle `Crypto · short-duration` caption.
- **3-up asset chips** (BTC/ETH/SOL, no empty cell), a small `●` marking active.
- A true **inset segmented control** for the 5m/15m candle timeframe.
- One concise summary line: `BTC · ETH — 5m candles only · category locked to Crypto.`

## 2. Current system architecture

Pure frontend/presentation. No API, preset, routing, risk, or execution change.
`PositionCarousel` is consumed only by the HOME `DashboardPage` open-positions
list (`count <= 1` still renders the child as-is). The app shell is already
mobile-first responsive (`max-w-mobile` + BottomNav on mobile; sidebar offset +
`overflow-x-hidden` on desktop) — a scan found no bare fixed-width or
non-responsive wide-grid overflow risks in the page content, so this lane
targets the two surfaces the owner reported rather than rewriting stable pages.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/PositionCarousel.tsx` (rewrite: scroll-snap)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx` (Assets/Timeframe redesign)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` (detail 2-col on desktop)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/index.css` (`.no-scrollbar` utility)
- `projects/polymarket/crusaderbot/reports/forge/webtrader-responsive-polish.md` (new)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (COMPLETED + timestamp)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append)

## 4. What is working

- `tsc --noEmit` exit 0; `vite build` clean.
- HOME open positions: swipe between cards on touch, dots on desktop; no
  mid-transition split; cards rest on a snap point.
- AUTO config: compact assets chips + segmented timeframe; selection + activation
  flow unchanged (same `handleToggleAsset` / `handleSelectTimeframe`).

## 5. Known issues / scope boundaries

- **Frontend only.** No backend / preset / execution change.
- Auto-advance was intentionally removed — position cards no longer rotate on
  their own; navigation is swipe/dots. (This is the fix, not a regression.)
- Visual result is best confirmed on the deployed Fly build on a real device.

## 6. What is next

- Owner visual review on mobile + desktop after Fly deploy.
- Unrelated epic continuation: complete-set-arb Lane 2 (PAPER two-leg execution).

---

- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** HOME open-positions carousel + AUTO Assets/Timeframe + position detail responsiveness
- **Not in Scope:** backend, preset registry, risk/execution, other pages (no reported issue)
- **Suggested Next Step:** WARP🔹CMD review; deploy to Fly; confirm on device.
