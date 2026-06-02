# PLAYBOOK — Autonomous Sports-Market Orchestration Engine

**Status:** v1.0 DRAFT — design blueprint (Phase-1 FOUNDATION coded, paper-only)
**Version:** 1.0
**Last Updated:** 2026-06-02 21:15 Asia/Jakarta
**Owner:** Bayue Walker (Mr. Walker)
**Agent:** WARP•R00T
**Project Path:** `projects/polymarket/crusaderbot/`
**Authority:** This blueprint is target architecture intent. Code truth defines current
reality. AGENTS.md remains highest authority. Linear: WARP-53.

> **PLAYBOOK is not a strategy — it is a strategy *router*.** It is the sports
> equivalent of SMART STRIKE (`candle_auto`). Where SMART STRIKE auto-selects between
> Close Sweep / Safe Close / Flip Hunter per candle stage, PLAYBOOK continuously
> evaluates each sports market and routes capital to the highest expected-value sports
> module. Users never see internal routing — they see one ACTIVE engine and a "current
> module + confidence" readout.

---

## 0. Posture & scope reconciliation

- **Phase-1 claim level = FOUNDATION (paper-only).** The router shell, Market Quality
  Filter, native signal layer, the **Closing Edge** module, the `playbook` preset, and
  the WebTrader card are built, registered, unit-tested and *selectable*. They are
  **not yet wired into the live signal-scan cadence** — that runtime dispatch is a
  Phase-2 lane (mirrors the `weather_monitor`→`weather` precedent).
- **Hybrid data posture.** Phase-1 edge is **Polymarket-native only** (CLOB orderbook,
  line movement, on-chain sharp-wallet accumulation, liquidity, event TTL). External
  feeds (odds providers, injury/news) are designed as pluggable adapters behind the
  `SportsFeed` Protocol (`domain/playbook/feeds.py`) and default to `NullFeed`. Signals
  are tagged **native-now** vs **feed-dependent** throughout.
- **Hard caps are inherited, never weakened.** PLAYBOOK reuses the 13-step risk gate
  (`domain/risk/gate.py`) unchanged: fractional Kelly ≤ 0.25, max position ≤ 10%, daily
  loss ≥ −$2,000, drawdown halt ≤ 8%, `ENABLE_LIVE_TRADING` guard untouched.

---

## 1. Sports-market alpha analysis — where real edge exists

Polymarket sports markets are CLOB binary/multi-outcome contracts resolving on real
game outcomes. Unlike a sportsbook (which sets a vig-laden line you cannot beat without
a model), Polymarket is a **peer-to-peer order book**: edge comes from being faster or
better-informed than the *other traders in the book*, not from beating a bookmaker.
That reframes where alpha lives — it is microstructure + information-timing, not
handicapping per se.

### 1.1 Per-league characteristics

| League | Liquidity | Lifecycle | Sharp vs public | News sensitivity | Closing-line efficiency | Edge profile |
|---|---|---|---|---|---|---|
| **NFL** | Deepest (esp. playoffs/SB) | Long pre-game (days) → spiky in-play | Heavy sharp + heavy public | Very high (QB/skill injuries, weather) | Tight near close | Closing Edge + Injury Alpha |
| **NBA** | Deep, high event count | Pre-game thin → liquid day-of | Sharp on totals, public on stars | Extreme (load mgmt, late scratches) | Loose until lineups posted | **Injury Alpha** (lineup repricing lag) |
| **MLB** | Moderate | Daily volume, pitcher-driven | Sharp on pitching/weather | High (pitcher scratch, weather) | Moderate | Sharp Money + Closing Edge |
| **NHL** | Thin–moderate | Daily | Mostly sharp (low public) | Moderate (goalie confirm) | Loose (thin books) | Closing Edge (stale thin books) |
| **Soccer** | Deep on majors, thin on minor | Long pre-match → 90min in-play | Sharp on Asian-handicap logic, heavy public on big clubs | High (lineup ~1h pre-match) | Tight on majors, loose elsewhere | Public Fade + Injury Alpha |
| **UFC** | Spiky around cards | Long build → fast resolution | Sharp on dogs, public on favorites/names | Moderate (weight miss, withdrawal) | Loose (event-driven) | **Public Fade** (name-bias) + Underdog Value |
| **Tennis** | Thin–moderate | Tournament arcs | Sharp-dominated | High (retirement/injury in-match) | Loose | Sharp Money + Line Momentum |

