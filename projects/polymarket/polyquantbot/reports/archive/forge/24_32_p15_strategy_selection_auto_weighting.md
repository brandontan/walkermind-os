# 24_32_p15_strategy_selection_auto_weighting

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - S4 decision weighting logic
  - integration with P14 analytics
- Not in Scope:
  - execution logic changes
  - risk model changes
  - ML models
  - external integrations
- Suggested Next Step: Auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_32_p15_strategy_selection_auto_weighting.md`. Tier: STANDARD

## 1. What was built
- Implemented dynamic strategy auto-weighting in S4 path using post-trade analytics from P14 (`summary()` inputs + deterministic normalization).
- Added scoring model `score = f(pnl, win_rate, expectancy, edge_captured)` and converted normalized scores into bounded base weights (`0.5` to `1.5`).
- Added smoothing limits to prevent abrupt shifts (`±0.12` on base transition, `±0.149` on final transition).
- Added regime-based adjustment layer (P11 context) applied as `final_weight = base_weight × regime_modifier` with confidence-gated neutral fallback.
- Integrated weights into S4 candidate scoring as multiplicative influence only (does not bypass/override decision contract).
- Exposed output `strategy_weights` in S4 aggregation decision payload with keys: `S1`, `S2`, `S3`, `S5`, `FALCON`.

## 2. Current system architecture
- `execution/strategy_trigger.py`
  - New helpers for default weights, regime modifier map, and dynamic weight computation.
  - Pulls analytics via `engine.get_analytics().summary()` (P14 integration source).
  - Computes per-strategy raw score from normalized PnL + win rate + global expectancy + global edge-captured.
  - Converts normalized scores to base weights (`0.5..1.5`), applies smoothing, then regime adjustment with bounded caps.
  - Injects `strategy_weight` into `_build_strategy_candidate_score` so S4 final candidate score is influenced but still bounded and deterministic.
- `tests/test_p15_strategy_auto_weighting_20260409.py`
  - Focused STANDARD-tier tests validating strong/weak weighting, regime effects, deterministic output, and anti-jump safety.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_p15_strategy_auto_weighting_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_32_p15_strategy_selection_auto_weighting.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
### Required tests
- strong strategy gets higher weight: pass
- weak strategy reduced: pass
- regime modifies weights: pass
- deterministic outputs: pass
- no extreme jumps: pass

### Validation commands
- `python -m py_compile projects/polymarket/polyquantbot/execution/strategy_trigger.py projects/polymarket/polyquantbot/tests/test_p15_strategy_auto_weighting_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_p15_strategy_auto_weighting_20260409.py` ✅ (`5 passed`)
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_s4_strategy_aggregation_prioritization_20260409.py projects/polymarket/polyquantbot/tests/test_p14_1_system_optimization_from_analytics_20260409.py` ✅ (`13 passed`)

### Runtime proof (required)
1) Weight distribution example
- Baseline computed weights:
  - `S1=1.12`, `S2=0.88`, `S3=1.109023`, `S5=1.078947`, `FALCON=1.12`

2) Before/after comparison
- Candidate score comparison (same S1/S2/S3 signals):
  - Before (baseline weighting): `S1=0.4816`, `S2=0.3784`, `S3=0.365978`
  - After (NEWS_DRIVEN regime weighting): `S1=0.643891`, `S2=0.29547`, `S3=0.323378`
- Result: stronger analytics-aligned strategy receives higher influence while weak strategy influence is reduced.

3) Regime-based adjustment example
- `NEWS_DRIVEN`: `FALCON=1.207895`, `S5=1.132895`
- `LOW_ACTIVITY_CHAOTIC`: `FALCON=1.125`, `S5=1.025`
- Demonstrates P11 regime context modifying final weights while respecting smoothing and bounds.

## 5. Known issues
- P15 weighting is NARROW integration in S4 decision path only; it does not yet propagate to non-S4 orchestration/reporting surfaces.
- Existing pytest warning remains in this environment: `Unknown config option: asyncio_mode`.

## 6. What is next
- Auto PR review + COMMANDER review required before merge.
- Optional next increment (if requested): expose `strategy_weights` telemetry to monitoring/dashboard surfaces for operator observability.

Report: projects/polymarket/polyquantbot/reports/forge/24_32_p15_strategy_selection_auto_weighting.md
State: PROJECT_STATE.md updated
