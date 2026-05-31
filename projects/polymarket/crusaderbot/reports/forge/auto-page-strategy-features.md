# WARP•FORGE — auto-page-strategy-features

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: AutoTradePage strategy-card feature surfacing + Risk Profile layout reorder (frontend-only)
Not in Scope: backend router, preset params, runtime config wiring, execution/risk logic, Telegram bot UI
Suggested Next Step: WARP🔹CMD visual review on mobile; optional follow-up to wire live operator-toggle state into feature chips

---

## 1. What was built

A premium-but-readable pass over the AUTO TRADE page (`AutoTradePage.tsx`):

- **Strategy feature visibility.** Each strategy preset now shows a row of
  feature chips describing what it actually does, plus an inline
  "ⓘ How it works" toggle that expands a short bullet explanation of the
  mechanism. Honest capability descriptions — not runtime on/off state — so the
  card never lies when an operator flag changes.
- **Risk Profile layout reorder.** The profile picker cards
  (Conservative / Balanced / Aggressive / Custom) now come FIRST under the
  section title, matching the mental model "pick a profile, then tune". The
  fine-tune limits (Max per trade, Daily loss, Drawdown halt) moved BELOW into a
  collapsed `CollapsibleSection` so they no longer wall off the page.
- **Spacing.** Section rhythm loosened (`mt-6 mb-2.5`) for breathing room on the
  dense mobile view.

## 2. Current system architecture

Frontend-only change, no new files. Data flow unchanged:

```
getAutotrade() ─┐
getDashboard()  ├─► AutoTradePage state ─► render
getPresetAvailability() ─┘
```

- `STRATEGY_PRESETS` (static const) gains `features: string[]` + `detail: string[]`
  per preset — descriptive copy mirroring verified late_entry_v3 / weather mechanics.
- New local UI state `expandedDetail: string | null` — single open detail panel.
- Feature chips render inside the existing activate `<button>`; the detail toggle
  is a `role="button"` span (stopPropagation) to avoid nested-button HTML and to
  keep a "details" tap from flipping the active preset.
- Detail panel + crypto config panel join visually under the card via
  `border-t-0` and conditional rounding (`showConfig || isDetailOpen`).
- Fine-tune controls wrapped in `CollapsibleSection id="autotrade_finetune_limits"`
  (persisted collapse state, same pattern as Market Filter).

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`

Created:
- `projects/polymarket/crusaderbot/reports/forge/auto-page-strategy-features.md`

## 4. What is working

- `npx tsc --noEmit` → exit 0 (clean).
- `npm run build` (tsc && vite build) → BUILD OK.
- Feature chips render for all 4 presets; toggle opens/closes one detail panel
  at a time; tapping "details" does not change the active preset.
- Profile picker renders before the collapsed fine-tune limits; banner + the
  three controls preserved verbatim, only relocated.

## 5. Known issues

- Feature chips are descriptive (capability), not live operator-toggle state.
  E.g. "↔ Dual-leg arb" reflects the strategy's capability even if the
  `CLOSE_SWEEP_DUAL_LEG_ENABLED` Fly secret is OFF. Wiring real runtime state
  would require backend changes (preset-availability endpoint) — deferred.
- ESLint not runnable in-repo (project predates eslint v9 flat config); validation
  relied on tsc + vite build.

## 6. What is next

- WARP🔹CMD visual review on the mobile AUTO tab.
- Optional: extend `/api/web/autotrade/preset-availability` to emit per-feature
  runtime flags so chips can show live ON/OFF for operator-gated features.
