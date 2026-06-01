# Strategic Alpha Research — CrusaderBot

**Role:** WARP•R00T (Principal Quant Researcher / Alpha Discovery)
**Issue:** WARP-51 — Strategic Alpha Research
**Branch:** `WARP/ROOT/strategic-alpha-research`
**Validation Tier:** MINOR (research / non-runtime — no code changed)
**Claim Level:** FOUNDATION (analysis grounded in code truth; no runtime integration)
**Constraint compliance:** No code written. No performance numbers invented. Every
mechanism cited to `file:line`. Where a quantity is unknowable without a backtest,
it is marked `UNMEASURED` rather than estimated.

> **Method.** Reverse-engineered the live pipeline
> `DATA → SIGNAL → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING`
> directly from source under `projects/polymarket/crusaderbot/`. Where the
> blueprint and code disagree, **code wins** (per `docs/blueprint/crusaderbot.md` §0.0).

---

## EXECUTIVE SUMMARY (read this first)

CrusaderBot is a **multi-user autonomous Polymarket trader** (PAPER in production;
LIVE behind 5 default-off activation guards). The trading core is sound *as
engineering* — a 15-step hard-wired risk gate, fail-closed kill switch, paper
default at the schema layer. The **alpha**, however, is the weakest link.

Five findings dominate everything below, ranked by expected-value impact:

| # | Finding | Severity | Evidence |
|---|---|---|---|
| F-1 | **No backtest / walk-forward / Monte-Carlo framework exists at all.** Every strategy parameter is tuned by imitating a reference bot ("Kreo") + short prod observation. There is no out-of-sample proof any candle strategy is +EV. | CRITICAL | exhaustive search: no `*backtest*`/`*replay*`/`*walkforward*` module; `late_entry_v3.py:1-7` cites `polybot_4coin`/Kreo as the edge source |
| F-2 | **The candle strategies have no probability model.** `confidence = ask_diff` — the *price gap*, not a calibrated win-probability. The system rides the CLOB's implied favorite on faith. | CRITICAL | `late_entry_v3.py:649` |
| F-3 | **The complete-set mispricing edge (`1 − (yes_ask+no_ask)`) is wired only as a config-disabled *defensive* filter, and is never harvested as a positive arbitrage.** `_gate_complete_set_edge` exists and is wired into `_process_candidate`, but is currently inert (`MIN_COMPLETE_SET_EDGE = 0.0` → early-return); and even when enabled it only *rejects* overpriced directional entries — no path *buys* the set when cost < $1.00. | HIGH | `late_entry_v3.py:606`, `signal_scan_job.py:1798-1856`, `config.py:559` |
| F-4 | **Execution edge is being destroyed at fill.** Prod 24h: only ~5.5% of `safe_close` and ~17% of `close_sweep` fills landed inside the intended price band (a TOB-freshness + fill-band guard was added in response). Candle books are thin in the final 35s. | HIGH | WORKTODO "late-entry fill-drift guard"; `late_entry_v3.py:704-708`; gate 3c |
| F-5 | **The richest intelligence is unharvested.** Wallet-360 metrics (Sharpe, win-rate, sybil flag — Falcon agent 581) are *fetched* but copy-trade uses a hardcoded `0.75` confidence and does not gate on leader quality. | HIGH | `copy_trade.py:40`; `services/copy_trade/wallet_360.py:96-174` |

**The single highest-EV move is not a new strategy — it is building the backtest /
calibration harness (F-1).** The trade data substrate already exists: every paper
trade is persisted with full entry metadata and resolved outcome
(`domain/execution/paper.py:22-102`, `positions`/`orders`/`fills` tables). The
framework to learn from it is the only missing piece, and it unblocks F-2, F-4 and
all strategy validation below.

The single most defensible *existing* edge is **weather** — it is the only strategy
with a real probabilistic model (normal-CDF bucket probability, EV `(p−price)/price`,
fractional Kelly α=0.25, σ-calibration from realized MAE).

---

## PHASE 1 — STRATEGY DECOMPOSITION

### 1.1 Current strategy architecture

Four strategies are registered at boot (`domain/strategy/registry.py:162-171`):
`copy_trade`, `signal_following`, `late_entry_v3`, `weather`. A fifth, `value`, is a
dead stub (`domain/signal/value.py:7` returns `[]`).

Four user-facing presets (`domain/preset/presets.py:101-156`), three of which route to
the **same** engine:

| Preset | Engine | Window / mode | TP | SL | max pos |
|---|---|---|---|---|---|
| `close_sweep` | `late_entry_v3` | final 35s, favored side, time-decay sizing | 0.90 | 0.40 | 5% |
| `safe_close` | `late_entry_v3` | final 60s, skip last 30s, force-exit rem=30s | 0.80 | 0.35 | 5% |
| `flip_hunter` | `late_entry_v3` | early window, **underdog** side, hold-to-settle | 1.50 | 0.50 | 5% |
| `weather_monitor` | `weather` | daily temp buckets, 20 cities | 0.25 | 0.20 | 5% |

`copy_trade` and `signal_following` are **not preset-mapped** to the candle presets;
they run as independent gate-coupled paths (`services/copy_trade/monitor.py`,
`services/signal_feed/signal_evaluator.py`).

