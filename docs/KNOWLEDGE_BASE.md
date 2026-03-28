# KNOWLEDGE BASE — Walker AI Trading Team
> Master reference file for COMMANDER
> Repo: https://github.com/bayuewalker/walker-ai-team
> Last Updated: [UPDATE THIS DATE]

---

# PART 1 — CORE TRADING FORMULAS

## 1.1 Edge Detection

```
Expected Value:
EV = p·b − (1−p)
p = model probability, b = decimal odds − 1
Enter trade ONLY if EV > 0

Market Edge:
edge = p_model − p_market
Positive edge = opportunity exists

Mispricing Z-Score:
S = (p_model − p_market) / σ
Enter if S > 1.5 (strong)
Enter if S > 2.0 (very strong)

Momentum Score:
M = Pt − Pt-n
Positive = upward momentum

Bayesian Update (log-space):
log P(H|D) = log P(H) + Σ log P(Dk|H) − log Z
Update beliefs after every new data point

Win Probability Adjustment:
p* = p_model − bias
Corrects systematic model overconfidence

Log Return:
r = ln(Pt / Pt-1)
```

## 1.2 Position Sizing

```
Kelly Criterion:
f = (p·b − q) / b
p = win prob, q = 1-p, b = net odds

⚠️ FRACTIONAL KELLY — ALWAYS USE THIS:
f_final = α · f_kelly
α = 0.25 (default for ALL markets)
NEVER full Kelly (α=1.0)
NEVER full Kelly on 5-min markets!

Value at Risk 95%:
VAR = μ − 1.645 · σ

Conditional VaR:
CVaR = E[loss | loss > VaR]

Volatility Scaling:
w = target_vol / realized_vol
```

## 1.3 Risk Metrics

```
Max Drawdown:
MDD = (Peak − Trough) / Peak
Block new trades if MDD > 8%

Downside Deviation:
σ_d = √E[min(R − τ, 0)²]

Correlation check:
Max correlated exposure = 40% bankroll
```

## 1.4 Performance Metrics

```
Sharpe Ratio:
SR = (ER − RF) / σ(R)
Target: SR > 2.5

Sortino Ratio:
Sortino = (ER − RF) / σ_d
Target: Sortino > 2.0

Profit Factor:
PF = gross_profit / gross_loss
Target: PF > 1.5
PF < 1.0 = losing strategy

Win Rate:
WR = winning_trades / total_trades
Target: WR > 70%

Expectancy:
E = (WR × avg_win) − ((1−WR) × avg_loss)
Positive = profitable system

Information Ratio:
IR = (R − B) / σ(R−B)

Max Drawdown:
MDD = (Peak−Trough) / Peak
```

## 1.5 Arbitrage Formulas

```
Arb Condition:
Σ (1/odds_i) < 1 = profit exists

Net Edge After Fees:
net_edge = gross_edge − fees − slippage
Only execute if net_edge > 2%

CEX vs Polymarket Lag:
lag_window ≈ 500ms
PM lags Binance on BTC/ETH moves
```

## 1.6 Polymarket Market Cost Function

```
C(q) = β · ln(Σ e^(qi/2))
β = liquidity sensitivity parameter
larger β = deeper liquidity
smaller β = higher price sensitivity

Market Maker Max Loss:
L_max = β · ln(n) / P(D)
Binary market (n=2, β=$80k):
L_max ≈ $55,451
```

## 1.7 Quick Reference Thresholds

```
ENTRY CONDITIONS:
✓ EV > 0
✓ edge = p_model − p_market > 0
✓ Mispricing S > 1.5
✓ Net arb edge > 2% after fees
✓ Liquidity > $10,000

POSITION SIZING:
✓ Kelly α = 0.25 (always fractional)
✓ Max position = 10% bankroll
✓ Max concurrent = 5 positions
✓ Max correlated exposure = 40%

RISK LIMITS:
✓ Daily loss limit = −$2,000
✓ Max drawdown = 8% → stop all
✓ Profit Factor min = 1.5

PERFORMANCE TARGETS:
✓ Win Rate > 70%
✓ Sharpe Ratio > 2.5
✓ Profit Factor > 1.5
✓ Max Drawdown < 5%
✓ Avg Profit/Trade > $15
```