### 1.2 Generalizable edge sources (ranked by persistence + Polymarket-nativeness)

1. **Closing-line value on slow-to-reprice books (native, durable).** Thin/medium
   Polymarket sports books often lag the true closing consensus. Entering the
   mispriced side as TTL→0, when the book has converged toward fair but a stale resting
   order or wide spread remains, captures closing-line value. Pure orderbook signal —
   **no external data required.** This is the Phase-1 MVP module.
2. **On-chain sharp-money accumulation (native).** Polymarket settles on Polygon;
   wallet flow is observable. Persistent one-sided accumulation by historically
   profitable wallets ahead of a move is an informed-flow signal. Native via the chain
   monitor the bot already uses for copy-trade.
3. **Injury / news repricing lag (feed-dependent, highest single-event EV).** The
   window between a confirmed lineup/injury/scratch and the book repricing is where the
   largest discrete edge sits (esp. NBA load management, NFL QB, soccer lineups). Needs
   an external injury/news feed → V2.
4. **Public overreaction fade (feed-dependent).** Public piles onto popular teams/names
   (UFC favorites, big soccer clubs); fading the over-bet side when historical
   overreaction patterns hold is contrarian alpha. Needs a public-flow / consensus feed
   → V2.
5. **Line momentum & liquidity-hunt microstructure (native, V3).** Steam moves and
   resting-liquidity imbalances are exploitable but require CLOB WebSocket streaming
   (not yet present) for reliable signal → V3.

**Bottom line:** durable, Polymarket-native edge starts with **Closing Edge** and
**Sharp Money**; the highest discrete EV (**Injury Alpha**, **Public Fade**) is real but
feed-gated and therefore sequenced into V2.

---

## 2. PLAYBOOK architecture

Locked pipeline (every stage maps to an existing or thin-new component):

```
Sports Market
   │
   ▼
Market Quality Filter   ── domain/playbook/market_quality.py   (NEW, reuses slippage.py patterns)
   │  reject: low liquidity / wide spread / shallow depth / unclear resolution / event-integrity
   ▼
Signal Layer            ── domain/playbook/signals.py + feeds.py (NEW; native-now + NullFeed adapters)
   │  8 feeds → per-feed confidence ∈ [0,1] → weighted signal bundle
   ▼
Playbook Router         ── domain/playbook/router.py            (NEW; precedence-claim, dedup)
   │  walks routing matrix, selects ONE module + confidence
   ▼
Correlation Engine      ── domain/playbook/correlation.py       (NEW; event-level cluster key)
   │  tags candidate cluster_key → folds into existing exposure cap
   ▼
Risk Manager            ── domain/risk/gate.py                   (REUSED, unchanged — 13-step gate)
   │  Kelly 0.25 · max pos 10% · daily loss · drawdown · exposure · kill switch · dedup
   ▼
Execution Engine        ── domain/execution/router.py           (REUSED, unchanged — paper/live + 5 guards)
   │  exit watcher (domain/execution/exit_watcher.py) calls PlaybookStrategy.evaluate_exit
   ▼
Monitoring / Telegram   ── monitoring/alerts.py                 (REUSED)
```

PLAYBOOK adds **one** `BaseStrategy` subclass — `PlaybookStrategy` (`name="playbook"`) —
that internally owns the router + modules, exactly as `LateEntryV3Strategy` owns the
Close/Safe/Flip rules behind `candle_auto`. The strategy emits standard
`SignalCandidate`s; everything downstream (risk, execution, exits, monitoring) is the
existing production machinery.

