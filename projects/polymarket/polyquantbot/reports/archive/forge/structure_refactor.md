# Structure Refactor Report

**Date:** 2026-04-01  
**By:** FORGE-X

## Old vs New Structure

| Old Location | New Location | Status |
|---|---|---|
| phase8/risk_guard.py | risk/risk_guard.py | Copied |
| phase8/order_guard.py | risk/order_guard.py | Copied |
| phase8/health_monitor.py | risk/health_monitor.py | Copied |
| phase8/position_tracker.py | risk/position_tracker.py | Copied |
| phase8/fill_monitor.py | risk/fill_monitor.py | Copied |
| phase8/exit_monitor.py | risk/exit_monitor.py | Copied |
| phase7/infra/ws_client.py | data/websocket/ws_client.py | Copied |
| phase7/engine/orderbook.py | data/orderbook/orderbook.py | Copied |
| phase7/engine/market_cache_patch.py | data/orderbook/market_cache.py | Copied |
| phase7/analytics/execution_feedback.py | data/ingestion/execution_feedback.py | Copied |
| phase7/analytics/latency_tracker.py | data/ingestion/latency_tracker.py | Copied |
| phase7/analytics/trade_flow.py | data/ingestion/trade_flow.py | Copied |
| signal/signal_engine.py | strategy/base/signal_engine.py | Copied + imports fixed |
| config/live_config.py | infra/live_config.py | Copied + imports fixed |
| config/runtime_config.py | infra/runtime_config.py | Copied |
| phase10/pipeline_runner.py | core/pipeline/pipeline_runner.py | Copied + imports fixed |
| phase10/live_paper_runner.py | core/pipeline/live_paper_runner.py | Copied + imports fixed |
| phase10/run_controller.py | core/pipeline/run_controller.py | Copied |
| phase10/go_live_controller.py | core/pipeline/go_live_controller.py | Copied |
| phase10/execution_guard.py | core/pipeline/execution_guard.py | Copied |
| phase10/capital_allocator.py | core/pipeline/capital_allocator.py | Copied |
| phase10/live_mode_controller.py | core/pipeline/live_mode_controller.py | Copied + imports fixed |
| phase10/arb_detector.py | core/pipeline/arb_detector.py | Copied |
| phase9/telegram_live.py | telegram/telegram_live.py | Copied + imports fixed |
| phase9/metrics_validator.py | monitoring/metrics_validator.py | Copied |
| report/*.md | reports/forge/*.md + reports/sentinel/*.md | Reorganized |

## Layer Separation Result

✅ DATA layer: data/websocket/, data/orderbook/, data/ingestion/
✅ STRATEGY layer: strategy/base/, strategy/implementations/, strategy/features/
✅ INTELLIGENCE layer: intelligence/ (stub)
✅ RISK layer: risk/
✅ EXECUTION layer: execution/ (pre-existing)
✅ MONITORING layer: monitoring/ (pre-existing + metrics_validator added)
✅ PIPELINE layer: core/pipeline/

## Improvements

1. Clear domain separation by responsibility
2. Discoverable module names (risk/ vs phase8/)
3. Pipeline flow matches system architecture document
4. Intelligence layer hook for future ML/Bayesian
5. Backtest placeholder ready for implementation
6. Reports organized by agent type

## Known Issues

1. phase7/core/execution/live_executor.py still used directly — migrate in next phase
2. intelligence/ is stub only
3. backtest/ is placeholder
4. Original phase* folders remain (by design — backward compat)

## Next Step

Phase 11 — Strategy Scaling: implement strategy/implementations/ with 2-3 concrete strategies
