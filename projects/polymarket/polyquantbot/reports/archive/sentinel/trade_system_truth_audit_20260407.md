# SENTINEL TRADE SYSTEM TRUTH AUDIT — 2026-04-07

## 1. Target

- Role: **SENTINEL**
- Intent: **Trade System Truth Audit** (paper-trade readiness map)
- Branch context: current worktree state after Telegram scope hardening / premium-nav decision line.
- Audit sources loaded:
  - `/workspace/walker-ai-team/PROJECT_STATE.md`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/telegram_premium_nav_ux_20260407.md`
  - `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/sentinel/telegram_menu_scope_hardening_validation_20260407.md`
  - code paths under `/workspace/walker-ai-team/projects/polymarket/polyquantbot/`

---

## 2. Current architecture truth

### 2.1 Actual runtime paper path in current main entrypoint

Current `main.py` starts **two concurrent pipelines**:

1) `LivePaperRunner` WS path (`runner.run()`):
- real WS ingest → orderbook cache → optional `decision_callback` → `ExecutionGuard` + `RiskGuard` → `ExecutionSimulator` (paper live sim only).`
- This path updates observation metrics and Telegram alerts, not wallet/positions DB state used by trading loop. Evidence: `main.py` starts `runner.run()` as `pipeline_task`.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/main.py:703-715】

2) `run_trading_loop()` polling path:
- REST `get_active_markets` → `apply_market_scope` → `ingest_markets` → `generate_signals` → execution (`PaperEngine` when provided) → DB upsert/insert/update + PositionManager + PnLTracker + Telegram + validation hooks. Evidence: same file starts `run_trading_loop` in parallel task with `paper_engine=engine_container.paper_engine`.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/main.py:720-733】

### 2.2 Ownership map by module (actual code ownership)

- **Signal generation**: `core/signal/signal_engine.py` via `generate_signals` and optional synthetic fallback.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/signal/signal_engine.py:183-599】
- **Intelligence (market typing/tagging)**: `strategy/market_intelligence.py` invoked as shadow analysis in trading loop before signal generation; no direct decision gating by default.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:874-904】
- **Risk checks (trading_loop path)**: mostly signal/executor thresholds (edge/size/liquidity/concurrency/cooldown). No direct `RiskGuard` integration in this path.
- **Execution**:
  - paper canonical path in trading loop: `execution/paper_engine.py` via `paper_engine.execute_order`.
  - fallback/live branch: `core/execution/executor.py`.
- **Position state**:
  - paper canonical: `core/positions.py` (`PaperPositionManager`) through `PaperEngine`.
  - separate in-memory tracker: `core/portfolio/position_manager.py` updated independently in trading loop.
- **PnL/account state**:
  - wallet/account: `core/wallet_engine.py` via `PaperEngine`.
  - trade PnL records: DB `trades` + `core/portfolio/pnl.py` + `monitoring/pnl_calculator.py` tick aggregation.
- **Monitoring/logging**:
  - structured logs throughout both pipelines.
  - LivePaperRunner has explicit metrics validator/activity monitor snapshots.
  - trading_loop uses validation/performance/snapshot hooks + Telegram notifications.

### 2.3 Does any execution path bypass risk?

**Yes — critical finding.**

- `run_trading_loop` does not import or use `RiskGuard`; it calls execution directly.
- `execute_trade` supports `kill_switch_active`, but trading loop does not pass it (default remains `False`).【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/execution/executor.py:170-181】【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:1154-1158】
- Daily loss / drawdown hard-stop enforcement (`RiskGuard.check_daily_loss`, `check_drawdown`) is not wired on this primary paper-trade loop.

### 2.4 Does monitoring receive events from each stage?

- **Partial only**. Logs exist for each major stage, and LivePaperRunner metrics track WS simulation path.
- No single unified event bus proving all DATA→STRATEGY→INTELLIGENCE→RISK→EXECUTION→MONITORING stages are consistently emitted and reconciled across both concurrent pipelines.
- Risk stage observability is incomplete in trading_loop because formal `RiskGuard` stage is absent.

---

## 3. Order lifecycle truth

### 3.1 Real order lifecycle in paper mode (trading_loop + PaperEngine path)

