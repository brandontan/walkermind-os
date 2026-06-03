# WARP•FORGE — scanner-preset-name-coin-feed

Role: WARP•FORGE — three owner-reported dashboard scanner fixes (mobile screenshots).
Validation Tier: **STANDARD** (WebTrader display — scanner panel + market-feed scoping;
no risk / execution / capital / gate change)
Claim Level: **NARROW INTEGRATION**
Validation Target: the Home scanner panel reflects the user's strategy (display name),
the market feed shows the user's selected coins (BTC/ETH/SOL) in order, and the SIGNALS
carousel is always present.
Not in Scope: trading logic, risk gate, execution, preset activation/validation, the
top full-width MarketFeed strip (unchanged), DB migrations (none).
Suggested Next Step: WARP🔹CMD review/merge + Fly redeploy. Linear WARP-52.

---

## 1. What was built

Owner reported three gaps against the live dashboard (crusaderbot.fly.dev) vs the
design preview:

1. **Preset shows the raw key (`candle_auto`)** instead of the strategy name.
   `ScannerPanel` rendered `activePreset` verbatim. Added a `PRESET_LABEL` map
   (mirrors AutoTradePage `STRATEGY_PRESETS`) and a `presetLabel()` helper; the
   terminal `preset` line now prints `Smart Strike` / `Close Sweep` / `Safe Close` /
   `Flip Hunter` / `Weather Monitor` / `Playbook` (falls back to the raw key for any
   unknown preset).
2. **Market feed ignored the user's coin selection** — `_crypto_market_feed` listed a
   hardcoded universe (`btc/eth/sol/bnb/xrp/doge/hype`) regardless of the preset's
   `selected_assets`, so a user who picked BTC/ETH/SOL could still see a different/partial
   set. `get_market_feed` now reads `selected_assets` from `user_settings`, sanitises it
   against the tradable universe (`_sanitize_selected_assets`), and `_crypto_market_feed`
   scopes the query to exactly those assets (`= ANY($1)`) and returns them in the user's
   selection order. No selection → defaults to BTC/ETH (`_DEFAULT_CRYPTO_SHORT_ASSETS`).
3. **No signals carousel when the feed was empty** — `SignalCarousel` returned `null`
   when there were no recent publications, so the SIGNALS section vanished. It now renders
   a calm always-visible placeholder ("awaiting signal — scanning live markets…") so the
   carousel area is always discoverable; with data it animates/auto-advances as before.
   (`/signals/recent` is global over a 4h window, so this normally populates once deployed.)

## 2. Current system architecture

No architectural change. Two display surfaces touched: the React `ScannerPanel` component
(preset label + carousel empty state) and the read-only `/market-feed` endpoint (coin
scoping). The scan/risk/execution pipeline is untouched.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `_crypto_market_feed`
  now takes `assets` and scopes `= ANY($1)` + selection-order sort; `get_market_feed`
  reads + sanitises `selected_assets`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/ScannerPanel.tsx` —
  `PRESET_LABEL` + `presetLabel()`; preset terminal line; carousel empty-state placeholder
- `projects/polymarket/crusaderbot/tests/test_market_feed_preset.py` — +3 coin-scoping
  tests (scope / default / selection-order); fake conn now serves `selected_assets`
- `projects/polymarket/crusaderbot/reports/forge/scanner-preset-name-coin-feed.md` — this report
- State: `state/PROJECT_STATE.md` + `state/CHANGELOG.md`

## 4. What is working

- Backend: **124 tests pass** (test_market_feed_preset + test_signal_scan_job +
  test_bnb_monitor_only); `ruff` + `py_compile` clean. New tests pin: ANY($1) carries the
  user's lowercased selection; default BTC/ETH with no selection; feed returns selection order.
- Frontend: `tsc --noEmit` exit 0 + `vite build` clean.
- Preset label verified for all six presets; coin scoping verified to the tradable universe
  (BTC/ETH/SOL only — BNB/XRP/DOGE/HYPE never resurface even from legacy rows, via
  `_sanitize_selected_assets`); carousel always renders.

## 5. Known issues

- The live screenshot predated the #1575 Fly deploy, so fixes #1/#2 (and the #1574
  carousel) only appear after the deployed build refreshes. The carousel placeholder now
  guarantees the SIGNALS area is visible even in a quiet signal window.
- `PRESET_LABEL` is a small duplicate of the AutoTradePage names (the repo already
  duplicates preset maps per page); kept local to keep ScannerPanel self-contained.

## 6. What is next

- WARP🔹CMD review/merge + Fly redeploy.
- Optional: hoist a single shared preset-label source if more pages need it.

---

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: scanner preset name + selected-coin feed + always-on carousel
- Not in Scope: trading logic, risk/execution, preset activation, top MarketFeed strip
- Suggested Next Step: WARP🔹CMD review/merge + redeploy
