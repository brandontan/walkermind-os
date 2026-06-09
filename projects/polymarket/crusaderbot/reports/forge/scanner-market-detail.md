# WARP•R00T — scanner-market-detail

Branch: WARP/ROOT/scanner-market-detail
Date: 2026-06-04 00:31 WIB
Role: WARP•R00T (build lane)
Tier: STANDARD · Claim: NARROW INTEGRATION

Owner follow-up after WARP/ROOT/dashboard-ux deployed: the Playbook scanner now
shows the live sports board, but (1) every market row rendered the label "WILL",
and (2) there was no way to see which market a row referred to. Owner asks:
"playbook marketnya WILL semua" + "market bisa di-expand untuk lihat detail."

---

## 1. What was built

- **Fixed the "every row reads WILL" artifact.** The market `asset` code was the
  raw first slug token (`slug.split("-")[0]`). Every Polymarket question slugs as
  `will-the-<subject>-…`, so every row collapsed to "WILL". New
  `router._short_market_code(slug, question)` skips filler tokens (`will`, `the`,
  `win`, `beat`, …) and pure-digit year tokens, returning the first meaningful
  token uppercased — e.g. `will-the-lakers-beat-the-celtics-2026` → `LAKERS`. It
  falls back to the question, then `MKT`. Applied to both
  `_sports_market_feed_live` (Gamma) and `_category_market_feed` (DB). The market
  `label` cap was widened 48 → 80 chars so the expanded detail shows the full
  question.

- **Tap-to-expand market rows.** `ScannerPanel`'s `MarketRow` is now a button:
  tapping it reveals a detail panel with the full market question plus three
  cards — Probability, Closes-in, Liquidity. A chevron rotates to indicate state.
  Both render paths support it: a new `MarketStaticList` (≤5 markets) tracks the
  expanded row, and `MarketCarousel` (>5) tracks it too and **pauses
  auto-advance + the progress bar while a row is expanded** so the detail you are
  reading doesn't slide away. Expanding is reset on page change.

- **Top ticker hardening.** `MarketFeed` (the compact one-line ticker above the
  fold) now truncates long labels cleanly (`truncate min-w-0` instead of
  `shrink-0`, which overflowed on sports questions) and uses the human `Nd Hh` /
  `Hh Mm` countdown instead of the five-digit minute count.

## 2. Current system architecture (relevant slice)

```
GET /api/web/market-feed → _sports_market_feed_live / _category_market_feed
   each row's asset  = _short_market_code(slug, question)   (NEW — was slug[0])
   each row's label  = question[:80]                        (was [:48])

ScannerPanel
  markets:
    feed ≤5  → <MarketStaticList>   tracks expandedIdx
    feed >5  → <MarketCarousel>     tracks expanded gi; auto-advance + progress
                                    bar HELD while expanded != null
    row      → <MarketRow expanded onToggle>
                 collapsed: code · lean · prob bar · % · countdown · liq · chevron
                 expanded:  full question + Probability/Closes-in/Liquidity cards

MarketFeed (top ticker) → label truncate-safe + human countdown
```

No trading/scan/risk/execution surface touched.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `_short_market_code` helper + `_SLUG_FILLER`; used in `_sports_market_feed_live` and `_category_market_feed`; label cap 48→80.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/ScannerPanel.tsx` — expandable `MarketRow`; `MarketStaticList`; `MarketCarousel` expand state + auto-advance/progress-bar pause.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/MarketFeed.tsx` — truncate-safe label + human `Nd Hh` countdown.
- `projects/polymarket/crusaderbot/tests/test_market_feed_preset.py` — `test_short_market_code` (4 cases incl. the WILL regression).

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `npx tsc --noEmit` — 0 errors · `npm run build` — clean.
- `ruff check` + `python -m py_compile` — clean.
- `pytest tests/test_market_feed_preset.py` — **21/21 pass** (17 prior + 4 new `_short_market_code` cases; the live-Gamma sports test still derives `NBA`/`NFL`).

## 5. Known issues

- Short code is heuristic (first meaningful slug token). For an unusual slug it may pick a less-ideal word, but the expanded full question is always the source of truth — and it can never regress to a column of identical "WILL" again.
- Display-only, as before — no change to what the bot scans/trades.
- Not exercised against live Gamma in-session (hermetic test only); confirm visually after Fly redeploy.

## 6. What is next

- WARP🔹CMD review + Fly.io redeploy.
- Visually confirm on `crusaderbot.fly.dev`: rows show varied codes (not all WILL); tapping a row expands to the full question + detail cards; the carousel holds while a row is open.

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : market-row asset code (`_short_market_code`) across both feeds; ScannerPanel tap-to-expand row + carousel pause-on-expand; MarketFeed ticker truncation + countdown.
Not in Scope      : trading/scan market-selection, risk gate, execution, Kelly, ENABLE_LIVE_TRADING; crypto/weather feed data sourcing; non-Home pages.
Suggested Next    : WARP🔹CMD review + Fly redeploy. (STANDARD — WARP•SENTINEL not required.)