---

## 3. Signal framework

Each feed produces a `SignalReading(value, confidence, source, native)` where
`confidence ∈ [0,1]`. The router consumes a weighted bundle. Native-now feeds are live
in Phase-1; feed-dependent feeds return a neutral reading until their adapter is wired.

| # | Feed | Formula (sketch) | Confidence basis | Phase-1 |
|---|---|---|---|---|
| 1 | **Line Movement** | Δmid over lookback window vs noise band: `(mid_t − mid_{t−k}) / σ_window` | magnitude vs σ, clamped [0,1] | **native-now** |
| 2 | **Sharp Money** | net signed size from profitable-wallet set / total flow | wallet-PNL weighting × imbalance | native-now (P1 stub→on-chain) |
| 3 | **Public Flow** | small-order count imbalance vs large-order flow | divergence magnitude | feed-dependent (V2) |
| 4 | **News / Injury** | event detected ∧ Δmid since event < expected repricing | recency × severity | feed-dependent (V2) |
| 5 | **Liquidity** | top-of-book depth + spread tightness | depth vs floor, spread vs cap | **native-now** |
| 6 | **Event TTL** | seconds to event start / resolution | bucketed (far / mid / near / closing) | **native-now** |
| 7 | **Historical Team Strength** | prior win-rate / Elo proxy vs implied prob | edge = model_p − implied_p | feed-dependent (V2) |
| 8 | **Market Sentiment** | order-flow skew + recent trade-side bias | skew magnitude | **native-now** |

**Weighting model.** Each module declares the feed weights it cares about; the router
computes a module-eligibility score `Σ wᵢ·confidenceᵢ` over that module's feed subset,
then applies the module's hard entry gates. Confidence surfaced to the UI is the
selected module's composite score, clamped [0,1]. Weights are config-tunable
(`config.py`) so they can be calibrated by the future backtest framework rather than
hand-set permanently.

---

## 4. Routing framework

The router walks modules in **precedence order** (highest-conviction / most discrete
edge first) and the **first module whose hard gates pass claims the market** — mirrors
`_CANDLE_AUTO_RULE_ORDER` precedence-claim + dedup. A market is claimed by at most one
module per scan, preventing duplicate exposure on the same event-side.

### Routing matrix

| Order | Module | Route IF (all true) | Edge source | Best sports | Phase-1 |
|---|---|---|---|---|---|
| 1 | **Injury Alpha** | injury/news event detected ∧ market not yet repriced ∧ TTL > 1h ∧ quality OK | repricing lag | NBA, NFL, Soccer | stub (V2) |
| 2 | **Sharp Money** | sharp-wallet accumulation ≥ θ ∧ TTL > 24h ∧ spread acceptable ∧ quality OK | informed flow | MLB, NHL, Tennis | stub (native, P1.5) |
| 3 | **Closing Edge** | TTL ≤ close-window ∧ book stale vs fair (mid-vs-resting gap) ∧ liquidity OK | closing-line value | NFL, NHL, NBA | **WIRED (MVP)** |
| 4 | **Public Fade** | public imbalance ≥ θ ∧ historical-overreaction pattern ∧ quality OK | contrarian | UFC, Soccer | stub (V2) |

Stubbed modules are present in the matrix and return no candidate (router falls through
to the next). This makes the router complete-by-design: enabling a module is wiring its
gate logic + feed, not re-architecting the router.

### Worked routing examples

```
IF sharp-wallet accumulation detected ∧ TTL > 24h ∧ spread acceptable
   → route Sharp Money

IF injury news detected ∧ market not repriced
   → route Injury Alpha

IF public betting imbalance ∧ historical overreaction
   → route Public Fade

ELSE IF TTL nearing close ∧ stale book ∧ liquidity OK
   → route Closing Edge   ← the always-available native fallback
```

---

## 5. Correlation engine

