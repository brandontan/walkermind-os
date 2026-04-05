# 11_1_execution_engine

## 1. What was built

- Implemented a new paper-trading `ExecutionEngine` with core position lifecycle methods: `open_position`, `close_position`, and `update_mark_to_market`.
- Added a dedicated `Position` model for execution state tracking (`market_id`, `side`, `entry_price`, `current_price`, `size`, `pnl`).
- Added a simple rules-based `StrategyTrigger` that opens positions under a threshold and closes them above a PnL target.
- Integrated simulated execution snapshots into Telegram `portfolio_service` so positions/equity/pnl can render even when full runtime engines are not injected.
- Added minimal Telegram command integration: `/trade test` path now executes a sample paper trade and returns positions UI payload.

## 2. Architecture

```text
Telegram /trade command
  -> CommandHandler._handle_trade_test()
     -> execution.strategy_trigger.StrategyTrigger
        -> execution.engine.ExecutionEngine
           - open_position (risk gated)
           - update_mark_to_market (unrealized pnl)
           - close_position (realized pnl)
     -> execution.engine.export_execution_payload()
     -> telegram.handlers.portfolio_service.update_simulated_state()
     -> interface.telegram.view_handler.render_view("positions", payload)
```

Risk flow:
- per-position check: size <= 10% equity
- aggregate check: total exposure <= 30% equity
- paper mode only: no external order submission / API execution

## 3. Files changed

- `PROJECT_STATE.md`
- `projects/polymarket/polyquantbot/execution/models.py` (new)
- `projects/polymarket/polyquantbot/execution/engine.py` (new)
- `projects/polymarket/polyquantbot/execution/strategy_trigger.py` (new)
- `projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py`
- `projects/polymarket/polyquantbot/telegram/command_handler.py`
- `projects/polymarket/polyquantbot/reports/forge/11_1_execution_engine.md` (new)

## 4. What is working

- Can open position in paper engine when risk limits pass.
- Can close position and realize PnL.
- Mark-to-market updates unrealized PnL and equity.
- Risk controls block over-sized or over-exposed execution requests.
- `/trade test` command path triggers a sample paper execution flow and returns positions payload for UI rendering.
- No external order/API calls are made by this engine path.

Validation performed:
- Python compile check for all touched modules.
- Engine lifecycle smoke test (open -> mtm -> close).
- Risk rule smoke test (10% max position, 30% max total exposure).

## 5. Issues / edge cases

- `CommandRouter` currently parses command args as numeric only; `/trade test` routes as `trade` command with no string arg, so test flow is bound to `/trade` command path behavior.
- Existing repository still contains historical phase-references in unrelated files; no new phase folders/imports were introduced by this task.
- This increment does not replace existing `PaperEngine`; execution engine v1 is introduced as paper-trading core module for incremental integration.

## 6. Next

- Wire `ExecutionEngine` into callback/menu handlers for explicit open/close test actions and richer execution telemetry.
- Add dedicated unit tests for `ExecutionEngine` and `StrategyTrigger` under `projects/polymarket/polyquantbot/tests/`.
- Extend `/trade` command parsing to support subcommands (`/trade test`, `/trade close`, `/trade status`) with string argument support.
- SENTINEL validation required for execution engine v1 before merge.
  Source: `projects/polymarket/polyquantbot/reports/forge/11_1_execution_engine.md`
