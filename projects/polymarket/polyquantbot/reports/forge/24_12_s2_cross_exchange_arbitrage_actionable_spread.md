# 24_12_s2_cross_exchange_arbitrage_actionable_spread

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - strategy trigger layer in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
  - market data normalization for cross-exchange probability comparison
  - cross-market comparison logic for Polymarket↔Kalshi equivalence path
  - fee/slippage-adjusted edge calculation and actionable-spread gate
- Not in Scope:
  - execution engine changes
  - risk model changes
  - order placement logic
  - Telegram UI changes
  - observability redesign
  - exchange API integration expansion
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_12_s2_cross_exchange_arbitrage_actionable_spread.md`. Tier: STANDARD

## 1. What was built
- Extended S2 narrow integration with an explicit actionable spread filter before fee/slippage adjustment:
  - Added `StrategyConfig.cross_exchange_min_actionable_spread`.
  - Added skip path: `reason="spread not actionable"` when raw spread is too small to be operationally meaningful.
- Preserved existing S2 output contract with `decision`, `edge`, `reason`, and `matched_markets_info`.
- Added focused regression test for actionable-spread skip behavior.

## 2. Current system architecture
- `StrategyTrigger` now evaluates S2 in this order:
  1. Select equivalent Kalshi market and confidence score.
  2. Skip on no match / low mapping confidence.
  3. Normalize both exchanges to probability space (0–1).
  4. Compute `raw_edge = abs(prob_poly - prob_kalshi)`.
  5. Skip when spread is not actionable (`raw_edge < cross_exchange_min_actionable_spread`).
  6. Subtract total fees/slippage (bps → probability) to compute net edge.
  7. Enforce liquidity and net-edge threshold for ENTER/SKIP decision.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_s2_cross_exchange_arbitrage_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_12_s2_cross_exchange_arbitrage_actionable_spread.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
- Required S2 contract remains intact:
  - `decision: ENTER | SKIP`
  - `edge: float`
  - `reason: str`
  - `matched_markets_info: dict`
- Required requested behavior remains covered:
  1. matched markets → edge detected
  2. no match → skipped
  3. edge < threshold → skipped
  4. fees reduce edge → skipped
  5. valid arbitrage → ENTER
- Additional guard now covered:
  - non-actionable raw spread → skipped with explicit reason.

Test evidence:
- `python -m py_compile projects/polymarket/polyquantbot/execution/strategy_trigger.py projects/polymarket/polyquantbot/tests/test_s2_cross_exchange_arbitrage_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_s2_cross_exchange_arbitrage_20260409.py` ✅ (6 passed)

Runtime proof examples:
1) Example matched markets
```text
input:
- Polymarket: poly-btc-60k, prob=0.64
- Kalshi: KXBTCAPR60, prob=0.58
- fees/slippage total: 33 bps
output:
- decision=ENTER
- edge=0.0567
- reason="cross-exchange arbitrage opportunity detected"
- matched_markets_info includes polymarket/kalshi ids and mapping_confidence
```

2) Example arbitrage opportunity
```text
input:
- equivalent event_key/timeframe/resolution_criteria
- liquidity on both exchanges >= 10,000
- net edge > 2%
output:
- decision=ENTER
- edge>0.02
```

3) Example skipped case
```text
input:
- Polymarket prob=0.6200, Kalshi prob=0.6210
- raw edge=0.0010 (< actionable spread gate 0.0050)
output:
- decision=SKIP
- reason="spread not actionable"
- edge=0.0
```

## 5. Known issues
- Existing pytest warning remains unchanged in this environment: `Unknown config option: asyncio_mode`.
- S2 remains narrow integration in strategy trigger only; execution/risk/runtime orchestration wiring is intentionally out of scope.

## 6. What is next
- Codex auto PR review on changed files and direct dependencies.
- COMMANDER review for STANDARD-tier merge/hold decision.
