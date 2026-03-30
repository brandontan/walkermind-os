# KNOWLEDGE BASE — Walker AI Trading Team
> Master reference file for COMMANDER
> Repo: https://github.com/bayuewalker/walker-ai-team
> Last Updated: 2026-03-30

---

# PART 0 — SYSTEM PRINCIPLES

## 0.1 Architecture Philosophy

DATA → SIGNAL → RISK → EXECUTION → MONITORING

- Deterministic > probabilistic behavior  
- No silent failures  
- Safety overrides profitability  
- Every decision must be explainable  

---

## 0.2 Agent Role Separation (CRITICAL)

COMMANDER:
- Planning, validation, decisions  

FORGE-X:
- System implementation  

BRIEFER:
- Prompt generation, UI, reporting  

SENTINEL:
- Testing & validation ONLY (NOT runtime risk gate)  

---

## 0.3 Runtime Risk Engine (FIXED)

LAYER 3 is NOT SENTINEL.

Correct:

LAYER 3 — RISK ENGINE (runtime)

- Enforces all trading rules  
- Blocks invalid trades  
- Executes before order submission  

SENTINEL:
→ Used ONLY for testing (on-demand)  

---
# PART 1 — CORE TRADING FORMULAS

## 1.1 Edge Detection

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

---

## 1.2 Position Sizing

Kelly Criterion:
f = (p·b − q) / b  
p = win prob, q = 1-p, b = net odds  

⚠️ FRACTIONAL KELLY — ALWAYS USE THIS:
f_final = α · f_kelly  
α = 0.25 (default for ALL markets)  

NEVER full Kelly (α=1.0)  
NEVER full Kelly on short timeframe markets  

Value at Risk (95%):
VaR = μ − 1.645 · σ  

Conditional VaR:
CVaR = E[loss | loss > VaR]  

Volatility Scaling:
w = target_vol / realized_vol  

---

## 1.3 Risk Metrics

Max Drawdown:
MDD = (Peak − Trough) / Peak  
Block new trades if MDD > 8%  

Downside Deviation:
σ_d = √E[min(R − τ, 0)²]  

Correlation Control:
Max correlated exposure = 40% bankroll  

---

## 1.4 Performance Metrics

Sharpe Ratio:
SR = (ER − RF) / σ(R)  
Target: SR > 2.5  

Sortino Ratio:
Sortino = (ER − RF) / σ_d  
Target: Sortino > 2.0  

Profit Factor:
PF = gross_profit / gross_loss  
Target: PF > 1.5  
PF < 1.0 = losing system  

Win Rate:
WR = winning_trades / total_trades  
Target: WR > 70%  

Expectancy:
E = (WR × avg_win) − ((1−WR) × avg_loss)  

Information Ratio:
IR = (R − B) / σ(R−B)  

---

## 1.5 Arbitrage Formulas

Arb Condition:
Σ (1/odds_i) < 1 → profit exists  

Net Edge:
net_edge = gross_edge − fees − slippage  

Execute ONLY if:
- net_edge > 2%  

CEX vs Polymarket Lag:
lag_window ≈ 500ms  

---

## 1.6 Polymarket Market Cost Function

C(q) = β · ln(Σ e^(qi/2))  

β = liquidity sensitivity parameter  
Higher β → deeper liquidity  
Lower β → higher sensitivity  

Market Maker Max Loss:
L_max = β · ln(n) / P(D)  

Binary market (n=2):
L_max ≈ $55k (example)  

---

## 1.7 Quick Reference Thresholds

ENTRY CONDITIONS:
✓ EV > 0  
✓ edge > 0  
✓ S > 1.5  
✓ net_edge > 2%  
✓ liquidity > $10,000  

POSITION RULES:
✓ Kelly α = 0.25  
✓ Max position = 10% bankroll  
✓ Max concurrent = 5  
✓ Correlation ≤ 40%  

RISK LIMITS:
✓ Daily loss = −$2000  
✓ Max drawdown = 8%  
✓ PF ≥ 1.5  

PERFORMANCE TARGETS:
✓ Win Rate > 70%  
✓ Sharpe > 2.5  
✓ Profit Factor > 1.5  

---

END OF PART 1 — CORE TRADING FORMULAS

# PART 2 — SYSTEM SPECIFICATIONS