### 1.2 Existing signal families (code truth)

| Family | Edge thesis (as stated in code) | Confidence model | File |
|---|---|---|---|
| `late_entry_v3` | Ride the CLOB-implied favorite in the final seconds of a BTC/ETH/SOL up/down candle; bail on flip. Explicitly a **mirror of reference bot Kreo / polybot_4coin**. | `ask_diff` ∈ [0,1] — *not a probability* | `late_entry_v3.py:1-7,649` |
| `weather` | Ensemble forecast (ECMWF+HRRR+METAR+VisualCrossing) prices a temperature bucket better than the crowd near expiry. | `p_true` = Φ((hi−μ)/σ) − Φ((lo−μ)/σ), genuine | `weather.py:249-268`, `strategies/weather/math_utils.py:12-30` |
| `copy_trade` | Mirror profitable leader wallets, size-scaled, 2h freshness. | fixed `0.75` | `copy_trade.py:17,40` |
| `signal_following` | Execute operator-curated feed publications (fed by `market_signal_scanner` using Heisenberg agents 568/575/585). | publisher-claimed `payload.confidence` (default 0.6) | `signal_evaluator.py:55,177-188` |
| `value` | (Phase 7+ stub) | n/a — returns `[]` | `domain/signal/value.py:7` |

### 1.3 Signal weighting logic

**There is none.** Each strategy emits independent `SignalCandidate` objects. There is
no cross-strategy ensemble, no weighted vote, no confluence scoring, no
correlation-aware aggregation. Within a single strategy, `late_entry_v3` sorts by
confidence (`late_entry_v3.py:261`); `signal_following` diversifies by
`sha1(user_id:market_id)` (`signal_evaluator.py:341-361`). That is the entire
"weighting" system.

### 1.4 Position sizing logic

Two-stage. Strategy *suggests*; risk gate *resizes down*.

- Suggestion (`late_entry_v3.py:99-121`): `equity × capital_alloc_pct × 0.04`,
  clamped `[$1, ceiling]` (ceiling default $25, abs cap $500).
- Risk gate (`domain/risk/gate.py:418-427`):
  `final = min(proposed, balance × max_pos_pct × kelly)` with `kelly = min(profile, 0.25)`.
- Weather sizes itself via fractional Kelly `α=0.25` (`math_utils.py:33-55`).

Capital pool by profile (`presets.py:80-94`): conservative 20% / balanced 40% /
aggressive 60% of equity.

### 1.5 Risk controls (hard-wired, `domain/risk/constants.py`)

`KELLY_FRACTION=0.25`, `MAX_POSITION_PCT=0.10`, `MAX_CORRELATED_EXPOSURE=0.40`,
`DAILY_LOSS_HARD_STOP=-2000`, `MAX_DRAWDOWN_HALT=0.08`, `MIN_LIQUIDITY=10000`,
`MIN_EDGE_BPS=200`, `SIGNAL_STALE_SECONDS=14400`, `DEDUP_WINDOW_SECONDS=300`,
`MAX_MARKET_IMPACT_PCT=0.05`, `SLIPPAGE_GUARD_PCT=0.05`. Enforced through a 15-step
gate (steps 0-14, `gate.py:244-482`). This layer is genuinely strong.

### 1.6 Entry / 1.7 Exit / 1.8 Confidence / 1.9 Capital — summarized

Entry: per-strategy `scan()` → ~15 pre-gates in `signal_scan_job._process_candidate`
→ 15-step risk gate → execution queue. Exit: priority chain in
`exit_watcher` (force-close → TP → SL → `strategy.evaluate_exit` → hold). Confidence:
see 1.2 (only weather is a real probability). Capital: see 1.4.

### 1.10 Strategy map / Edge map / Failure map

**Strategy map** (what actually trades):
```
BTC/ETH/SOL 5m+15m up/down candles ──► late_entry_v3 ──► close_sweep / safe_close / flip_hunter
Daily temp buckets (20 cities)     ──► weather       ──► weather_monitor
Leader wallets (Data API + 360)    ──► copy_trade    ──► (independent monitor)
Operator feed (scanner+Heisenberg) ──► signal_following ──► (independent evaluator)
```

**Edge map** (does a defensible edge exist?):

| Strategy | Claimed edge | Defensible? | Why |
|---|---|---|---|
| weather | informational (forecast > crowd near expiry) | **YES** | real model + calibration + +EV gate |
| complete-set arb (latent) | structural (cost < $1.00) | **YES, if fillable** | computed; only feeds a disabled rejection filter, never bought (`:606`) |
| copy_trade | behavioral (follow smart money) | **CONDITIONAL** | only if leader-quality gated; currently not |
| signal_following | informational (operator + Heisenberg) | **UNVALIDATED** | publisher-claimed confidence, uncalibrated |
| late_entry_v3 | momentum/persistence of late favorite | **UNPROVEN** | no probability model, no backtest, fill-drift |

**Failure map**:

| Failure mode | Where it bites | Evidence |
|---|---|---|
| Overfit to one reference bot | all candle presets | thesis = "mirror Kreo" (`late_entry_v3.py:1-7`); no OOS test |
| No probability calibration | candle confidence | `confidence = ask_diff` (`:649`) |
| Exposure cap is correlation-blind (global sum) | exposure gate | step 8 sums ALL open positions globally (`_open_exposure`, `gate.py:106-113,363`) vs a single cap — conservative for concentration, but cannot credit genuinely independent sleeves (weather vs candle) |
| Execution-edge destruction | thin final-35s books | fill-drift 5.5%/17% in-band (WORKTODO) |
| Latency | scan→fill drift | TOB-freshness gate `TOB_STALE_MS=2000` (`signal_scan_job.py:1749-1795`) |
| Structural edge not harvested | complete-set | `:606` feeds only a config-disabled rejection filter (`MIN_COMPLETE_SET_EDGE=0.0`); never bought as arb |
| Regime blindness | momentum in chop | no regime detector anywhere |

---

## PHASE 2 — EDGE DETECTION

Edges that *can exist* in prediction markets, mapped to **data this system already
has** (no new infra invented).

### 2.1 Inefficiencies, by class

- **Behavioral.** Favorite-longshot bias (longshots overpriced). The scanner already
  removed its own longshot bias (WORKTODO LANE-3 "edge-model-momentum"). Residual
  behavioral edge lives in *over-reaction* to recent candle moves near expiry —
  exploitable only with a calibrated model (which does not exist yet → F-2).
- **Market structure.** Complete-set mispricing: UP+DOWN settle to exactly $1.00, so
  `yes_ask + no_ask < 1.00` is a riskless taker edge when depth allows. The metric is
  **computed** (`late_entry_v3.py:606`) and feeds a *defensive* rejection filter
  (`_gate_complete_set_edge`) that is currently config-disabled (`MIN_COMPLETE_SET_EDGE
  = 0.0`); it is **never harvested as a positive arbitrage**. That harvest is the
  cleanest unexploited edge in the repo.
- **Resolution.** Weather buckets resolve on objective NWS data; an ensemble forecast
  (4 sources) genuinely beats the crowd as expiry approaches and the forecast
  converges. This is the system's strongest *informational* edge and it is already
  modeled (`weather.py`, `math_utils.py`).
- **Liquidity.** Final-35s candle books thin out (MMs withdraw). This *destroys* the
  late_entry taker edge (F-4) but *creates* a maker/complete-set edge for whoever
  provides liquidity at fair value.
- **Cross-market.** Same-underlying candle correlation is currently invisible to the
  exposure gate; two BTC candle markets are one bet. Also: YES/NO complementarity is
  the complete-set edge above.

### 2.2 Five new alpha concepts

| # | Concept | Why edge exists | Why others miss it | Harvest | Risk | Scalability |
|---|---|---|---|---|---|---|
| A1 | **Weather ensemble convergence** (scale the existing model) | NWS-objective resolution + 4-source forecast skill the retail crowd lacks | retail can't run ECMWF+HRRR+METAR ensembles or calibrate σ from realized error | extend city coverage; tighten σ-calibration; size on EV | model risk (bad forecast), low liquidity per market | **wide** (many cities × days), but per-market size-capped |
| A2 | **Complete-set liquidity arb** | $1.00 settlement bound makes `cost<1` riskless | books are shallow at the quote; needs depth-aware sizing most bots skip | add a *harvest* path that buys the set when `cost<1` (the existing `_gate_complete_set_edge` only rejects; it never buys) + depth-aware sizing | execution risk (partial fill of one leg) | thin (rare, size-bound) but **pure** |
| A3 | **Wallet-360-gated copy** | smart-money persistence; sybil/over-fit leaders filtered out | the data (Sharpe, win-rate, sybil flag) is expensive to compute; this system already pays for it (agent 581) and then ignores it | replace fixed 0.75 with a quality-weighted confidence + hard sybil/Sharpe gate | leader regime change, crowding | **medium** (leader-bound) |
| A4 | **Calibrated late-favorite** | IF the late favorite wins more than its price implies, ride it; IF not, fade it — *empirically decided* | everyone guesses; nobody calibrates P(win\|price,secs,asset) from their own outcomes | build calibration table from the bot's own resolved trades → replace `ask_diff` | regime drift; needs continuous recalibration | **high** (every candle) |
| A5 | **Social-pulse / candlestick confluence** (Heisenberg 585+568) | sentiment + momentum confluence on event markets | data is wired (`market_signal_scanner.py`) but confidence is uncalibrated to realized hit-rate | calibrate feed confidence to outcomes; require confluence not single-agent | sentiment noise, reflexivity | **medium** |

### 2.3 Three high-conviction opportunities

1. **A1 Weather** — only existing model-driven edge; extend, don't reinvent.
2. **A2 Complete-set arb** — structural, riskless-when-fillable, already 90% computed.
3. **A3 Wallet-360 copy** — turns a sunk data cost (agent 581) into a real filter.

### 2.4 Highest-EV strategy

**A1 + the F-1 harness.** Weather is the only edge with a defensible, repeatable,
model-backed +EV claim. But its EV is **UNMEASURED** without a backtest. Therefore the
highest-EV *action* is: build the calibration/backtest harness (Phase 6), validate
weather first (its objective resolution data makes it the cleanest thing to backtest),
then scale capital into it. Everything else is speculation until the harness exists.

