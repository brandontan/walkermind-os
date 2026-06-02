# Smart Strike Rule Picker — WebTrader AUTO page declutter

**Branch:** `WARP/smart-strike-rule-picker`
**Role:** WARP•FORGE
**Validation Tier:** STANDARD (user-facing UX; frontend-only, no trading core)
**Claim Level:** NARROW INTEGRATION

> Owner request: the AUTO page main view should show only the two strategy
> *families* — 🔥 Smart Strike and 🌤 Weather — with the three single candle
> rules (Close Sweep / Safe Close / Flip Hunter) moved into a manual "Rule"
> sub-picker inside Smart Strike, instead of four separate candle cards.

## 1. What was built

The WebTrader AUTO page Strategy Preset grid now renders only two top-level
cards — **Smart Strike** (the candle auto-router, `candle_auto`) and **Weather
Monitor**. The three single candle rules are no longer standalone cards; they
live inside the Smart Strike card as a 2×2 **Rule** sub-picker:

- 🔥 **Auto** (`candle_auto`) — the router picks the rule per candle stage (default)
- 🧹 **Close Sweep** (`close_sweep`)
- 🔒 **Safe Close** (`safe_close`)
- 🎯 **Flip Hunter** (`flip_hunter`)

Selecting any chip activates that preset through the existing
`activatePreset` flow (assets + timeframe forwarded for crypto-short presets).
The Smart Strike card shows as ACTIVE for any candle rule, and its subtitle
reflects the live choice — `Auto — picks the rule per candle stage` or
`Manual rule: 🧹 Close Sweep`. Clicking the card body selects the Auto default
but is a no-op once a rule is active, so it never clobbers a pinned rule.

## 2. Current system architecture

Pure presentational re-grouping in `AutoTradePage.tsx`. No backend change: all
five presets remain valid and selectable server-side
(`VISIBLE_PRESET_ORDER` / `activate_preset` untouched), so the single rules are
still first-class — only their placement in the UI changed. Two new local
constants drive the grouping: `TOP_LEVEL_PRESET_KEYS` (filters the grid) and
`SMART_STRIKE_RULES` (the sub-picker). The Smart Strike card's `isActive` is
computed across `CRYPTO_SHORT_PRESETS` so a pinned single rule still lights up
the family card and surfaces its assets/timeframe config.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx` (modified)
- `projects/polymarket/crusaderbot/reports/forge/smart-strike-rule-picker.md` (new)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (COMPLETED + NEXT PRIORITY)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append)

## 4. What is working

- `tsc --noEmit` exit 0; `vite build` clean.
- Top-level grid shows Smart Strike + Weather only.
- Rule sub-picker activates each candle preset; active rule highlighted;
  in-flight save shows `…` and disables the row (mirrors the card double-tap
  guard); admin-disabled rules render greyed + `off` and are unclickable.
- Operator global-disable + PAUSED (ADMIN) badge still resolve for the active
  family; the active preset always stays visible.

## 5. Known issues / scope boundaries

- **Frontend only.** No preset params, routing, risk gate, or execution change.
- **Telegram bot picker unchanged** — owner scoped this to the web terminal;
  the Telegram preset list still shows all five. A follow-up lane can mirror the
  grouping there if desired.
- `COMING_SOON_PRESETS` remains empty (no locked cards).

## 6. What is next

- Optional: mirror the same grouping in the Telegram preset picker
  (`bot/handlers/presets.py`) for surface parity.
- Unrelated epic continuation: complete-set-arb Lane 2 (PAPER two-leg execution).

---

- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** AUTO-page preset grid grouping + Smart Strike Rule sub-picker
- **Not in Scope:** backend preset registry, activation logic, risk/execution,
  Telegram preset picker
- **Suggested Next Step:** WARP🔹CMD review; then deploy to Fly to surface.
