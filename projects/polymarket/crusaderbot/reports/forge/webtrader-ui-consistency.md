# WARP•FORGE — webtrader-ui-consistency

Role: WARP•FORGE (WARP•R00T) — landing a Claude Design handoff (export verified).
Validation Tier: **STANDARD** (WebTrader frontend; no runtime/trading/backend change)
Claim Level: **NARROW INTEGRATION**
Validation Target: the WebTrader design-system consistency pass — `rounded-*` →
`clip-*` migration, HeroCard P&L grid, MarketFeed layout, and `type="button"` a11y,
across 16 frontend files. tsc + vite + a clip-class audit.
Not in Scope: backend, trading logic, Telegram lanes (T1–T4), and the proposed
`ScannerPanel` (described in the design summary but NOT present in the export — see §5).
Suggested Next Step: WARP🔹CMD review/merge (STANDARD). Linear WARP-52 (WebTrader UX).

---

## 1. What was built

A pure WebTrader frontend consistency pass, handed off from Claude Design and
verified into the repo. Five design lanes condensed into 16 changed files:

- **W1 Dashboard** — HeroCard meta becomes a 4-column `PnlCol` grid
  (Today / 7 Day / All Time / Balance); MarketFeed gets a two-row layout + a 3px
  probability bar; EmptyState uses an inline SVG ghost glyph; PositionCard/StatCard
  adopt `clip-*` + hover/focus states.
- **W2 Portfolio** — `rounded-*` → `clip-*`; CollapsibleSection hide/show polish.
- **W3 AutoTrade** — full `rounded-*` → `clip-*` migration (31 sites → 31 `clip-*`).
- **W4 Consistency** — `rounded-*` → `clip-*` across Settings / CopyTrade / Discover.
- **W5 Cross-cutting** — residual `rounded-*` → `clip-*` + `type="button"` added to
  buttons that were missing it (a11y / accidental-submit guard).

No new design tokens or utilities were introduced — the migration reuses the
`clip-*` clip-path utilities already defined in `src/index.css`
(`clip-card`/`-lg`/`-sm`, `clip-btn`, `clip-tab`, `clip-pos`, `clip-term`) and the
existing Tailwind tokens (`surface-1`, `border-1`, `font-hud`).

## 2. Current system architecture

No architectural change. Same React 18 + Vite + TypeScript + Tailwind SPA; same
routing, data hooks, and component contracts. The diff is presentational: utility
classes (`rounded-*` → `clip-*`), one new presentational sub-component (`PnlCol`,
local to DashboardPage), markup re-layout in MarketFeed/EmptyState, and `type`
attributes on existing buttons. `PositionRow` is still imported from PortfolioPage
into DashboardPage exactly as before (the vite dynamic/static-import advisory for
PortfolioPage is pre-existing on main, not introduced here).

## 3. Files created / modified (full repo-root paths)

All under `projects/polymarket/crusaderbot/webtrader/frontend/src/` (16 files):
- `pages/DashboardPage.tsx` (PnlCol 4-col grid), `components/MarketFeed.tsx`
  (two-row + prob bar), `components/EmptyState.tsx` (SVG), `components/HeroCard.tsx`,
  `components/PositionCard.tsx`, `components/StatCard.tsx`
- `pages/AutoTradePage.tsx` (31 `rounded`→`clip`), `pages/PortfolioPage.tsx`,
  `components/CollapsibleSection.tsx`
- `pages/SettingsPage.tsx`, `pages/CopyTradePage.tsx`, `pages/DiscoverPage.tsx`,
  `pages/AdminPage.tsx`
- `components/KillSwitchButton.tsx`, `components/TopBar.tsx`,
  `components/DesktopSidebar.tsx`
- Plus this report. State files updated separately (PROJECT_STATE + CHANGELOG).

(6 files in the export were byte-identical to the repo — incl. `index.css` — and were
NOT touched.)

## 4. What is working

- `npx tsc --noEmit` → exit 0 (the new `PnlCol` uses real `data.pnl_7d` /
  `pnl_alltime` fields; no type breakage).
- `npx vite build` → exit 0, clean (only the pre-existing PortfolioPage chunking
  advisory).
- **clip-class audit:** every `clip-*` class used across the 16 files resolves to a
  utility defined in `src/index.css` — no invented/typo classes that would silently
  render as plain rectangles.
- `git diff --stat` = exactly the 16 intended files (+190 / −169 after review fixes);
  no stray edits.
- **One regression caught + fixed in review** (Codex P2 + Gemini HIGH): the export
  snapshot predated `#1572` (playbook-live-dispatch) and silently reverted `playbook`
  out of `TOP_LEVEL_PRESET_KEYS` in AutoTradePage. Restored to match main. Verified
  `#1572` touched ONLY AutoTradePage in the frontend, so it was the sole semantic
  revert (the other 15 files diff against main as pure rounded→clip / a11y).
- **Hardening folded in** (Gemini MEDIUM): `PnlCol` value + `data.balance_usdc`
  default to `0` (null-safe); the W5 `type="button"` sweep was completed across all
  29 untyped buttons in the changed files (the intentional `type="submit"` on the
  SettingsPage link form is preserved).

## 5. Known issues

- **`ScannerPanel` NOT delivered.** The design summary + two of the export's own
  reports describe a new animated `ScannerPanel.tsx`, but it is **absent from the
  export** (no file, and nothing imports it). It is therefore intentionally excluded
  from this landing — claiming it would be inventing data. If wanted, it is a
  follow-up lane (`WARP/webtrader-scanner-panel`).
- The W1 HeroCard now shows P&L as a 4-col grid and drops the inline
  "N CLOSED" advanced line — a deliberate redesign, not a bug.

## 6. What is next

- WARP🔹CMD review/merge (STANDARD, frontend-only). Tracks Linear WARP-52.
- Optional follow-ups: deliver `ScannerPanel` properly; the Telegram lanes (T1–T4)
  the design pass flagged as "ready".

---

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: WebTrader rounded→clip consistency + P&L grid + a11y (16 files)
- Not in Scope: backend/trading, ScannerPanel, Telegram lanes
- Suggested Next Step: WARP🔹CMD review/merge