---

## PHASE 3 — MARKET REGIME DETECTION

No regime engine exists today. Design (conceptual — **no code per task constraint**),
using only data already ingested (Heisenberg 568 candlesticks, CLOB spread/depth,
realized vol from price history):

### 3.1 Regime taxonomy + recommended posture

| Regime | Detector (existing data) | Best strategy | Worst strategy | Risk × | Capital × | Confidence adj |
|---|---|---|---|---|---|---|
| Trending | realized return persistence > threshold over N candles | late-favorite (A4), copy | flip_hunter (underdog) | 1.0 | 1.0 | +0 |
| Mean-reverting | autocorrelation < 0, oscillation | flip_hunter, complete-set | late-favorite | 0.75 | 0.75 | −10% |
| Volatile | realized vol spike, spread widening | complete-set arb, weather | all directional candle | 0.5 | 0.5 | −25% |
| Stable / low-vol | tight spread, low realized vol | late-favorite, weather | flip_hunter | 1.0 | 1.0 | +0 |
| News-driven | Heisenberg social-pulse (585) spike | stand aside / weather | all candle | 0.5 | 0.25 | −30% |
| Liquidity-starved | CLOB depth < floor (already computed `_book_depth_usdc`) | **none — skip** | all taker | 0.0 | 0.0 | reject |

### 3.2 Dynamic switching framework

A regime classifier emits a label per (asset, timeframe) per tick → a policy table
(above) maps label → {enabled strategies, risk multiplier, capital multiplier,
confidence delta}. The multipliers compose *on top of* the existing hard caps — they
can only tighten, never loosen (mirrors the existing "user can only restrict downward"
precedence rule, `constants.py:82-161`). Liquidity-starved → hard skip reuses the
existing `_book_depth_usdc` signal. This is the missing layer between SIGNAL and RISK.

---

## PHASE 4 — MULTI-FACTOR STRATEGY DESIGN

The system has **no composite score** today (Phase 1.3). A production factor model to
replace the single `ask_diff` confidence:

| Factor | Formula (from existing data) | Weight* | Signal quality | Failure condition |
|---|---|---|---|---|
| Momentum | sign+magnitude of N-candle return (Heisenberg 568) | 0.25 | medium | chop / reversal regime |
| Trend | persistence / Hurst-style autocorrelation | 0.15 | medium | regime flip |
| Volatility | realized vol vs baseline (inverse-weight size) | 0.10 | high (risk control) | vol regime shift |
| Liquidity | `_book_depth_usdc` both legs | 0.15 | high | stale book |
| Crowd sentiment | Heisenberg social-pulse 585 | 0.10 | low-medium | reflexivity / noise |
| News impact | sentiment spike detector | 0.05 | low | false positives |
| Resolution proximity | seconds_to_close (already computed) | 0.10 | high | — |
| MM behavior | spread + depth dynamics (bid/ask asymmetry) | 0.10 | medium | spoofing |

\* **Weights are illustrative priors, NOT fitted** — they must be learned by the F-1
harness (ridge/logistic regression on resolved outcomes) before use. Presenting them as
final would violate the no-invented-numbers rule.

**Composite Alpha Score** = calibrated `P(win)` from a model fit on these factors
against realized outcomes, *then* `EV = (P − price)/price` (reuse the weather EV form,
`math_utils.py:22-30`). Confidence calibration = reliability curve (predicted vs realized
hit-rate by bucket) — the same MAE→σ recalibration loop weather already runs
(`calibration.py:58`). This unifies the four ad-hoc confidence models into one
EV-comparable scale.

---

## PHASE 5 — STRATEGY GENERATION

Three strategies with **defensible edge** (no indicator spam). Each maps to an edge
identified in Phase 2 and is implementable on existing data.

### 5.1 Weather Ensemble Convergence (extends `weather`)
- **Logic:** as forecast convergence increases near expiry, the bucket probability
  sharpens; enter when model `p_true` materially exceeds market price and σ is
  well-calibrated.
- **Entry:** `EV=(p−price)/price ≥ min_ev` (existing gate, `weather.py:251`), σ from
  ≥30 resolved samples (`calibration.py`), hours-to-expiry ∈ [2,72].
- **Exit:** existing 5-exit ladder (stop, trailing breakeven, TP windows, forecast-shift,
  near-expiry) — already wired.
- **Risk/sizing:** fractional Kelly α=0.25 (existing).
- **Edge source:** informational (4-source ensemble vs crowd) + objective resolution.
- **Failure:** model error on extreme events; per-market liquidity caps size.
- **Scalability:** wide (cities × days); the most scalable defensible edge.

### 5.2 Complete-Set Liquidity Arb (new, from latent metric)
- **Logic:** when `yes_ask + no_ask < 1.00 − costs` AND both legs have depth, buy the
  set for a locked payout of $1.00.
- **Entry:** add a **harvest path** that buys the set when `cost < 1.00 − costs` with
  depth-aware max size (use `_book_depth_usdc` per leg). (The existing
  `_gate_complete_set_edge` is a *rejection* filter only — re-enable it for defense, but
  it does not place the arb.)