NOTE:
PART 1 defines all mathematical & trading logic  
PART 2 defines system architecture & implementation  

---

## 2.1 Platform Specs

POLYMARKET (Primary)  
Type: CLOB Prediction Market  
Network: Polygon PoS  
API: CLOB API + Gamma API  
WebSocket: Real-time order book  
Token: USDC (6 decimals)  
Contract: CTF (Conditional Token Framework)  
Fee: ~2% taker / 0% maker  

KALSHI (Secondary — Arb Target)  
Type: Regulated prediction market  
Currency: USD cents  
Use: Cross-exchange arbitrage  

BINANCE (CEX Reference)  
Use: Price reference for lag detection  
Lag: ~500ms vs Polymarket  

TRADINGVIEW  
Language: Pine Script v5  
Alerts: Webhook → CONNECT pipeline  

MT4 / MT5  
MT4: MQL4 (.ex4)  
MT5: MQL5 (.ex5)  

---

## 2.2 Tech Stack

Language: Python 3.11+  
Async: asyncio + aiohttp  
WebSocket: websockets  
Queue: asyncio.Queue (event bus)  

Database:
- PostgreSQL  
- Redis  
- InfluxDB  

Chain: Polygon PoS (ID: 137)  
Deploy: VPS / Replit  

---

## 2.3 Bot Architecture

LAYER 0 — DATA INGESTION  
Polymarket WS + Binance WS + Kalshi API  
→ asyncio.Queue  

LAYER 1 — RESEARCH (ORACLE)  
News + sentiment + drift detection  
→ structured data  

LAYER 2 — SIGNAL (QUANT)  
EV calculation + Bayesian update  
→ signal + size  

LAYER 3 — RISK ENGINE (runtime)  
All checks must PASS  
Reject = order not sent  

NOTE:  
SENTINEL is NOT part of runtime  
SENTINEL is ONLY used for testing & validation  

LAYER 4 — EXECUTION (FORGE-X)  
Deduplication → order submission → fill tracking  

LAYER 5 — ANALYTICS (EVALUATOR)  
Logging → metrics → reporting  

---

## 2.4 Latency Targets

Data Ingestion: <100ms  
Signal: <200ms  
Execution: <500ms  

End-to-End: <1000ms  
(Target only — not guaranteed in live conditions)  

---

## 2.5 Key API Endpoints

Polymarket CLOB:  
https://clob.polymarket.com  

Polymarket Gamma:  
https://gamma-api.polymarket.com  

PM Intelligence API:  
https://narrative.agent.heisenberg.so  

Polygon RPC:  
https://polygon-rpc.com  

---

## 2.6 Engineering Standards

- Python 3.11+  
- asyncio ONLY (no threading)  
- Full type hints required  

- Retry + timeout on ALL external calls  
- Structured JSON logging  
- Idempotent systems  

- Secrets in `.env` only  
- No hardcoded values  

- Every function must have docstring  
- Zero silent failures  

---

END OF PART 2 — SYSTEM SPECIFICATIONS

# PART 3 — PREDICTION MARKET INTELLIGENCE API

Base URL: https://narrative.agent.heisenberg.so  
Endpoint: POST /api/v2/semantic/retrieve/parameterized  

---

## 3.1 Universal Request Format

{
  "agent_id": <number>,
  "params": { ... },
  "pagination": { "limit": 50, "offset": 0 },
  "formatter_config": {
    "format_type": "raw"
  }
}

---

## 3.2 Rules (MANDATORY)

- agent_id is FIXED per endpoint  
- ALL params must be STRINGS  
- pagination values are INTEGERS  
- ALWAYS include formatter_config  
- max pagination limit = 200  

Time format:
- Default: Unix timestamp (seconds)  
- PnL endpoint: YYYY-MM-DD  

---

## 3.3 Agent ID Mapping

574 → Polymarket Markets  
556 → Polymarket Trades  
568 → Candlesticks (token_id required)  
572 → Orderbook (token_id required)  
569 → PnL (wallet required)  
579 → Leaderboard  
584 → H-Score (preferred — filters bots)  
581 → Wallet 360  
575 → Market Insights  
565 → Kalshi Markets  
573 → Kalshi Trades  
585 → Social Pulse  

---

## 3.4 Core Workflows