**Problem.** On one event, "Team A moneyline", "Team A series winner", and a correlated
player prop are largely the *same underlying risk*. Naive per-market sizing would
multiply exposure on one outcome.

**Design.**
- `cluster_key` — derived from the underlying event/team (e.g. `nba:2026-06-02:LAL@BOS`)
  attached to every `SignalCandidate` in `metadata`.
- **Correlation scoring** — candidates sharing a `cluster_key` get a correlation score;
  scores ≥ threshold are treated as one exposure unit.
- **Exposure clustering** — the engine annotates candidates so the existing risk-gate
  exposure check (`MAX_CORRELATED_EXPOSURE = 0.40` aggregate cap, gate step 8) covers
  correlated legs as a cluster, not independently. This layers *on top of* the gate
  rather than replacing it — the gate stays the authoritative enforcer.
- **Event-level cap** — a per-`cluster_key` sub-cap (config-tunable, default tighter
  than the aggregate cap) prevents over-concentration on a single game even when total
  exposure is within bounds.

This reuses the proven `paired_position_id` collapse precedent (complete-set arb) and
the aggregate exposure cap; it does not introduce a new risk authority.

---

## 6. Risk framework

Three profiles, all strictly bounded by the inherited hard caps. Preset values can only
**tighten**, never exceed, the system constants in `domain/risk/constants.py`; the gate
re-enforces at evaluation time.

| Profile | Capital % | TP % | SL % | Max position % | Daily loss | Drawdown halt | Kelly |
|---|---|---|---|---|---|---|---|
| **Conservative** | 20% | 15% | 8% | 3% | −$500 | 6% | 0.10 |
| **Balanced** | 40% | 25% | 12% | 6% | −$1,000 | 8% | 0.20 |
| **Aggressive** | 60% | 40% | 18% | 10% | −$2,000 | 8% | 0.25 |

Inherited, non-negotiable system caps (never overridden by PLAYBOOK):

| Rule | Value |
|---|---|
| Kelly fraction (a) | ≤ 0.25 — fractional only |
| Max position size | ≤ 10% of capital |
| Daily loss limit | −$2,000 hard stop |
| Drawdown circuit-breaker | > 8% → auto-halt |
| Correlated exposure cap | ≤ 40% aggregate (+ per-cluster sub-cap) |
| Signal dedup | per (market, side, price, size) + idempotency key |
| Kill switch | Telegram-accessible, immediate halt |

**Position sizing path:** module proposes `suggested_size_usdc` → correlation engine
clusters → risk gate applies fractional Kelly + position/exposure caps → final size.
**Holding duration** is per-module (Closing Edge: minutes to event close; Sharp Money:
hours-to-days; Injury Alpha: until repricing or event; Public Fade: to resolution).

---

## 7. UI blueprint

PLAYBOOK is surfaced exactly like SMART STRIKE — one card in the Auto-Trade preset
picker (`webtrader/frontend/src/pages/AutoTradePage.tsx`, `STRATEGY_PRESETS`). Users do
not see or configure internal routing.

```
┌──────────────────────────────────────────────┐
│ 🏟  PLAYBOOK                         [ ACTIVE ]│
│ Engine: W.A.R.P_PLAYBOOK                       │
│ Autonomous sports orchestration. Set-and-forget│
│                                                │
│ Tags:  ⚡ Auto rule-switch   📰 News-aware      │
│        🦈 Sharp-money aware  🎯 Market adaptive │
│                                                │
│ Current Active Module:  Closing Edge           │
│ Confidence:  0.81                              │
│                                                │
│ Risk badge: 🟡 Balanced                        │
└──────────────────────────────────────────────┘
```

- **ACTIVE / PAUSED (Admin)** state from the same `preset_globally_enabled` lookup
  weather/candle presets use (`webtrader/backend/router.py`, `_PRESET_TO_STRATEGY`).
- **Current Active Module + Confidence** read from the latest `SignalCandidate.metadata`
  (`selected_module`, `confidence`) emitted for the user — no new data source.