1. Signal created (`SignalResult`) in `generate_signals`.
2. Trading loop applies per-tick guards (max open positions + cooldown).
3. Order intent is constructed inline dict and sent to `paper_engine.execute_order`.
4. Paper engine validates, dedups by `trade_id`, checks wallet cash, simulates partial fill/slippage, locks funds, opens position, writes ledger entry.
5. Trading loop maps `PaperOrderResult` back into `TradeResult`.
6. Trading loop persists to DB (`positions` and `trades` tables), updates in-memory `PositionManager`, updates `PnLTracker`, sends Telegram.
7. Later close pipeline (TP/SL) calls `paper_engine.close_order`, updates DB trade status and position deletion, persists wallet.

Evidence chain:
- Intent + execution call path.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:1079-1128】
- Persistence + state mutation path.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:1215-1294】
- Paper engine internals (validate→wallet→position→ledger).【/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/paper_engine.py:162-357】
- Close path with wallet settle and ledger close.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/paper_engine.py:404-517】

### 3.2 Separation quality: signal vs intent vs execution vs state mutation

- **Signal vs intent**: clear enough (`SignalResult` then order dict creation).
- **Execution result vs state mutation**: mixed.
  - `PaperEngine` mutates wallet/positions/ledger first.
  - trading_loop then separately mutates DB positions/trades + separate `PositionManager` + `PnLTracker`.
- Result: lifecycle is split across multiple stores/managers, increasing drift risk.

### 3.3 State transition explicitness

- Explicit statuses exist in DB (`open/closed`), `PaperPosition` (`OPEN/CLOSED`), and ledger actions (`OPEN/PARTIAL/CLOSE`).
- But transitions are **distributed**, not atomically coordinated across all stores.

### 3.4 Retries/idempotency/dedup safety

- Present, but fragmented:
  - `core/execution/executor` uses `_submitted_ids` in-memory dedup (lost on restart).【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/execution/executor.py:143-149】
  - `PaperEngine` dedup by processed trade_ids in-memory (lost on restart unless reconstructed indirectly via restored components).【/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/paper_engine.py:131-133】【/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/paper_engine.py:191-208】
  - DB `insert_trade` and `insert_ledger_entry` are idempotent (`ON CONFLICT DO NOTHING`).【/workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/db/database.py:329-358】【/workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/db/database.py:697-703】

Runtime proof (local harness): duplicate `trade_id` returns duplicate reason and no second fill mutation from PaperEngine.
- command run: `PYTHONPATH=/workspace/walker-ai-team python - <<'PY' ...` with repeated `trade_id="t1"`
- observed output: `RESULT2_DUP ... duplicate_trade_id` with zero second fill.

---

## 4. Failure modes and drift risks

## 4.1 Critical risks

1) **Risk layer bypass on active trading loop path (critical)**
- trading_loop executes trades without `RiskGuard` kill-switch/daily-loss/drawdown checks.
- This violates required RISK-before-EXECUTION architecture for that path.
- Evidence: no `RiskGuard` usage in `trading_loop.py`; direct execution calls used instead.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:986-1160】

2) **Silent exception swallowing in close alert path (critical reliability finding)**
- explicit `except Exception: pass` in close alert sends (paper + live close branches).【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:1500-1509】【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:1587-1596】
- Violates “zero silent failures” rule and hides alert-delivery failures.

3) **Startup recovery mismatch bug in engine container (critical reconciliation risk)**
- `EngineContainer.restore_from_db` calls `await self.wallet.restore_from_db(db)` but `restore_from_db` is a classmethod returning a *new* `WalletEngine`; returned object is ignored.
- Effect: persisted wallet may not actually be loaded into container wallet instance used at runtime.
- Evidence:
  - call site ignoring return value.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/engine_router.py:96-99】
  - wallet method returns new engine instance.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/wallet_engine.py:365-406】

## 4.2 High risks

4) **Dual position state owners can drift**
- `PaperPositionManager` (engine_container) and `PositionManager` (core/portfolio) both updated in trading loop with different schemas/lifecycles.
- Divergence between Telegram portfolio/exposure views and trade accounting is possible if one write fails.

5) **Order success but downstream state updates can partially fail**
- after execution success, DB/position/pnl writes are not transactionally bound.
- Several post-fill steps can fail independently (logged warning/error), causing partial state.
- Example: wallet/position persistence errors are logged and loop continues.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:1139-1150】

6) **In-memory dedup scopes reset on restart**
- `_submitted_ids` / `_processed_trade_ids` / `_seen_trade_ids` use process memory; restart can replay signals if upstream identifiers repeat.