COPY TRADING PIPELINE:
584 → 581 → 556 → 575 → 585  

Purpose:
- Find profitable traders  
- Validate behavior  
- Replicate trades  

---

CROSS-EXCHANGE ARBITRAGE:
565 → 574 → 573 + 556 → 575  

Purpose:
- Detect price differences  
- Confirm liquidity  
- Execute arbitrage  

---

BREAKING NEWS SIGNAL:
585 → 574 → 568 → 575  

Purpose:
- Detect emerging narratives  
- Check if price moved  
- Validate liquidity before entry  

---

SETTLEMENT GAP SCANNER:
565 → 574 → 568 → 572  

Purpose:
- Detect unresolved markets  
- Identify near-settlement inefficiencies  

---

## 3.5 Social Pulse Interpretation

acceleration > 1.0 → mentions rising  
author_diversity > 50% → organic  

REAL SIGNAL:
- high acceleration + high diversity → VALID  

NOISE:
- high acceleration + low diversity → IGNORE  

Momentum signal:
- 1h > 6h → trending now  
- 1h < 6h → fading  

---

## 3.6 API Best Practices

- Always start with Markets (574)  
- Use H-Score (584) over leaderboard (579)  
- Always validate liquidity before trading  

- Never trade based on single signal  
- Combine:
  - market data  
  - trade flow  
  - social signal  

---

END OF PART 3 — API SYSTEM

# PART 4 — PICO FRAMEWORK
Solo Operator System for Low-Capital Trading ($100–$500)

---

## 4.1 Overview

PICO = modular pipeline optimized for:
- Low capital
- Limited trades
- High efficiency

Core modules:

1. Market Selection  
2. Entry / Exit Logic  
3. Position Sizing  
4. Risk Controls  
5. Paper Trading  
6. Observability  

---

## 4.2 Market Selection

Liquidity Score L_m(t) ∈ [0,1]

Increases with:
- Orderbook depth  
- Recent volume  

Decreases with:
- Bid-ask spread  
- Time-to-event risk  

Feature vector φ_m(t):

- δ_m(t) → spread  
- D_m(t) → depth  
- τ_m(t) → turnover  
- evt_m(t) → time to event  
- σ_m(t) → volatility  

Selection rule:
→ pick top-K markets based on liquidity-adjusted signal  

---

## 4.3 Position Sizing (PICO)

Max stake per market:

w_m(t) ≤ min(E_m × B(t), b_max)

Where:
- E_m = 2%–4% bankroll  
- B(t) = current bankroll  
- b_max = hard cap  

---

Risk constraint:

w_m(t) ≤ max_loss_m / max(p_m, 1−p_m)

Where:
- max_loss_m = α × B(t)  
- α = 0.02–0.05  

---

## 4.4 Cooldown & Anti-Overtrading

Cooldown τ_m after position close  

Rules:
- Market only tradable if cooldown expired  
- Max trades/day = 2  
- Decision frequency = 1–6 hours  

---

Optional model (advanced):

2-layer predictor:
- Input: φ_m(t)  
- Output: cooldown scalar  

Range:
c_m(t) ∈ [0, C_max]

---

## 4.5 Stop-Loss & Take-Profit

Stop-loss:
Exit if PnL < −θ_loss  

Take-profit:
Exit if PnL > θ_profit  

Guideline:
- θ_loss = small fraction of position  
- θ_profit = multiple of θ_loss  

---

## 4.6 Cost Model

PnL_realized = payout − fees − slippage − settlement  

Components:

- Fee: 0–2%  
- Slippage: liquidity dependent  
- Settlement delay  

---

## 4.7 Hyperparameters

Exposure cap: 2–4%  
Max trades/day: 2  
Decision interval: 1–6h  
Fees: 0–2%  

Evaluation:
- 60-day window  
- Multiple walk-forward folds  
- 3 random seeds  

---

## 4.8 Observability Checklist

Monitor:

- Liquidity per market  
- Exposure  
- Cooldown state  
- Drawdown  
- Daily PnL  
- Win rate (rolling 20 trades)  
- Slippage vs expected  

---

## 4.9 Walk-Forward Validation

W_train → optimize parameters  
W_eval → test performance  

Rules:
- No data leakage  
- Separate regimes  

