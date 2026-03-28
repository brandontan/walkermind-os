# Core Trading Formulas
> AI Trading Team — Knowledge Reference
> Repo: https://github.com/bayuewalker/walker-ai-team
> File: /docs/formulas.md

---

## 1. EDGE DETECTION

### Expected Value (EV)
```
EV = p·b − (1−p)

p = model probability (your estimate)
b = decimal odds − 1
Enter trade only if EV > 0
```

### Market Edge
```
edge = p_model − p_market

p_model = your estimated true probability
p_market = current market price
Positive edge = opportunity exists
```

### Mispricing Z-Score
```
S = (p_model − p_market) / σ

σ = historical volatility of market price
Enter if S > 1.5 (strong signal)
S > 2.0 = very strong signal
```

### Momentum Score
```
M = Pt − Pt-n

Pt = current price
Pt-n = price n periods ago
Positive M = upward momentum
Negative M = downward momentum
```

### Bayesian Probability Update
```
Pr(H|D) = Pr(D|H) · Pr(H) / Pr(D)

Log-space (numerically stable):
log P(H|D) = log P(H) + Σ log P(Dk|H) − log Z

Update beliefs after every new data point
Z = normalizing constant
```

### Win Probability Adjustment
```
p* = p_model − bias

bias = historical model error
Corrects systematic overconfidence
```

### Log Return
```
r = ln(Pt / Pt-1)

Measures continuous return over time
Use for performance tracking
```

---

## 2. POSITION SIZING

### Kelly Criterion
```
f = (p·b − q) / b

p = win probability
q = 1 − p (loss probability)
b = net odds (decimal odds − 1)
f = fraction of bankroll to bet
f ∈ (0, 1)
```

### Fractional Kelly ⚠️ ALWAYS USE THIS
```
f_final = α · f_kelly
α = 0.25 (default for all markets)

⚠️ NEVER use full Kelly (α = 1.0)
⚠️ NEVER use full Kelly on 5-min markets!
Fractional Kelly reduces variance significantly
```

### Value at Risk 95%
```
VAR = μ − 1.645 · σ

μ = mean daily return
σ = standard deviation of returns
Max daily loss at 95% confidence level
```

### Conditional VaR (CVaR)
```
CVaR = E[loss | loss > VaR]

Expected loss in worst-case scenarios
More conservative than VaR
Use for tail risk assessment
```

### Volatility Scaling
```
w = target_vol / realized_vol

Adjust position size to control risk
Scale down when volatility is high
Scale up when volatility is low
```

---

## 3. RISK METRICS

### Max Drawdown (MDD)
```
MDD = (Peak − Trough) / Peak

Peak = highest portfolio value
Trough = lowest value after peak
Block new trades if MDD > 8%
```

### Downside Deviation
```
σ_d = √E[min(R − τ, 0)²]

τ = minimum acceptable return (MAR)
Focuses only on negative volatility
Used in Sortino ratio calculation
```

### Correlation Check
```
Max correlated exposure = 40% of bankroll

If two markets move together:
combined_exposure < 0.40 × bankroll
```

---

## 4. PERFORMANCE METRICS

### Sharpe Ratio
```
SR = (ER − RF) / σ(R)

ER = expected portfolio return
RF = risk-free rate
σ(R) = standard deviation of returns
Target: SR > 2.5
Healthy: SR > 1.5
```

### Sortino Ratio
```
Sortino = (ER − RF) / σ_d

σ_d = downside deviation only
Better than Sharpe for asymmetric returns
Target: Sortino > 2.0
```

### Profit Factor
```
PF = gross_profit / gross_loss

Target: PF > 1.5
Healthy bot maintains PF > 1.5
PF < 1.0 = losing strategy
Review strategy if PF < 1.5
```

### Win Rate
```
WR = winning_trades / total_trades

Target: WR > 70%
Must be combined with avg win/loss ratio
```

### Expectancy
```
E = (WR × avg_win) − ((1 − WR) × avg_loss)

Positive expectancy = profitable system
Most important metric for bot evaluation
```

### Information Ratio
```
IR = (R − B) / σ(R − B)

R = portfolio return
B = benchmark return
σ(R−B) = tracking error
Performance relative to benchmark
```

### Profit Factor
```
PF = gross_profit / gross_loss
Healthy bot: PF > 1.5
```

---

## 5. ARBITRAGE FORMULAS

### Arb Condition Check
```
Σ (1/odds_i) < 1 = profit exists

Sum of reciprocal odds across all outcomes
If sum < 1.0 → arbitrage opportunity
```

### Net Edge After Fees
```
gross_edge = |price_A − price_B|
fees_roundtrip = fee_A + fee_B + est_slippage
net_edge = gross_edge − fees_roundtrip

Only execute if net_edge > MIN_THRESHOLD
MIN_THRESHOLD = 0.02 (2% minimum)
```

### CEX vs Polymarket Lag
```
lag_window = ~500ms

Polymarket price lags CEX by ~500ms
on major crypto events (BTC, ETH)
Window to exploit: <500ms after CEX move
```

### Mispricing Score for Arb
```
S = (p_model − p_market) / σ

S > 2.0 → strong arb signal
Calculate for both platforms
Enter platform with larger S
```

---

## 6. MARKET COST FUNCTION (Polymarket CLOB)

### Generalized Cost Function
```
C(q) = β · ln(Σ e^(qi/2))

β = liquidity sensitivity parameter
  larger β → deeper liquidity, smoother prices
  smaller β → higher price sensitivity to order flow
qi = quantity vector for each outcome
```

### Market Maker Maximum Loss
```
L_max = β · ln(n) / P(D)

n = number of outcomes
Binary market (n=2, β=$80,000):
L_max = 80,000 · ln(2) ≈ $55,451
```

### Cost of a Trade
```
To move outcome i from qi to qi + Δ:
P(H|D1,...,Dt) ≈ P(H) · ∏ P(Dk|H)

Critical properties:
Σ pi = 1 (probabilities sum to 1)
0 < pi < 1 for all i
```

---

## 7. SIGNAL QUALITY METRICS

### Edge Captured
```
edge_captured = actual_return / theoretical_edge

Measures how much of theoretical edge is realized
< 0.5 = execution problems (slippage, timing)
> 0.8 = excellent execution
```

### Signal Decay Rate
```
decay = edge_t / edge_t0

Measures if edge is shrinking over time
< 0.7 after 30 days = strategy needs refresh
```

### Kelly Accuracy
```
kelly_accuracy = actual_f / calculated_f

How close actual sizing was to Kelly optimal
Consistently < 0.8 = sizing too conservative
Consistently > 1.2 = oversizing risk
```

---

## 8. EXECUTION LATENCY TARGETS

```
Component          Mean Target    p99 Target
─────────────────────────────────────────────
Data Ingestion     <100ms         <300ms
Bayesian Update    <20ms          <30ms
EV Calculation     <5ms           <10ms
Order Placement    <500ms         <1000ms  ← bottleneck
─────────────────────────────────────────────
Total Cycle        <1000ms        <1795ms
```

---

## 9. QUICK REFERENCE — THRESHOLDS

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
✓ Max drawdown = 8% → stop all trades
✓ Profit Factor min = 1.5
✓ VAR 95% checked before each order

PERFORMANCE TARGETS:
✓ Win Rate > 70%
✓ Sharpe Ratio > 2.5
✓ Profit Factor > 1.5
✓ Max Drawdown < 5%
✓ Avg Profit/Trade > $15
```

---

*Reference: Quantitative Prediction Market Research v2.3.1*
*Internal use only — AI Trading Team*
