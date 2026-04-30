# 24_13_s3_smart_money_copy_trading

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - strategy trigger layer in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
  - wallet activity input normalization for copy-trading signal evaluation
  - trade signal extraction (quality + strength + conflict detection)
  - decision logic output (`ENTER` / `SKIP`) with required explanation contract
- Not in Scope:
  - execution engine changes
  - risk model changes
  - Telegram UI changes
  - observability redesign
  - wallet scoring system expansion beyond basic filter
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_13_s3_smart_money_copy_trading.md`. Tier: STANDARD

## 1. What was built
- Implemented S3 smart-money/copy-trading strategy path in `StrategyTrigger` as a narrow integration focused on strategy decisioning.
- Added wallet signal input contract:
  - `wallet_address`
  - `action` (buy/sell)
  - `size_usd`
  - `liquidity_usd`
  - `timestamp_ms`
  - `market_move_pct`
  - `wallet_success_rate`
  - `wallet_activity_count`
- Added required output contract:
  - `decision` (`ENTER` or `SKIP`)
  - `reason`
  - `confidence`
  - `wallet_info`
- Implemented filters and skip gates:
  - low-quality wallet
  - late entry
  - conflicting signals
  - insufficient liquidity
  - below-threshold signal strength

## 2. Current system architecture
- `StrategyTrigger.evaluate_smart_money_copy_trading(...)` now runs this deterministic sequence:
  1. Quality gate checks minimum wallet success rate and activity count.
  2. Timing gate rejects late entries when market move already exceeds configured early-entry bound.
  3. Action gate ensures action semantics and detects buy/sell conflicts across related wallet signals.
  4. Liquidity gate enforces minimum market depth via existing strategy liquidity threshold.
  5. Signal-strength scoring combines:
     - position size score
     - early-entry score
     - repeated/aligned wallet behavior score
  6. Final decision gate returns `ENTER` only when confidence exceeds threshold; otherwise returns explicit `SKIP` reason.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_s3_smart_money_copy_trading_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_13_s3_smart_money_copy_trading.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
- Required behavior tests implemented and passing:
  1. high-quality wallet → triggers entry
  2. low-quality wallet → skipped
  3. late entry → skipped
  4. conflicting signals → skipped
  5. valid early signal → ENTER
- Output contract confirmed in tests (`decision`, `reason`, `confidence`, `wallet_info`).

Test evidence:
- `python -m py_compile projects/polymarket/polyquantbot/execution/strategy_trigger.py projects/polymarket/polyquantbot/tests/test_s3_smart_money_copy_trading_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_s3_smart_money_copy_trading_20260409.py` ✅ (5 passed)
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_s1_breaking_news_momentum_strategy_20260409.py projects/polymarket/polyquantbot/tests/test_s2_cross_exchange_arbitrage_20260409.py projects/polymarket/polyquantbot/tests/test_s3_smart_money_copy_trading_20260409.py` ✅ (16 passed)

Runtime proof examples:

1) Example wallet signal input
```text
wallet_address=0xsmart1
action=buy
size_usd=18000
liquidity_usd=40000
timestamp_ms=1746000000000
market_move_pct=0.004
wallet_success_rate=0.71
wallet_activity_count=28
```

2) Example entry decision
```text
input:
- anchor signal from 0xsmart1 (BUY)
- two additional aligned BUY wallet signals in last 30m
- size is large, move is early, liquidity >= 10000
output:
- decision=ENTER
- reason="high-quality early smart-money signal"
- confidence=0.94
- wallet_info includes wallet_address/action/success_rate/activity_count/size_usd/aligned_wallets
```

3) Example skip decision
```text
input:
- anchor BUY signal and mixed BUY/SELL related signals inside 30m window
output:
- decision=SKIP
- reason="conflicting signals"
- confidence=0.0
- wallet_info includes buy_votes/sell_votes
```

## 5. Known issues
- This is narrow strategy-trigger integration only and is not yet wired to execution orchestration.
- Wallet quality filtering is intentionally basic for this scope (success rate + activity count only); advanced scoring remains out of scope.
- Existing environment warning remains unchanged: pytest reports `Unknown config option: asyncio_mode` while tests still pass.

## 6. What is next
- Codex auto PR review on changed files and direct dependencies.
- COMMANDER review for STANDARD-tier merge/hold decision.
