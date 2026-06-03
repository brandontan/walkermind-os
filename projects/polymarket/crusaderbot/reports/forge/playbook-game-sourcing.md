# WARP•R00T — Playbook: source today's game markets + single (0,72h] window

Branch: WARP/ROOT/playbook-game-sourcing
Trigger: owner — playbook opens ZERO positions/day (paper). Sequenced after the
weather lane (#1595, merged). "No fake data, ready 100% LIVE/PAPER."
Date: 2026-06-04 Asia/Jakarta

## 0. Diagnosis (live-evidence: prod scan_runs + live Gamma)

- Prod `scan_runs`: `playbook:filter_or_no_match` — playbook ran, matched no market.
- Root causes (live Gamma confirmed):
  1. SOURCING — `get_events_with_markets` (Gamma `/events`) surfaces season FUTURES
     (NBA Champion, World Cup winner) whose event `startDate` is the *season* start
     (in the past) → negative TTL → excluded. Today's individual games never entered
     the window. Real near-term games (ATP 0.4h/$651k, Knicks-vs-Spurs 6.5h/$2.4M)
     live on Gamma `/markets` with `sportsMarketType` + per-game `gameStartTime`.
  2. RECOGNITION — those `/markets` game dicts carry `category=None`, and
     `_is_sports_category(None)` is False → every game market excluded at selection.
  3. WINDOW — the `(0,2h] ∪ (24,72h]` bands had a 2h–24h blind-spot.

## 1. What was built

- NEW `integrations/polymarket.get_sports_game_markets(limit=500)` — fetches Gamma
  `/markets` (volume-ranked), keeps only individual game markets (non-empty
  `sportsMarketType` + a `gameStartTime`), and annotates `category` from the parent
  event slug (e.g. `nba-nyk-sas-2026-06-03`). Cached 120s, fail-soft → [].
- NEW `_is_sports_market(market)` — recognises sports via, in order: the
  authoritative `sportsMarketType`, the tag-derived `category`, or the event slug.
  `select_sports_markets_in_window` now uses it (was category-token-only).
- SPORTS_CATEGORIES broadened (esports / competitions / tennis-majors slugs).
- WINDOW → single `(0, 72h]` (owner directive) — closes the 2h–24h gap so same-day
  games are ingested. Module routing (near = Closing-Edge ≤2h, far = Sharp-Money,
  flow-gated) is unchanged downstream.
- WIRING — both the strategy snapshot fetch (`PlaybookStrategy._fetch_sports_snapshots`)
  and the scan-job sync (`_sync_playbook_sports_markets`) now merge BOTH sources
  (game markets first, then `/events` futures), de-duped by market id, None/non-dict
  tolerant.

## 2. Current system architecture (relevant slice)

```
SOURCING (playbook):
  /markets  get_sports_game_markets  -> today's GAME markets (sportsMarketType,
                                         gameStartTime, category=event-slug)
  /events   get_events_with_markets  -> season FUTURES (tags -> category)
       merge (games first, dedup by market_id)
            v
  select_sports_markets_in_window:
       _is_sports_market(m)  (sportsMarketType | category | event-slug)
       AND  0 < ttl <= 72h     [single window]
            v
  _fetch_sports_snapshots:  near (<=2h) -> Closing-Edge ;  far (>2h, flow-gated) -> Sharp-Money
       real CLOB books via pm.get_book (already real — unchanged)
            v  RISK GATE (unchanged) -> EXECUTION (paper)
```

No change to the risk gate, Kelly, liquidity floor, module logic, or
`ENABLE_LIVE_TRADING`. Playbook already priced from the real CLOB book — this lane
fixes only which markets are *sourced/recognised/in-window*.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/integrations/polymarket.py (get_sports_game_markets)
- projects/polymarket/crusaderbot/domain/strategy/strategies/playbook.py (SPORTS_CATEGORIES;
  _is_sports_market; single-window select; merge both sources in _fetch_sports_snapshots)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
  (_sync_playbook_sports_markets merges both sources)
- projects/polymarket/crusaderbot/tests/test_playbook_engine.py (window + malformed updated)
- projects/polymarket/crusaderbot/tests/test_playbook_sharp_money.py (single-window test)
- projects/polymarket/crusaderbot/tests/test_signal_scan_job.py (sync test patches new source)

Created:
- projects/polymarket/crusaderbot/tests/test_playbook_sourcing.py
- projects/polymarket/crusaderbot/reports/forge/playbook-game-sourcing.md (this report)

## 4. What is working

- 148 tests pass (new playbook-sourcing + engine + sharp-money + signal-scan); ruff +
  py_compile clean. Proves: game markets with `category=None` + `sportsMarketType` are
  recognised + selected; the single `(0,72h]` window includes the old mid-band; futures
  with past start (negative TTL) and >72h markets stay excluded; merge is None/junk safe.

## 5. Known issues

- LIVE-VALIDATION PENDING (no dev DATABASE_URL): confirm on Fly paper that
  `_sync_playbook_sports_markets` upserts today's games and Closing-Edge (≤2h to
  tip-off) + Sharp-Money (≥24h) open real trades.
- BY-DESIGN mid-band gap: 2h–24h games are now SOURCED but no module ACTS there
  (Closing-Edge ≤2h, Sharp-Money ≥24h; Injury/Public are feed-dependent + OFF). So a
  game 6h out is ingested but won't trade until the Injury/Public feeds are enabled
  (needs ODDS_API_KEY + a market→event resolver — owner inputs, separate lane).
- Sports volume is event-driven — quiet windows legitimately yield few games (e.g.
  4 near-term games at diagnosis time). Real, not fake; expect bursty frequency.

## 6. What is next

- WARP•SENTINEL (MAJOR, money-path sourcing) or owner merge -> Fly redeploy ->
  paper-observe playbook opens (Closing-Edge near tip-off + Sharp-Money far band).
- Optional follow-up lane: enable Injury/Public feeds (ODDS_API_KEY + resolver) for
  2h–24h mid-band coverage.

---

Validation Tier   : MAJOR (strategy market sourcing — money path)
Claim Level       : FULL RUNTIME INTEGRATION (changes which markets playbook trades)
Validation Target : get_sports_game_markets; _is_sports_market recognition; single
                    (0,72h] window; both sourcing seams merge game + futures markets
Not in Scope      : Injury/Public feed enablement (mid-band); risk gate; CLOB pricing
                    (already real); weather (shipped #1595)
Suggested Next    : WARP•SENTINEL / owner merge -> Fly -> paper-observe -> (optional) feeds lane