- **Exit:** hold to resolution (riskless).
- **Risk:** single-leg partial-fill (mitigate with FOK/atomic two-leg or post-only).
- **Edge source:** structural ($1.00 settlement bound).
- **Failure:** shallow books make it rarely fillable at size — accept low frequency.
- **Scalability:** thin but pure; capital-bound by book depth.

### 5.3 Calibrated Late-Favorite (replaces `ask_diff` faith)
- **Logic:** keep the late-entry *structure* but replace `confidence=ask_diff` with an
  empirical `P(win | fav_price, seconds_left, asset, regime)` lookup learned from the
  bot's own resolved candle trades; trade only when `P > price + edge_floor`.
- **Entry:** existing timing/spread/band gates **plus** calibrated-EV gate.
- **Exit:** existing flip-stop + fixed-time exits.
- **Risk/sizing:** Kelly on the *calibrated* edge, not on `ask_diff`.
- **Edge source:** behavioral persistence — *if and only if* the data confirms it; the
  calibration table is allowed to say "no edge, stand down."
- **Failure:** regime drift → mandatory rolling recalibration.
- **Scalability:** high (every candle), self-limiting via the EV gate.

---

## PHASE 6 — BACKTEST DESIGN (the critical gap)

**Code truth:** no backtest, simulation, walk-forward, or replay framework exists
(exhaustive search). The only validation is `ReadinessValidator` (structural dry-run,
`services/validation/readiness_validator.py`) and paper trading. This is the #1 alpha
risk: **no strategy parameter in the repo has out-of-sample support.**

**Key enabler:** the data substrate already exists. Every paper trade persists entry
metadata + resolved outcome (`paper.py:22-102`; `orders`/`positions`/`fills` tables;
candidate metadata carries `entry_price`, `fav_price`, `ask_diff`, `complete_set_edge`,
`seconds_to_close`, `entry_price_ts`). A harness only needs to *replay* this, not source
new data → **high ROI, low cost.**

### 6.1 Framework (design)
- **Walk-forward:** rolling train/validate windows; parameters fit on window *t*,
  evaluated on *t+1*; never peek forward.
- **Out-of-sample:** strict holdout of most-recent N days; report OOS metrics only.
- **Cross-regime:** bucket results by the Phase-3 regime label; require positive
  expectancy in ≥ the trending+stable regimes, neutral elsewhere.
- **Stress:** worst-case sequences (max consecutive losses), spread-widening shock.
- **Slippage simulation:** model fill at `best_ask + k·tick` and at the observed
  fill-drift distribution (the 5.5%/17% in-band data is the empirical prior).
- **Liquidity simulation:** cap fills at `_book_depth_usdc`; reject size > depth.

### 6.2 Required metrics
CAGR · Sharpe · Sortino · Win rate · Profit factor · Max drawdown · Recovery factor —
reported **OOS only**, per strategy and per regime.

### 6.3 Bias flags (must be enforced by the harness)
- **Data leakage:** never use post-entry info (e.g. final price) in the entry decision;
  freeze the orderbook snapshot at `entry_price_ts`.
- **Survivorship:** include markets that delisted / resolved void.
- **Overfitting:** penalize parameter count; prefer walk-forward stability over
  in-sample peak; the Kreo-imitation parameters are prime suspects.
- **Selection bias:** evaluate the full eligible universe, not the subset that traded.

---

## PHASE 7 — RISK / REWARD ANALYSIS

Grounded in actual constants (`domain/risk/constants.py`), not estimates.

- **Risk per trade:** bounded by `final = min(proposed, balance × max_pos_pct × 0.25)`
  and `max_position_pct ≤ 0.10` (`gate.py:418-427`). Per-trade risk is well-capped.
- **Portfolio risk:** capped by a **global** total-exposure limit — step 8 sums ALL open
  positions (`_open_exposure`, `gate.py:106-113,363`) against `effective_exposure_cap`
  (system 0.40, `constants.py:6`). This is *conservative* — it treats every position as
  fully correlated, so concentration is contained, not understated. The mild inefficiency
  is the inverse: it is correlation-blind and cannot credit genuinely independent sleeves
  (weather vs candle).
- **Drawdown:** `MAX_DRAWDOWN_HALT = 0.08` auto-halt (`gate.py:332-340`); daily loss
  hard stop −$2,000 + per-profile caps.
- **Tail risk:** the asymmetric payoff of late-favorite (buy ~0.50–0.70 to win $1.00 ≈
  +43–100% up vs −100% down) means **a sub-coinflip win-rate is ruinous**, and win-rate
  is UNMEASURED (F-2). This is the dominant tail exposure.

### 7.1 Three ways to reduce risk WITHOUT reducing edge
1. **Add a per-underlying concentration sub-limit** — the global exposure cap is
   correlation-blind, so a book can sit entirely in one underlying (e.g. BTC candles)
   within the 40% cap. An optional per-asset sub-cap trims correlated-cluster variance
   without shrinking any single winning trade.