Compare:
- FixCD  
- RandEntr  
- Heuristic  
- PICO  

---

END OF PART 4 — PICO FRAMEWORK

# PART 5 — TRADING STRATEGIES OVERVIEW

---

## 5.1 Strategy Categories

BEGINNER:

- SMA Crossover  
  → signal dari moving average  

- Momentum  
  → M = Pt − Pt-n  
  → follow trend  

---

INTERMEDIATE:

- Mean Reversion  
  → harga kembali ke rata-rata  

- Bayesian Signal  
  → update probability dari data baru  

- Mispricing (Z-Score)  
  → S = (p_model − p_market) / σ  

- PICO Framework  
  → liquidity-aware micro trading  

---

ADVANCED:

- Machine Learning / Deep Learning  
  → pattern recognition  

- Bayesian Fusion  
  → multi-signal integration  

- Market Microstructure  
  → C(q) = β·ln(Σ e^(qi/2))  

- CEX vs Polymarket Arbitrage  
  → exploit ~500ms lag  

- Orderbook Spread Capture  
  → liquidity edge  

- Volatility Compression  
  → dual-side positioning  

- Copy Trading (H-Score based)  
  → follow top traders  

---

## 5.2 Strategy Selection Guide

Budget: $100–$500  
→ Use PICO framework  
→ Max 2–4% per trade  
→ Max 2 trades/day  
→ Focus: liquidity  

---

Budget: $500–$5,000  
→ Momentum + Bayesian  
→ Kelly 0.25  
→ Up to 5 concurrent  

---

Budget: $5,000+  
→ Multi-strategy system  
→ Arbitrage + copy trading  
→ CEX lag exploitation  

---

## 5.3 Strategy Execution Rules

- Never rely on single signal  
- Combine:
  - price  
  - trade flow  
  - sentiment  

- Always validate:
  - liquidity  
  - spread  
  - execution feasibility  

---

## 5.4 Strategy Risk Alignment

Every strategy MUST respect:

- Kelly fraction = 0.25  
- Max position = 10%  
- Max concurrent = 5  
- Daily loss = −$2000  
- Drawdown limit = 8%  

---

END OF PART 5 — STRATEGIES

# PART 6 — PROJECT CONTEXT

---

## 6.1 Team Structure

COMMANDER  
→ Planning, validation, decision making  

FORGE-X  
→ System implementation (Claude Code → GitHub)  

BRIEFER  
→ Prompt generation, UI, reporting  

SENTINEL  
→ Testing & validation (on-demand ONLY)  

---

## 6.2 Repository Structure

https://github.com/bayuewalker/walker-ai-team  

projects/polymarket/  
→ Python trading bot  

projects/tradingview/indicators/  
→ Pine Script indicators  

projects/tradingview/strategies/  
→ Pine Script strategies  

projects/mt5/ea/  
→ MQL5 Expert Advisors  

projects/mt5/indicators/  
→ MQL5 indicators  

docs/  
→ Knowledge base  

---

## 6.3 Workflow

1. COMMANDER defines task  
2. FORGE-X builds system  
3. BRIEFER supports (prompt/UI/report)  
4. SENTINEL validates (ONLY if triggered)  

---

## 6.4 Operational Modes

BUILD MODE:

1. Analyze requirement  
2. Identify risks  
3. Ask approval  
4. Generate FORGE-X task  
5. Review output  
6. Confirm running → STANDBY  

---

MAINTENANCE MODE:

1. Root cause analysis  
2. Generate fix task  
3. Validate resolution  

---

STANDBY MODE:

- No action  
- Wait for command  

---

## 6.5 Done Criteria

✓ Code merged to main  
✓ README complete  
✓ Risk rules enforced  
✓ No runtime errors (24h)  
✓ Founder confirms system stable  

---

## 6.6 Risk Rules (NON-NEGOTIABLE)

max_position_pct = 0.10  
max_concurrent = 5  
daily_loss_limit = −2000  
max_drawdown_pct = 0.08  
kelly_fraction = 0.25  
min_liquidity = 10000  
correlation_limit = 0.40  

---

## 6.7 Go-Live Gate

System CANNOT go live unless:

- Risk rules validated  
- No critical issues  
- SENTINEL approval obtained  

---

END OF PART 6 — PROJECT CONTEXT