- Power-user sub-rule pinning (force a single module) is deferred to V2, mirroring the
  SMART STRIKE `SMART_STRIKE_RULES` pattern.

---

## 8. MVP design (Phase-1 — this PR)

**Scope:** router shell + Market Quality Filter + native signal layer + **Closing Edge**
module + `playbook` preset + WebTrader card, paper-mode, reusing the gate/execution.

New package `domain/playbook/`:

- `market_quality.py` — `MarketQualityResult` + pure-function checks (min liquidity,
  max spread, min depth, resolution clarity, event integrity). Reuses the
  `SlippageResult` / `check_market_impact` pattern from `domain/execution/slippage.py`.
- `signals.py` — `SignalReading` + native feed formulas (Line Movement, Liquidity,
  Event TTL, Market Sentiment, Sharp Money proxy) + weighting model. Feed-dependent
  feeds return neutral readings.
- `feeds.py` — `SportsFeed` Protocol + `NullFeed` default (native-only, no network).
- `correlation.py` — `cluster_key` derivation + correlation scoring + exposure
  clustering annotation.
- `router.py` — `PlaybookRouter`: precedence-claim walk over the routing matrix → one
  module + confidence.
- `modules.py` — `PlaybookModule` base + `ClosingEdgeModule` (full impl) + declared
  stubs `SharpMoneyModule` / `PublicFadeModule` / `InjuryAlphaModule`.

Strategy + wiring:

- `domain/strategy/strategies/playbook.py` — `PlaybookStrategy(BaseStrategy)`:
  `name="playbook"`, `version="1.0.0"`,
  `risk_profile_compatibility=["conservative","balanced","aggressive","custom"]`.
  `scan()` applies a sports eligibility filter (sports category — NOT
  `is_short_crypto_market`), runs Market Quality Filter → signals → router → emits
  `SignalCandidate`s. `evaluate_exit()` per-module (Closing Edge: TTL/price two-stage,
  mirroring `LateEntryV3Strategy`). `default_tp_sl()=(0.25,0.12)`.
- Export in `domain/strategy/strategies/__init__.py`; register in
  `domain/strategy/registry.py` `bootstrap_default_strategies` tuple (idempotent).
- `domain/preset/presets.py` — add `playbook` preset (`strategies=("playbook",)`,
  Balanced badge, tp/sl/max_position within validated bounds) + `PRESET_ORDER` /
  `VISIBLE_PRESET_ORDER`.
- `webtrader/backend/router.py` — `_PRESET_TO_STRATEGY["playbook"]="playbook"`.
- `AutoTradePage.tsx` — Playbook preset card.

**Explicitly NOT in Phase-1:** live scan-loop runtime dispatch (Phase-2), external feed
implementations, backtest engine, Monte Carlo, CLOB WebSocket.

**Tests:** registry registers `playbook`; preset validates at import; Market Quality
Filter accept/reject; router precedence/dedup; Closing Edge entry/exit; candidate shape.

---

## 9. V2 roadmap

- **Live runtime dispatch** — wire `playbook` into the signal-scan cadence
  (`services/signal_scan/signal_scan_job.py`), following the `weather` dispatch path.
- **Sharp Money module (full)** — promote the on-chain sharp-wallet accumulation signal
  from proxy to live, reusing the copy-trade chain monitor.
- **External feed adapters** — implement `SportsFeed` for an odds provider + an
  injury/news feed (requires network allowlist + API keys).
- **Injury Alpha + Public Fade modules** — enable now that their feeds exist.
- **Underdog Value + News Shock** — additional modules in the matrix.
- **Backtest framework** — walk-forward validation + leakage/overfit/selection-bias
  detection (shared blocker; also unblocks candle-preset validation).

---

## 10. V3 roadmap

- **Line Momentum + Liquidity Hunt modules** — microstructure edge.
- **CLOB WebSocket streaming** — real-time orderbook feed (removes polling latency;
  prerequisite for reliable momentum / liquidity-hunt signals).