2. **Re-enable the complete-set rejection filter** — set `MIN_COMPLETE_SET_EDGE > 0`
   (it is `0.0` today, so the wired filter is inert): rejecting `cost > 1.00` markets
   removes structurally-unwinnable taker entries (pure loss-avoidance, config-only, no
   edge given up).
3. **Liquidity-aware sizing on thin books** — cap size to `_book_depth_usdc` (already
   computed) so the final-35s slippage tax shrinks; this *recovers* edge lost to F-4.

### 7.2 Two ways to increase edge WITHOUT increasing risk
1. **Calibrated confidence (A4)** — replacing `ask_diff` with a learned `P(win)` raises
   EV per trade at identical position caps; the gate stays unchanged.
2. **Wallet-360 gating on copy (A3)** — filtering to high-Sharpe, non-sybil leaders
   raises copy hit-rate using data already paid for; risk caps untouched.

---

## PHASE 8 — MONTE CARLO ANALYSIS

**Constraint honored:** I cannot output probability-of-ruin numbers without a backtest —
doing so would be inventing performance. Instead I (a) specify the framework and (b)
classify each strategy by **structural evidence available today**.

### 8.1 Framework (design)
Bootstrap-resample the per-trade return distribution (from the F-1 harness) → simulate
many equity paths → report probability of ruin, probability of net loss over horizon,
worst drawdown distribution, recovery-duration distribution, and a return *range*
(percentile band, never a point estimate).

### 8.2 Structural classification (evidence-based, not numeric)

| Strategy | Class | Why |
|---|---|---|
| weather | **ROBUST-candidate** | real model + calibration + +EV gate + objective resolution; still UNMEASURED until backtested |
| complete-set arb | **ROBUST (if fillable)** | payoff bounded by $1.00 settlement; risk is execution, not thesis |
| copy_trade (current) | **FRAGILE** | fixed 0.75 confidence, no leader-quality gate; edge depends entirely on ungated leader selection |
| signal_following | **FRAGILE** | uncalibrated publisher confidence; edge unproven |
| late_entry_v3 (current) | **UNTRADEABLE-until-validated** | no probability model, fill-drift evidence of execution-edge loss, asymmetric tail, zero OOS support |

"UNTRADEABLE-until-validated" is a statement about *evidence*, not a claim the strategy
loses money — it means: do not scale LIVE capital into it before F-1 produces an OOS
win-rate that clears the price line.

---

## PHASE 9 — PORTFOLIO CONSTRUCTION

Design (qualitative — no invented allocation %s; final weights must come from F-1):

- **Treat the 3 candle presets as ONE correlated sleeve**, not three strategies. They
  share the engine, universe, and direction logic.
- **Diversify across edge *types*:** informational (weather), structural (complete-set),
  behavioral (copy/late-favorite). These have low mutual correlation by construction —
  the only genuine diversification available.
- **Weight by edge quality, not by count:** over-weight the model-driven/structural
  sleeves (weather, arb) which have defensible +EV; under-weight and cap the
  behavioral/unvalidated sleeves until backtested.
- **Liquidity ceiling per sleeve:** weather and arb are size-bound by per-market depth;
  do not allocate capital that cannot be deployed at fair value.
- **Portfolio drawdown estimate:** UNMEASURED — output a percentile band from the Monte
  Carlo (Phase 8) once the harness exists; the existing 8% auto-halt is the hard backstop.
- **Rebalancing:** recalibrate confidence models on the weather cadence (≥30 resolved
  samples, `calibration.py`); rebalance sleeve weights on the walk-forward window
  boundary; never intra-window (avoids chasing noise).

---

## PHASE 10 — TRADE SETUP GENERATION

**Constraint honored:** these are **mechanism illustrations** of how the live gates
evaluate an archetype — they are NOT historical results or predicted P&L. All prices are
illustrative variables.

### 10.1 Late-favorite archetype (close_sweep, 5m BTC)
- Path: `get_crypto_window_markets` → `is_short_crypto_market` true → seconds_left ≤ 35
  → both books fetched → best ask each leg → `ask_diff ≥ 0.05` → `spread ≤ 1.05` →
  `entry_price ∈ [0.50, 0.70)` → `confidence = ask_diff` → suggested size (time-decay
  ×0.75 in 10–35s) → 15-step risk gate → queue.
- Exit: flip-stop if favored price ≤ flip-stop, else TP 0.90 / SL 0.40, else force-exit
  ~8s before close. **EV is UNMEASURED** — the setup is only +EV if `P(win) > entry_price`,
  which the system does not currently know (F-2).

### 10.2 Weather archetype (weather_monitor)
- Path: ensemble Tmax (4 sources) → σ from calibration → `p_true = Φ((hi−μ)/σ)−Φ((lo−μ)/σ)`
  → `EV = (p_true − price)/price ≥ min_ev (0.10)` → volume/spread/price/hours gates →
  Kelly size (α=0.25) → risk gate. Exit: 5-exit ladder. This is the only archetype where
  the entry decision is driven by a **computed edge**, not a price gap.

### 10.3 Complete-set archetype (proposed A2)
- Path: both legs' best asks → `cost = yes_ask + no_ask` → if `1.00 − cost > fees` AND
  depth ≥ size on both legs → buy set → hold to $1.00 resolution. Technical reasoning:
  $1.00 settlement bound. Market-structure reasoning: shallow books make this rare but
  riskless when present.