---

# PART 2 — SYSTEM SPECIFICATIONS

## 2.1 Platform Specs

```
POLYMARKET (Primary)
Type:     CLOB Prediction Market
Network:  Polygon PoS
API:      CLOB API + Gamma API
WebSocket: Real-time order book
Token:    USDC (6 decimals)
Contract: CTF (Conditional Token Framework)
Fee:      ~2% taker / 0% maker

KALSHI (Secondary — Arb Target)
Type:     Regulated prediction market
Currency: USD cents
Use:      Cross-platform arb vs Polymarket

BINANCE (CEX Reference)
Use:      Price reference for CEX lag exploit
Lag:      PM lags Binance ~500ms on BTC/ETH

TRADINGVIEW
Language: Pine Script v5
Alerts:   Webhook → CONNECT pipeline

MT4/MT5
MT4: MQL4 → .ex4 files
MT5: MQL5 → .ex5 files
```

## 2.2 Tech Stack

```
Language:  Python 3.11+
Async:     asyncio + aiohttp
WebSocket: websockets library
Queue:     asyncio.Queue (event bus)
Database:  PostgreSQL + Redis + InfluxDB
Chain:     Polygon PoS (Chain ID: 137)
Deploy:    Replit / VPS
```

## 2.3 Bot Architecture

```
LAYER 0 — DATA INGESTION
Polymarket WS + Binance WS + Kalshi API
→ asyncio.Queue (Event Bus)

LAYER 1 — RESEARCH (ORACLE)
news_fetcher + sentiment + drift_detector
→ structured JSON output

LAYER 2 — SIGNAL (QUANT)
EV calculation + Bayesian update
→ Signal: YES/NO + size

LAYER 3 — RISK GATE (SENTINEL)
All checks must PASS
REJECT = order never sent

LAYER 4 — EXECUTION (FORGE-X)
Dedup → CLOB submission → Fill monitor

LAYER 5 — ANALYTICS (EVALUATOR)
Trade logged → Metrics updated → Report
```

## 2.4 Latency Targets

```
Data Ingestion:    <100ms
Signal Generation: <200ms
Order Execution:   <500ms ← bottleneck
End-to-End:        <1000ms
```

## 2.5 Key API Endpoints

```
Polymarket CLOB:  https://clob.polymarket.com
Polymarket Gamma: https://gamma-api.polymarket.com
PM Intelligence:  https://narrative.agent.heisenberg.so
Polygon RPC:      https://polygon-rpc.com
```

## 2.6 Engineering Standards

```
✓ Full type hints required
✓ Structured JSON logging everywhere
✓ All secrets in .env only
✓ Idempotency on all orders
✓ Retry + timeout on all API calls
✓ No hardcoded values — use config.yaml
✓ Every function needs docstring
✓ Zero silent failures
```

---

# PART 3 — PREDICTION MARKET INTELLIGENCE API

```
Base URL: https://narrative.agent.heisenberg.so
Endpoint: POST /api/v2/semantic/retrieve/parameterized

Universal Request:
{
  "agent_id": <number>,
  "params": { ... },
  "pagination": { "limit": 50, "offset": 0 },
  "formatter_config": { "format_type": "raw" }
}

Rules:
- agent_id is FIXED per endpoint
- All params are STRINGS
- Max pagination limit: 200
- Timestamps: Unix seconds (except PnL = YYYY-MM-DD)
```

## 3.1 Agent ID Quick Reference

```
574 → Polymarket Markets
556 → Polymarket Trades
568 → Polymarket Candlesticks (token_id required)
572 → Polymarket Orderbook (token_id required)
569 → Polymarket PnL (wallet required, date = YYYY-MM-DD)
579 → Polymarket Leaderboard
584 → H-Score Leaderboard (filter bots — use this not 579)
581 → Wallet 360 (60+ metrics per wallet)
575 → Polymarket Market Insights
565 → Kalshi Markets
573 → Kalshi Trades
585 → Social Pulse (keywords in {curly braces})
```