- **Monte Carlo robustness framework** — ruin / drawdown / losing-streak probability →
  per-module robustness classification (ROBUST / FRAGILE / UNTRADEABLE).
- **Power-user module pinning** in the UI (force a single module).

---

## 11. Highest-EV implementation plan (ROI-ranked lane sequence)

1. **Phase-1 FOUNDATION (this PR)** — router + Market Quality Filter + native signals +
   Closing Edge + preset + UI. Lowest risk, ships the spine. *Done criteria: tests green,
   selectable, SENTINEL-validated.*
2. **Phase-2a — live dispatch** — wire into scan loop (paper). Highest ROI: makes the
   spine actually trade. Validate closing-line capture in paper.
3. **Phase-2b — Sharp Money (native)** — on-chain accumulation; no external dependency,
   high persistence.
4. **Phase-2c — Backtest framework** — unblocks +EV proof for PLAYBOOK *and* candle
   presets (flagged F-1 critical in strategic-alpha-research.md).
5. **Phase-2d — Injury Alpha** (after injury feed) — highest discrete single-event EV.
6. **Phase-2e — Public Fade** (after public-flow feed).
7. **Phase-3 — Line Momentum / Liquidity Hunt + WebSocket + Monte Carlo classifier.**

Rationale: ship the native spine first (cheap, durable edge), prove it in paper, then
spend integration budget on the feed-gated modules that carry the largest discrete EV.

---

## 12. Backtest & Monte Carlo framework specs (design — V2 build)

### 12.1 Backtest framework

- **Replay engine** — reconstruct historical sports-market orderbook snapshots + event
  timelines; feed them through the *same* signal → router → gate path used live (no
  parallel logic — prevents sim/live drift).
- **Walk-forward validation** — rolling train/validate windows; parameters fit on past,
  evaluated out-of-sample only.
- **Metrics** — win rate, EV per trade, **Sharpe**, **Sortino**, **profit factor**,
  **max drawdown**, average holding duration, per-module + per-league breakdown.
- **Bias detection** — (a) **data leakage**: assert no post-event data reaches an
  entry decision (resolution timestamp guard); (b) **overfitting**: out-of-sample
  degradation threshold vs in-sample; (c) **selection bias**: full-universe inclusion,
  no cherry-picked markets.

### 12.2 Monte Carlo framework

- Resample per-module trade-outcome distributions to estimate **losing-streak
  probability**, **drawdown-depth probability**, and **risk-of-ruin** at each risk
  profile's sizing.
- **Robustness classification:**
  - **ROBUST** — ruin probability negligible, drawdown within profile circuit-breaker,
    positive EV stable across resamples.
  - **FRAGILE** — positive EV but tail drawdown approaches the 8% halt, or streak risk
    high; size down / restrict.
  - **UNTRADEABLE** — non-positive EV out-of-sample or unacceptable ruin probability;
    module disabled.

A module must be classified at least **FRAGILE (sized down)** before it is eligible for
live capital; **UNTRADEABLE** modules stay paper-only.

---

## 13. File map (Phase-1)

| Action | Path (under `projects/polymarket/crusaderbot/` unless `docs/`) |
|---|---|
| create | `docs/blueprint/playbook.md` (this file) |
| create | `domain/playbook/{__init__,market_quality,signals,feeds,correlation,router,modules}.py` |
| create | `domain/strategy/strategies/playbook.py` |
| edit | `domain/strategy/strategies/__init__.py` (export) |
| edit | `domain/strategy/registry.py` (bootstrap tuple) |
| edit | `domain/preset/presets.py` (playbook preset + orders) |
| edit | `webtrader/backend/router.py` (`_PRESET_TO_STRATEGY`) |
| edit | `webtrader/frontend/src/pages/AutoTradePage.tsx` (preset card) |
| create | `tests/test_playbook_*.py` |

---

*End of PLAYBOOK blueprint v1.0. Phase-1 is FOUNDATION; subsequent phases per §9–§11.*