Macro reasoning for all three: intraday crypto candles and daily weather are
**macro-insensitive** (see Phase 11).

---

## PHASE 11 — MACRO INTELLIGENCE

**When macro matters:** longer-horizon *event* markets — elections, rate decisions,
geopolitical/regulatory resolutions. These are Polymarket's signature markets and are
*driven* by macro data.

**When macro is noise:** the markets CrusaderBot actually trades today — 5m/15m crypto
up/down candles (microstructure-driven, macro-irrelevant intraday) and daily
temperature buckets (driven by meteorology, not rates/inflation).

**Recommendation:** do **not** bolt macro feeds onto the current candle/weather engine —
it would add noise to macro-insensitive markets. Macro intelligence becomes relevant
**only if** the roster expands to event markets (currently out of scope; copy/signal
paths could already touch them, in which case Heisenberg social-pulse (585) is the
right, already-wired, signal). Until then: macro = noise; ignore it. This avoids a
common false-edge trap (importing macro context into markets it cannot move).

---

## PHASE 12 — STRATEGY OPTIMIZATION

| Strategy | Current | Improved | Trade-off |
|---|---|---|---|
| late_entry_v3 | `confidence = ask_diff`; complete-set filter config-disabled + not harvested; no per-asset concentration sub-limit | calibrated `P(win)` (A4); per-asset concentration sub-limit; re-enable filter + add arb-harvest path | needs F-1 harness first; more compute per scan |
| copy_trade | fixed 0.75; no leader gate | Wallet-360 quality-weighted confidence + sybil/Sharpe hard gate (A3) | fewer leaders pass → lower frequency, higher quality |
| signal_following | publisher-claimed confidence | calibrate confidence to realized feed hit-rate; require Heisenberg confluence | needs outcome history; slower feed activation |
| weather | already model-driven | scale cities; tighten σ; size on EV percentile | more API calls; per-market liquidity cap |
| portfolio | no cross-strategy logic | regime-switched, edge-quality-weighted sleeves | adds the missing regime + portfolio layers |

Goal mapping: Sharpe↑ via calibration + diversification; drawdown↓ via correlation-key
fix + liquidity-aware sizing; robustness↑ via the backtest harness; consistency↑ via
regime switching.

---

## FINAL DELIVERABLE

### 1. Strategy audit
4 live strategies + 1 dead stub. Strong risk engine; weak alpha. 3 candle presets share
one un-modeled engine; weather is the only calibrated model; copy/signal are
uncalibrated. No cross-signal weighting, no regime layer, no backtest.

### 2. Edge analysis
One defensible informational edge (weather), one latent structural edge (complete-set,
unharvested), one conditional behavioral edge (copy, if quality-gated). The candle
late-favorite edge is **unproven** (no probability model, no OOS).

### 3. Market regime framework
Designed (Phase 3): 6 regimes from existing data; policy table tightens risk/capital and
hard-skips liquidity-starved markets. Missing layer between SIGNAL and RISK.

### 4. New alpha opportunities
A1 weather convergence · A2 complete-set arb · A3 wallet-360 copy · A4 calibrated
late-favorite · A5 social/candlestick confluence.

### 5. New strategy proposals
5.1 Weather Ensemble Convergence · 5.2 Complete-Set Liquidity Arb · 5.3 Calibrated
Late-Favorite (full logic/entry/exit/risk/edge/failure/scalability in Phase 5).

### 6. Risk analysis
Per-trade risk well-capped; portfolio exposure capped **globally** (conservative,
correlation-blind); asymmetric late-favorite tail is the dominant exposure. 3 risk-reductions + 2
edge-increases that don't trade off (Phase 7).

### 7. Monte Carlo framework
Bootstrap equity-path simulation designed (Phase 8). Strategies classified by structural
evidence: weather ROBUST-candidate, arb ROBUST-if-fillable, copy/signal FRAGILE,
late_entry UNTRADEABLE-until-validated. No numbers invented.

### 8. Portfolio framework
Edge-type diversification (informational/structural/behavioral); candle presets = one
sleeve; weight by edge quality; liquidity-ceiling per sleeve; recalibrate on
walk-forward boundaries (Phase 9).

### 9. Optimization roadmap
Per-strategy current→improved table (Phase 12), all gated behind the harness.

### 10. Highest-EV implementation roadmap
**Build the backtest/calibration harness first** (data substrate already in DB) →
validate weather → re-enable + extend the complete-set gate to harvest arb + add a per-asset concentration sub-limit (pure risk wins) →
calibrate candle confidence (A4) → wallet-360 copy gate (A3) → regime layer → portfolio
weighting. Capital scales LIVE only behind OOS-validated edge.

---

## PRIORITY RANKING

### HIGH PRIORITY (do first — unblocks everything / pure risk wins)
- **H1. Backtest + calibration harness** (F-1). Replay existing trade history; produce
  OOS metrics. Unblocks F-2, all validation, Monte Carlo, portfolio weights.
