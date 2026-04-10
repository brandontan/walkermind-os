# 24_50_public_account_wallet_foundation_v1

## Validation metadata
- Validation Tier: MAJOR
- Claim Level: FOUNDATION
- Validation Target:
  1. Durable persistence schema coverage for `users`, `trading_accounts`, `api_credentials`, `risk_profiles`, and `trade_intents`.
  2. Runtime-safe account envelope resolution for active account, mode (`paper`, `live_shadow`, `live`), wallet/auth metadata, and bound risk profile.
  3. Existing StrategyTrigger → ExecutionEngine proof-verified path unchanged for current runtime behavior.
  4. Narrow integration to persist strategy decisions as `trade_intents` without replacing execution truth semantics.
  5. Fail-closed behavior for invalid mode / missing live auth metadata.
- Not in Scope:
  - Deposit/withdraw/bridge UX and wallet product flows.
  - Full per-user live order submission routing.
  - Orders/fills/positions public persistence surface.
  - Credential vault hardening beyond placeholder credential reference slot.
- Suggested Next Step: SENTINEL validation required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_50_public_account_wallet_foundation_v1.md`. Tier: MAJOR.

## 1. What was built
- Added public-account foundation schema contracts in DB layer for:
  - `users`
  - `risk_profiles`
  - `trading_accounts`
  - `api_credentials`
  - `trade_intents`
- Added migration artifact at:
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/db/migrations/20260410_public_account_wallet_foundation_v1.sql`
- Added runtime account envelope module:
  - `AccountRuntimeResolver` for fail-closed mode/account/auth/risk-profile resolution
  - `TradeIntentWriter` for strategy-decision persistence boundary
- Added narrow StrategyTrigger integration:
  - Optional account resolver check before execution submission
  - Optional trade-intent write on validated decision path
  - Preserved existing execution proof generation and engine-boundary verification flow

## 2. Current system architecture
1. StrategyTrigger computes decision and pre-trade validation exactly as before.
2. If account resolver is configured:
   - resolve active envelope for user/account
   - fail closed on invalid mode / missing account / missing live auth metadata / missing risk profile
3. If trade-intent writer is configured:
   - persist decision intent (`trade_intents`) as auditability boundary record
4. Build execution validation proof and submit `open_position(...)` through existing authoritative path.
5. Execution truth remains owned by ExecutionEngine + downstream trade lifecycle, while `trade_intents` stays decision-level persistence.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/db/database.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/account_runtime.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/db/migrations/20260410_public_account_wallet_foundation_v1.sql`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_public_account_wallet_foundation_v1_20260410.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_50_public_account_wallet_foundation_v1.md`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/PROJECT_STATE.md`

## 4. What is working
- DB schema includes durable foundation entities for public account runtime.
- Account runtime envelope resolves and validates allowed mode set (`paper`, `live_shadow`, `live`).
- Resolver rejects invalid mode and missing live credential reference in `live` mode.
- StrategyTrigger can record trade intents as decision persistence without replacing execution-proof boundary behavior.
- Existing StrategyTrigger execution path still opens positions through proof-aware `ExecutionEngine.open_position(...)`.

## 5. Validation commands
- `python -m py_compile /workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/account_runtime.py /workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/db/database.py /workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/strategy_trigger.py /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_public_account_wallet_foundation_v1_20260410.py`
- `PYTHONPATH=/workspace/walker-ai-team pytest -q /workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_public_account_wallet_foundation_v1_20260410.py`

## 6. Known issues
- Existing environment warning may still appear in pytest (`Unknown config option: asyncio_mode`) and is non-blocking for scoped task verification.
- API credential secret hardening remains placeholder/reference only by design in this foundation phase.

## 7. Suggested next step
- Phase 2: `public execution account binding v1`
  - add orders/fills/positions schema
  - add paper/live_shadow execution adapters
  - prepare live-capable per-account execution path

## 8. What is next
- SENTINEL MAJOR validation on declared target scope before merge.
