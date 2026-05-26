# WARP•FORGE — Close Sweep asset options (HYPE/XRP/DOGE) + BTC-only default

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Close Sweep (late_entry_v3) asset selection — UI options, backend
validation/default, Home market feed. Plus diagnosis of the "only BTC/ETH open" report.
Not in Scope: risk fences (Kelly 0.25 / position / loss / drawdown — untouched), the
exit_watcher hold-time logic, live-trading guard, strategy entry-gate tuning.
Suggested Next Step: WARP🔹CMD review; deploy; confirm XRP/DOGE/HYPE appear as opt-in
chips with BTC the only one lit by default for a fresh selection.

## 1. What was built

- Added **HYPE, XRP, DOGE** as selectable assets for the Close Sweep / crypto-short
  presets (BTC, ETH, SOL, BNB already supported). All seven have live Polymarket
  `{coin}-updown-{tf}-{slot}` candle markets (verified live against Gamma).
- Changed the **default active selection to BTC only**. The four majors keep deep
  candle books; XRP/DOGE/HYPE books are thinner, so they are opt-in rather than on by
  default — this avoids the "selected but never fills" experience on low-liquidity
  tickers. Users with a saved `selected_assets` keep their existing choice.
- Surfaced the three new coins in the Home live candle-market feed.
- **Persisted `positions.market_question`** at open time (paper + live executors) and
  added a `COALESCE(m.question, p.market_question, …)` fallback in the WebTrader
  position read queries. The question text is already available on the signal at open
  time; it was simply dropped at the INSERT. Candle markets are ephemeral, so once the
  `markets` row is pruned the label JOIN would otherwise degrade to a raw hash — this
  makes Port / Activity / closed-position labels durable.

## 2. Current system architecture

UI (AutoTradePage) asset chips -> POST /autotrade/activate (validates against
`_VALID_ASSETS`, persists `user_settings.selected_assets`) -> late_entry_v3.scan reads
`selected_assets` -> `pm.get_crypto_window_markets(tf, assets)` builds per-coin candle
slugs -> `is_short_crypto_market` asset gate (eligibility.ASSET_ALIASES already had all
seven) -> CLOB book entry gate -> RISK -> paper execute. Pipeline unchanged; only the
offered/validated/default asset set widened.

## 3. Files created / modified

- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx
  (CRYPTO_ASSETS -> 7 coins; new CRYPTO_ASSETS_DEFAULT = ["BTC"]; default + fallbacks
  switched from all-assets to BTC-only)
- projects/polymarket/crusaderbot/webtrader/backend/router.py
  (`_CRYPTO_SHORT_ASSETS` -> 7 coins; new `_DEFAULT_CRYPTO_SHORT_ASSETS = ("BTC",)`
  empty-selection default; Home-feed coin filter + `asset_labels` extended)
- projects/polymarket/crusaderbot/reports/forge/close-sweep-asset-options.md (this report)

- projects/polymarket/crusaderbot/domain/execution/paper.py
  (INSERT INTO positions now writes market_question)
- projects/polymarket/crusaderbot/domain/execution/live.py
  (same INSERT change for the live executor)
- projects/polymarket/crusaderbot/webtrader/backend/router.py
  (4 position read queries: m.question -> COALESCE(m.question, p.market_question, …))

No change to integrations/polymarket.py line 213: the full_auto fallback intentionally
stays on the four deep-book majors when a user has no explicit selection.

## 4. What is working

- Backend `eligibility.ASSET_ALIASES` already maps xrp/doge/hype, so the asset gate
  passes for the new coins once selected.
- router.py syntax check passes.
- Gamma probe confirmed live 5m candle markets for all 7 coins.

## 5. Known issues

- **"Only BTC/ETH open" — diagnosis: NOT a missing-trades bug.** Per-user position
  audit (Supabase, all 4 late_entry_v3 users) shows every account trades all four
  majors: representative user 7e6fbd20 = BTC 101 / ETH 84 / **SOL 68** / BNB 9.
  SOL is ~26% of fills; BNB is ~3%. The live "open positions" view only shows the
  current candle window, and not every coin clears the entry gate every candle — so at
  any instant the user may see only BTC/ETH even though SOL fills regularly. BNB is
  genuinely starved by thin candle books (same reason XRP/DOGE/HYPE are opt-in).
- `positions.market_question` NULL-on-all-rows is now FIXED (see above). Historical
  rows stay NULL but still label correctly via the live `markets.question` JOIN; only
  rows opened after deploy carry the persisted fallback.
- Frontend `tsc` not run — no node_modules in this environment. Changes are type-safe
  (spreading a readonly string[] default).

## 6. What is next

- WARP🔹CMD review + deploy.
- Optional: lower the entry gate for thin-book coins, or decide whether
  `positions.market_question` should be persisted.