- **H2. Re-enable + extend the complete-set gate** (F-3). The `_gate_complete_set_edge`
  rejection filter is wired but inert (`MIN_COMPLETE_SET_EDGE = 0.0`); set it > 0 to
  resume blocking overpriced directional entries (config-only), then add a *harvest* path
  that buys the set when `cost < $1.00` with depth-aware sizing (A2).
- **H3. Per-asset concentration sub-limit** — the global exposure cap is correlation-
  blind, so a book can sit entirely in one underlying within the 40% cap; an optional
  per-asset sub-cap trims correlated-cluster variance without cutting winning trades
  (Phase 7.1).
- **H4. Liquidity-aware sizing on thin candle books** — recovers edge lost to fill-drift
  (F-4); `_book_depth_usdc` already computed.
- **H5. Validate + scale weather** — the only defensible existing edge.

### MEDIUM PRIORITY (raise EV at constant risk — after the harness exists)
- **M1. Calibrated late-favorite (A4)** — replace `ask_diff` with learned `P(win)`.
- **M2. Wallet-360 copy gate (A3)** — use agent-581 metrics already fetched.
- **M3. Regime detection + dynamic switching** (Phase 3 layer).
- **M4. Unify confidence onto one EV scale** (Phase 4 composite score).

### LOW PRIORITY (polish / scope-dependent)
- **L1. Calibrate signal_following confidence** to realized feed hit-rate.
- **L2. Social/candlestick confluence (A5)** for the feed.
- **L3. Remove the dead `value` stub** (`domain/signal/value.py`).
- **L4. Macro intelligence** — only if the roster expands to event markets (else noise).

> **Optimization target obeyed:** every recommendation is ranked for **expected value,
> robustness, scalability, survivability, and long-term edge persistence** — not
> elegance. The throughline: *measure before you scale.* The system's biggest alpha risk
> is not a bad strategy — it is the absence of any mechanism to know which strategies are
> good.

---

## REPORT METADATA (per CLAUDE.md WARP•FORGE/R00T)

**1. What was built:** A code-grounded strategic alpha research audit (this document).
No runtime code changed (task: "do not write code").
**2. Current system architecture:** documented in Phase 1 + the pipeline map.
**3. Files created/modified:**
`projects/polymarket/crusaderbot/reports/forge/strategic-alpha-research.md` (new).
**4. What is working:** risk gate (15-step), kill switch, paper-default, weather model,
data ingestion + caching, monitoring/alerts — all verified in code.
**5. Known issues / gaps surfaced:** F-1 no backtest · F-2 no candle probability model ·
F-3 complete-set edge gate config-disabled + not harvested as arb · F-4 fill-drift /
execution-edge loss · F-5 unharvested Wallet-360 intelligence.
**6. What is next:** HIGH-priority H1–H5 above; all LIVE scaling gated behind OOS
validation.

- **Validation Tier:** MINOR (research, non-runtime)
- **Claim Level:** FOUNDATION
- **Validation Target:** strategy/edge/risk audit of the live pipeline as of HEAD
- **Not in Scope:** writing/refactoring code; flipping activation guards; LIVE trading;
  inventing performance numbers; merging.
- **Suggested Next Step:** WARP🔹CMD review → scope H1 (backtest harness) as the first
  build lane; it is the prerequisite for validating every other recommendation.

### WARP•R00T findings format (top 5)

| # | Problem | Root cause | Risk | Technical impact | Recommended solution | Files |
|---|---|---|---|---|---|---|
| F-1 | No backtest/validation framework | built by imitating a reference bot; never invested in validation infra | CRITICAL | no OOS support for any parameter; cannot size LIVE responsibly | build replay harness on existing trade history | (new harness) |
| F-2 | Candle "confidence" is a price gap, not a probability | no model; `confidence=ask_diff` | CRITICAL | EV unknown; asymmetric tail uncontrolled | calibrated `P(win)` from own outcomes | `late_entry_v3.py:649` |
| F-3 | Complete-set edge gate is config-disabled + never harvested as arb | `MIN_COMPLETE_SET_EDGE=0.0` makes the wired filter inert; no path buys the set when cost<$1.00 | HIGH | a riskless edge sits unharvested; defensive filter currently off | re-enable filter (>0) + add depth-aware harvest path (A2) | `signal_scan_job.py:1798-1856`, `config.py:559`, `late_entry_v3.py:606` |
| F-4 | Execution edge destroyed at fill | thin final-35s books + latency | HIGH | fills land outside intended band (5.5%/17%) | liquidity-aware sizing; keep TOB/fill-band guards | `signal_scan_job.py:1749-1929` |
| F-5 | Premium intelligence unharvested | data fetched, then ignored | HIGH | pays for Wallet-360 (agent 581) but uses fixed 0.75 | quality-weighted, sybil-gated copy confidence | `copy_trade.py:40`, `wallet_360.py:96-174` |

**Validation performed:** read-only reverse-engineering of `domain/`, `services/`,
`integrations/`, `strategies/weather/`, `monitoring/`, `state/`, and
`docs/blueprint/crusaderbot.md`; exhaustive search confirming no backtest module exists.
No code executed; no runtime touched.

---

*End — WARP-51 Strategic Alpha Research. WARP•R00T does not merge; WARP🔹CMD decides.*



