# 24_24_tg2_tg3_open_positions_trade_history

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - portfolio view handler (`projects/polymarket/polyquantbot/interface/telegram/view_handler.py`)
  - UI formatter (`projects/polymarket/polyquantbot/interface/ui_formatter.py`)
  - trade storage / retrieval layer (`projects/polymarket/polyquantbot/execution/engine.py`, `projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py`, `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`)
- Not in Scope:
  - execution engine decision/routing logic changes
  - strategy logic changes
  - sizing / risk behavior changes
  - observability redesign
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_24_tg2_tg3_open_positions_trade_history.md`. Tier: STANDARD

## 1. What was built
- Added explicit closed-trade persistence in execution payload export (`closed_trades`) and wired it into Telegram portfolio state ingestion.
- Extended portfolio state contracts to carry open-position detail fields needed for strict card rendering (`position_id`, `opened_at`, `current_price`) and closed-trade rows for history rendering.
- Updated callback router normalization so Telegram portfolio payload always includes both open positions and closed trade history datasets.
- Updated view adapter to normalize/sort open positions and closed trades newest-first before rendering.
- Updated formatter to render:
  - open positions as separate strict-format cards,
  - same-market multiple positions without overwrite (distinct refs/entries preserved),
  - trade history section after open positions,
  - empty states (`No open positions`, `No trade history yet`),
  - history cap (`TRADE_HISTORY_LIMIT = 10`) for message-size safety.
- Added focused tests covering required TG-2/TG-3 behavior and formatting constraints.

## 2. Current system architecture
Touched rendering/storage flow now resolves as:
1. `execution.engine.ExecutionEngine.close_position(...)` appends structured closed-trade records to in-memory execution state.
2. `execution.engine.export_execution_payload()` exports both open positions and closed trades.
3. `telegram.handlers.portfolio_service.PortfolioService.merge_execution_state(...)` normalizes and stores open/closed datasets.
4. `telegram.handlers.callback_router.CallbackRouter._build_normalized_payload(...)` includes both datasets in callback payloads.
5. `interface.telegram.view_handler._derive_position_metrics(...)` and `_trade_history_rows(...)` canonicalize data and enforce newest-first ordering.
6. `interface.ui_formatter.render_dashboard(mode="positions")` renders open-position cards first, then trade history, with strict format and empty-state logic.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/engine.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/portfolio_service.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/command_handler.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/ui_formatter.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_tg_open_positions_trade_history_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_24_tg2_tg3_open_positions_trade_history.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
- All open positions render with one card per position (no truncation in formatter path).
- Same-market multi-position rows remain distinct by entry/ref fields and are rendered independently.
- Closed trades render in `📜 Trade History` with required fields and WIN/LOSS classification.
- Ordering is enforced newest-first for both open positions and closed trades.
- Empty states are explicit:
  - `No open positions`
  - `No trade history yet`
- Performance guard is active via history display cap (`TRADE_HISTORY_LIMIT = 10`).

Runtime proof samples:

1) Multiple open positions (newest first)
```text
🎯 Position
|- Market: Will BTC close above 120k?
|- Side: NO
|- Entry: 52.00¢
|- Now: 49.00¢
|- Size: $80.00
|- UPNL: +2.40
|- Opened: Apr 9, 10:03 UTC
|- Status: Monitoring
|- Ref: p2
```

2) Trade history section
```text
📜 Trade History

🏁 Closed Trade
|- Market: Will CPI print under 2.5%?
|- Side: YES
|- Entry: 40.00¢
|- Exit: 55.00¢
|- PnL: +15.00
|- Result: WIN
|- Closed: Apr 9, 10:05 UTC
```

3) Empty states
```text
No open positions
No trade history yet
```

## 5. Known issues
- TG-2/TG-3 history path is currently scoped to Telegram portfolio rendering flow only (narrow integration); broader analytics/history surfaces remain out of scope.
- Existing pytest warning persists in environment: `Unknown config option: asyncio_mode`.

## 6. What is next
- Codex auto PR review on changed files and direct dependencies.
- COMMANDER review for STANDARD-tier merge/hold decision.

Report: projects/polymarket/polyquantbot/reports/forge/24_24_tg2_tg3_open_positions_trade_history.md
State: PROJECT_STATE.md updated