## 3.2 Key Workflows

```
COPY-TRADING PIPELINE:
584 (H-Score) → 581 (Wallet 360) → 556 (Trades)
→ 575 (Market Insights) → 585 (Social Pulse)

CROSS-EXCHANGE ARB:
565 (Kalshi) → 574 (Polymarket) → 573+556 (Trades)
→ 575 (Liquidity check)

BREAKING NEWS SIGNAL:
585 (Social: acceleration>1.5, diversity>40%)
→ 574 (Find related markets)
→ 568 (Check if price moved yet)
→ 575 (Verify liquidity before acting)

SETTLEMENT GAP SCANNER:
565 (Kalshi finalized) → 574 (Polymarket match)
→ 568 (Price converged to 0/1?)
→ 572 (Liquidity still available?)
```

## 3.3 Social Pulse Reading

```
acceleration > 1.0 = mentions rising
author_diversity_pct > 50% = organic
author_diversity_pct < 20% = bot noise → ignore

REAL SIGNAL:
high acceleration + high diversity → act

NOISE:
high acceleration + low diversity → ignore

pct_last_1h high vs pct_last_6h → surging NOW
pct_last_1h low vs pct_last_6h high → fading
```

---

# PART 4 — PICO FRAMEWORK
*Solo Operator Framework for Small-Budget Polymarket Bots*

## 4.1 Overview

```
PICO = modular pipeline for micro-budget ($100-$500)
Polymarket trading by a solo operator.

Core modules:
1. Market Selection — liquidity-aware ranking
2. Entry/Exit Logic — YES/NO under liquidity constraints
3. Position Sizing — exposure caps + risk budget
4. Risk Controls — stop-loss, take-profit, cooldowns
5. Paper Trading — cost-aware backtesting
6. Observability — metrics, logs, alerts
```

## 4.2 Market Selection

```
Liquidity Score L_m(t) ∈ [0,1]:
- Increases with: depth, recent turnover
- Decreases with: bid-ask spread, time-to-event

Feature vector φ_m(t):
- δ_m(t) = bid-ask spread
- D_m(t) = depth proxy
- τ_m(t) = recent turnover
- evt_m(t) = time-to-event
- σ_m(t) = volatility proxy

Select top-K markets by liquidity-adjusted signal
```

## 4.3 Position Sizing (PICO)

```
Max stake per market:
w_m(t) ≤ min(E_m × B(t), b_max)

E_m = 0.02–0.04 of bankroll (2-4% per market)
b_max = hard cap to prevent over-concentration

Risk budget rule:
w_m(t) ≤ max_loss_m / max(p_m(t), 1−p_m(t))
max_loss_m = α × B(t)
α ∈ (0, 0.1] typically 0.02–0.05
```

## 4.4 Cooldown & Anti-Overtrading

```
Cooldown τ_m after every position close
Market eligible only if c_m(t) ≤ θ_min

Max trades per day: 2
Decision cadence: 1–6 hours

Dynamic cooldowns via 2-layer predictor:
- 64–128 hidden units
- Per-market features φ_m(t)
- Output: cooldown scalar c_m(t) ∈ [0, C_max]
```

## 4.5 Stop-Loss & Take-Profit

```
Stop-loss θ_loss: exit if unrealized PnL < −θ_loss
Take-profit θ_profit: exit to lock gains

θ_loss = modest fraction of w_m(t)
θ_profit = small multiple of θ_loss

Calibrate to market liquidity & horizon
```

## 4.6 Cost Model

```
Per-unit fee: f = 0.0–0.02
Slippage: s_m(t) ∝ liquidity proxy
Settlement delay: g_m(t)

Always include ALL costs in backtest:
PnL_realized = payout − fee − slippage − settlement
```

## 4.7 PICO Hyperparameters

```
Exposure cap E_m:    0.02–0.04 of bankroll
Max daily trades:    2
Decision cadence:    1–6 hours
Fees:                0–2% per unit
Evaluation window:   60 days per walk-forward fold
Walk-forward folds:  Multiple regimes
Seeds:               3 random seeds for stochastic runs
```

