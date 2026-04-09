# 24_16_p8_portfolio_exposure_balancing_correlation_guard

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - post-S4 selection layer in `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
  - pre-execution validation path before `open_position(...)`
  - portfolio state inspection from execution snapshot open positions + exposure totals
- Not in Scope:
  - execution engine changes
  - risk model redesign
  - strategy logic changes
  - Telegram UI changes
  - observability redesign
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_16_p8_portfolio_exposure_balancing_correlation_guard.md`. Tier: STANDARD

## 1. What was built
- Added lightweight portfolio exposure + correlation guard at post-S4, pre-execution stage in strategy trigger.
- Introduced `PortfolioExposureDecision` contract with required outputs:
  - `final_decision` (`ENTER` / `SKIP` / `REDUCE`)
  - `adjusted_size`
  - `reason`
  - `flags`
- Implemented portfolio snapshot consumption from execution snapshot:
  - open positions
  - market identifiers (`market_id`)
  - inferred themes (`theme` / `event_key` / `category` if available)
  - total exposure aggregation
- Added correlation handling:
  - same market: block
  - same theme cap: reduce/skip based on available headroom
  - highly similar market condition (token-overlap heuristic): reduce with correlation factor
- Integrated guard decision into `evaluate(...)` before `open_position(...)`.

## 2. Current system architecture
1. S4 produces `StrategyAggregationDecision` with selected candidate and metadata.
2. Existing P7 sizing computes `proposed_size` from edge/confidence and total exposure budget.
3. New portfolio guard resolves target market/theme context from selected candidate metadata.
4. Guard inspects current snapshot open positions and evaluates:
   - duplicate same-market exposure (hard block)
   - total exposure cap headroom
   - per-theme exposure cap
   - high market-id similarity overlap
5. Guard emits deterministic `PortfolioExposureDecision`.
6. Runtime behavior:
   - `SKIP` → evaluate returns `BLOCKED`
   - `REDUCE` → execution continues with reduced `adjusted_size`
   - `ENTER` → execution continues with original validated size

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Added: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_p8_portfolio_exposure_balancing_correlation_guard_20260409.py`
- Added: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_16_p8_portfolio_exposure_balancing_correlation_guard.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
- Same-market duplication is blocked before execution.
- Similar/high-overlap market conditions are reduced by deterministic correlation reduction factor.
- Total exposure cap is enforced in guard path even when candidate passes signal checks.
- Diversified positions pass guard and continue execution.
- Deterministic behavior verified for identical inputs.

### Correlation handling examples
1) Same market block
- Existing: `election-2026-winner`
- Candidate: `election-2026-winner`
- Output: `final_decision=SKIP`, reason `correlated exposure: same market already open`

2) High-similarity reduction
- Existing: `btc-hit-100k-2026`
- Candidate: `btc-will-hit-100k-in-2026`
- Output: `final_decision=REDUCE`, flag `high_similarity_reduce`

### Exposure enforcement proof
- Total capital `10,000`, exposure cap ratio `30%` ⇒ cap `3,000`
- Current exposure `2,700`
- Candidate proposed size `900`
- Guard output: `final_decision=REDUCE`, `adjusted_size=300.0`

### Runtime proof (required)
1) Trade blocked due to correlation
- `evaluate(...)` outcome: `BLOCKED` when same market already open.

2) Trade reduced due to exposure
- `evaluate(...)` outcome: `OPENED` with reduced size `300.0` under capped headroom.

3) Normal trade allowed
- `evaluate(...)` outcome: `OPENED` with positive non-zero size for diversified portfolio.

### Test evidence
- `python -m py_compile projects/polymarket/polyquantbot/execution/strategy_trigger.py projects/polymarket/polyquantbot/tests/test_p8_portfolio_exposure_balancing_correlation_guard_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_p8_portfolio_exposure_balancing_correlation_guard_20260409.py projects/polymarket/polyquantbot/tests/test_p7_capital_allocation_position_sizing_20260409.py` ✅ (`14 passed`, 1 known pytest warning)

## 5. Known issues
- P8 guard currently uses lightweight similarity heuristics over market-id tokens and available metadata; no external correlation matrix integration is included in this scope.
- Theme detection depends on available metadata/position attributes (`theme` / `event_key` / `category`) and falls back to non-theme checks when absent.
- Repository pytest warning `Unknown config option: asyncio_mode` remains present but non-blocking for focused tests.

## 6. What is next
- COMMANDER review (STANDARD tier handoff with Codex auto PR review baseline).