## 4.3 Medium risks

7) **Paper duplicate return semantics are ambiguous**
- duplicate order returns `status=FILLED` with `filled_size=0.0` and reason `duplicate_trade_id`, which can mislead downstream status-only consumers.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/execution/paper_engine.py:198-208】

8) **LivePaperRunner risk checks use synthetic PnL=0.0**
- daily-loss guard receives `current_pnl = 0.0` in paper sim runner path, so loss protection is observational rather than true accounting. 【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/live_paper_runner.py:681-686】

9) **Async background validation hooks are fire-and-forget**
- validation updates use `asyncio.create_task(...)`; failures are logged inside hook, but orchestration ordering is non-deterministic vs trade status updates.【/workspace/walker-ai-team/projects/polymarket/polyquantbot/core/pipeline/trading_loop.py:1361-1363】

---

## 5. Paper vs live divergence

### Paper-only behaviors currently in use

- PaperEngine simulates fills (partial %, slippage, latency) without exchange acknowledgment lifecycle.
- TP/SL close in trading_loop directly closes paper positions and updates DB locally.
- LivePaperRunner always runs simulator and blocks real order placement by design.

### Divergences likely to fail at real-wallet cutover

1. Real exchange order lifecycle (`accepted/partial/cancel/reject/fill`) not reflected by paper shortcut path.
2. Reconciliation across wallet/positions/trades/ledger under network failures is not end-to-end proven.
3. RiskGuard not enforced on trading_loop path; live enablement would expose hard safety gap.
4. Idempotency not globally persistent (restart replay risk).
5. Two concurrent pipelines (`runner.run` and `run_trading_loop`) can create observability/accounting mismatch at production scale.

---

## 6. Recommended next hardening scope

1) **Unify risk gating on trading_loop path (P0, blocking real wallet)**
- enforce RiskGuard checks (kill switch, daily loss, drawdown, exposure) directly before every execution attempt.
- ensure execution APIs receive authoritative kill-switch flag.

2) **Reconciliation contract hardening (P0)**
- define single source of truth for positions/account (or explicit reconciliation loop) between:
  - PaperEngine wallet/positions/ledger
  - DB trades/positions/wallet snapshots
  - PositionManager + PnLTracker overlays

3) **Fix recovery semantics (P0)**
- correct wallet restore wiring in `EngineContainer.restore_from_db` and verify restart continuity with deterministic test harness.

4) **Eliminate silent failures (P0)**
- remove `except: pass` paths; log + propagate appropriately or downgrade with explicit warning events.

5) **Idempotency persistence hardening (P1)**
- persist dedup keys / order-intent IDs (or derive from durable event IDs) so restart does not re-trigger duplicate order intents.

6) **Paper/live parity tests (P1)**
- add deterministic integration tests for:
  - success/fail/partial fill transitions,
  - order success + state update failure rollback behavior,
  - restart recovery parity,
  - stale signal rejection and retry side effects.

7) **Pipeline ownership simplification (P1)**
- explicitly decide which pipeline is execution-authoritative in paper mode to avoid dual-path ambiguity.

---

## 7. Verdict

### Score: **62 / 100**

Rationale:
- + strong modular components for signal, paper engine, wallet/positions/ledger, DB persistence primitives.
- + explicit logs and many defensive checks.
- - major safety architecture gap: trading_loop execution path bypasses formal RiskGuard.
- - restart/recovery inconsistency risk in wallet restore wiring.
- - partial-state mutation risk due to non-atomic multi-store updates.
- - silent exception paths remain.

### Final classification (required format)

**PAPER-ACCEPTABLE WITH RISKS**

### What is already strong
- paper execution primitives are reasonably complete (wallet lock/unlock, position lifecycle, ledger recording).
- DB write APIs support idempotent inserts for trades/ledger.
- runtime telemetry/logging is rich.

### What is acceptable for paper running now
- controlled paper testing with close monitoring and no real-wallet capital is acceptable.

### What is unsafe / incomplete
- risk enforcement is not uniformly mandatory across active execution paths.
- recovery and reconciliation are not hardened enough for real wallet.

### Must-fix before real wallet enablement
- mandatory RiskGuard enforcement in trading_loop execution path,
- reconciliation contract hardening + restart correctness,
- removal of silent exception swallowing,
- durable idempotency and restart-safe dedup,
- explicit paper/live lifecycle parity validation.