## 4.8 Observability Checklist

```
Per session, monitor:
✓ Per-market liquidity proxies
✓ Current exposure levels
✓ Cooldown status per market
✓ Risk alerts (drawdown, daily loss)
✓ P&L trajectory
✓ Win rate rolling 20 trades
✓ Slippage actual vs estimated
```

## 4.9 Walk-Forward Validation Protocol

```
W_train → calibrate parameters
W_eval  → test (strictly separated, no lookahead)

Vary regimes:
- Easy Liquidity vs Hard Liquidity
- Event-driven vs Non-event windows

Report with 95% CI via bootstrap
Compare arms: FixCD vs RandEntr vs HeurPred vs PICOLQ
```

---

# PART 5 — TRADING STRATEGIES OVERVIEW

## 5.1 Strategies by Complexity

```
BEGINNER:
- SMA Crossover — moving average signals
- Momentum — M = Pt − Pt-n trend riding

INTERMEDIATE:
- Mean Reversion — bet on return to average
- Bayesian Signal — update beliefs with data
- Mispricing Score — Z-score entry filter
- PICO Framework — liquidity-aware micro-budget

ADVANCED:
- ML/DL pattern recognition (Neural nets, Bayes, KNN)
- Bayesian Fusion — multi-signal combination
- Market Cost Function: C(q) = β·ln(Σ e^(qi/2))
- CEX vs PM spread arb (500ms lag exploit)
- CLOB spread capture
- Volatility compression both-sides entry
- Copy-trading via H-Score leaderboard

FULL REFERENCE:
→ docs/ssrn-3247865.pdf (151 strategies, 550+ formulas)
→ docs/pico.pdf (PICO framework full paper)
→ docs/advancee_trade_strategy.pdf
```

## 5.2 Strategy Selection Guide

```
Budget $100-$500:
→ Use PICO framework
→ Max 2-4% per market
→ Max 2 trades/day
→ Focus: liquidity-aware markets only

Budget $500+:
→ Momentum + Bayesian Signal
→ Kelly 0.25 sizing
→ Up to 5 concurrent positions

Budget $5,000+:
→ Full multi-strategy
→ Arb scanning (SCOUT)
→ CEX lag exploit
→ Copy-trading pipeline
```

---

# PART 6 — PROJECT CONTEXT

## 6.1 Team Structure

```
COMMANDER — Master AI Agent (Claude Project)
FORGE-X   — Full-stack engineer (Claude Code → GitHub)
BRIEFER   — Prompt maker for external AI (Claude Project)
```

## 6.2 GitHub Repository

```
https://github.com/bayuewalker/walker-ai-team

projects/polymarket/             → Python trading bot
projects/tradingview/indicators/ → Pine Script v5
projects/tradingview/strategies/ → Pine Script v5
projects/mt5/ea/                 → MQL5 Expert Advisors
projects/mt5/indicators/         → MQL5 indicators
docs/                            → this knowledge base
```

## 6.3 Operational Rules

```
BUILD MODE:
1. Analyze requirement
2. Give suggestions & risks
3. Ask approval BEFORE starting
4. Generate task for FORGE-X
5. Review output
6. Report: "Running ✅ → STANDBY"

STANDBY:
- Zero self-initiative
- Wait for next order

DONE CRITERIA:
✓ Code in GitHub main branch
✓ README complete
✓ Risk logic reviewed
✓ Running 24+ hours error-free
✓ Founder confirms "running well ✅"
```

## 6.4 Risk Rules (non-negotiable)

```
max_position_pct:      0.10
max_concurrent:        5
daily_loss_limit:      -2000 USD
max_drawdown_pct:      0.08
kelly_fraction:        0.25 (NEVER full Kelly)
min_liquidity:         10000 USD
min_ev:                0.0
correlation_limit:     0.40
```

---

*Walker AI Trading Team — COMMANDER Knowledge Base*
*Upload this single file to Claude Project Knowledge section*
*Update at: https://github.com/bayuewalker/walker-ai-team/blob/main/docs/KNOWLEDGE_BASE.md*
