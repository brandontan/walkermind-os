# WARP•FORGE — P3B Copy-Trade Strategy

Branch: `WARP/CRUSADERBOT-P3B-COPY-TRADE`
Validation Tier: MAJOR
Claim Level: STRATEGY SIGNAL GENERATION — `scan()` returns SignalCandidates only, no order placement, no execution-path I/O, delegates to the (future P3d) execution queue.
Validation Target: `CopyTradeStrategy` contract (scan dedup + size scaling + window filter + leader-exit detection), `services.copy_trade.scaler.scale_size` arithmetic, `services.copy_trade.wallet_watcher` rate limiter + 5 s timeout + error swallowing, Telegram `/copytrade add|remove|list` (Tier 2 gate, MAX 3 cap, 0x address normalisation), migration `009_copy_trade.sql` idempotency, registry `bootstrap_default_strategies()` registering `copy_trade@1.0.0`.
Not in Scope: signal scan loop, execution queue, risk gate wiring, CLOB submission, order placement, exit watcher integration, position-row writer that persists the eventual `copy_trade_events.mirrored_order_id`, activation guards, leader bankroll estimator (P3c+).
Suggested Next Step: P3c — Signal Following strategy (second `BaseStrategy` consumer); P3d — wire scan loop + execution queue so the SignalCandidates flow through the risk gate.

---

## 1. What was built

The first concrete `BaseStrategy` consumer of the P3a foundation. Five new modules + one migration + one test module + a 4-line wire-up across the registry, dispatcher, and lifespan:

- `domain/strategy/strategies/copy_trade.py` — `CopyTradeStrategy`. Implements `scan` (DB load → wallet poll → 5-min window filter → unique-tx dedup → size scaling → SignalCandidate emit), `evaluate_exit` (leader-exit detection by condition_id presence in leader's open set), and `default_tp_sl = (0.25, 0.10)`.
- `services/copy_trade/scaler.py` — pure-arithmetic `scale_size(...)`. Proportional rule + `max_position_pct` cap + `MIN_TRADE_SIZE_USDC=1.0` floor; degenerate inputs return `0.0` (the strategy's "skip" sentinel).
- `services/copy_trade/wallet_watcher.py` — `fetch_recent_wallet_trades` (5 s `asyncio.wait_for`, process-wide 1 req/s rate limit via `asyncio.Lock` + monotonic stamp, swallow-and-empty on timeout / HTTP / parse error) and `fetch_leader_open_condition_ids` (newest-first walk over Data API trade rows, BUY = still open, SELL = exited).
- `domain/strategy/registry.py` — extended with `bootstrap_default_strategies(registry=None)` (idempotent, lazy-import to dodge the registry↔strategies cycle).
- `infra/migrations/009_copy_trade.sql` — `copy_targets` (UNIQUE per `(user_id, target_wallet_address)`) + `copy_trade_events` (UNIQUE composite on `(copy_target_id, source_tx_hash)` — per-follower dedup boundary so the same leader trade may legitimately be mirrored by every follower of the leader).
- `bot/handlers/copy_trade.py` + `bot/keyboards/copy_trade.py` — `/copytrade add|remove|list` with Tier 2 gate, hard cap of 3 active rows enforced at the handler boundary, `0x[a-fA-F0-9]{40}` validator + case-fold to keep the UNIQUE index honest, callback-driven `🗑 Stop` button.
- `tests/test_copy_trade.py` — 49 hermetic tests (no DB, no broker, no Telegram network).

Wire-up:
- `bot/dispatcher.py` — `/copytrade` command + `^copytrade:` callback registered.
- `domain/strategy/__init__.py` — re-exports `bootstrap_default_strategies`.
- `domain/strategy/strategies/__init__.py` — exports `CopyTradeStrategy`.
- `main.py` — single-line `bootstrap_default_strategies()` call inside `lifespan`, after `init_pool/run_migrations/init_cache`. This satisfies the WARP🔹CMD done criterion *"CopyTradeStrategy registered in StrategyRegistry at startup"*.

Foundation contract preserved: zero changes to `domain/strategy/base.py` and `domain/strategy/types.py`. `ExitDecision`'s rigid `should_exit ↔ reason` invariant (only `strategy_exit` and `hold` are valid) is honoured by encoding leader-driven exits as `reason="strategy_exit", metadata={"reason": "leader_exit"}` — see Known Issues for the rationale.

## 2. Current system architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Telegram /copytrade add|remove|list                             │
│   - Tier 2 gate                                                  │
│   - 0x + 40-hex validator + lower-case fold                      │
│   - MAX 3 active rows per user (enforced at handler)             │
└────────────────────────┬─────────────────────────────────────────┘
                         │ writes
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  copy_targets (DB)                                               │
│   UNIQUE(user_id, target_wallet_address)                         │
│   status ∈ {active, inactive}                                    │
└────────────────────────┬─────────────────────────────────────────┘
                         │ read by
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  CopyTradeStrategy.scan(filters, user_context)                   │
│   1. _load_active_copy_targets(user_id)                          │
│   2. for each target:                                            │
│        wallet_watcher.fetch_recent_wallet_trades(wallet)         │
│        - 5 s timeout per call                                    │
│        - 1 req/s global rate limit                               │
│        - swallow HTTP / parse errors                             │
│   3. drop trades older than 5 minutes                            │
│   4. _already_mirrored(source_tx_hash) -> drop                   │
│   5. scaler.scale_size(...) -> 0.0 means skip                    │
│   6. SignalCandidate(confidence=0.75, suggested_size=…,          │
│                      metadata={ source_tx_hash, leader_wallet,   │
│                                 copy_target_id, … })             │
└────────────────────────┬─────────────────────────────────────────┘
                         │ list[SignalCandidate]
                         ▼
                  → INTELLIGENCE → RISK → EXECUTION  (P3d scope)
```

Exit path:

```
exit watcher (R12c)            CopyTradeStrategy.evaluate_exit(position)
   priority chain              ┌────────────────────────────────────┐
   force_close > tp > sl > ── │ read metadata.{leader_wallet,       │
   strategy_exit > hold        │              condition_id}         │
                              │ wallet_watcher.fetch_leader_open_   │
                              │   condition_ids(leader_wallet)      │
                              │ if condition_id in open  -> hold    │
                              │ else                     ->         │
                              │   ExitDecision(should_exit=True,    │
                              │     reason='strategy_exit',         │
                              │     metadata['reason']='leader_exit'│
                              │   )                                 │
                              │ on fetch failure -> hold (retry     │
                              │   on next exit-watcher tick)        │
                              └────────────────────────────────────┘
```

Persistence (migration 009):

```
copy_targets
  ├─ id UUID PK
  ├─ user_id UUID FK users(id) ON DELETE CASCADE
  ├─ target_wallet_address VARCHAR(42)
  ├─ scale_factor DOUBLE PRECISION DEFAULT 1.0
  ├─ status VARCHAR(20) DEFAULT 'active'   -- 'active' | 'inactive'
  ├─ trades_mirrored INTEGER DEFAULT 0
  ├─ created_at TIMESTAMPTZ
  ├─ UNIQUE (user_id, target_wallet_address)
  └─ INDEX (user_id, status)

copy_trade_events                          -- per-follower dedup boundary
  ├─ id UUID PK
  ├─ copy_target_id UUID FK copy_targets(id) ON DELETE CASCADE
  ├─ source_tx_hash VARCHAR(66)
  ├─ mirrored_order_id UUID                -- written by P3d execution path
  ├─ created_at TIMESTAMPTZ
  ├─ UNIQUE (copy_target_id, source_tx_hash) -- per-follower; same leader
  │                                          -- tx may be mirrored by every
  │                                          -- follower of the leader, but
  │                                          -- a single follower must not
  │                                          -- double-mirror after re-scan
  └─ INDEX (copy_target_id, created_at DESC)
```

Registry bootstrap:

```
main.py lifespan
   init_pool() → run_migrations() → init_cache()
        → bootstrap_default_strategies()       -- single call, idempotent
              → StrategyRegistry.instance().register(CopyTradeStrategy())
```

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/strategy/strategies/__init__.py`
- `projects/polymarket/crusaderbot/domain/strategy/strategies/copy_trade.py`
- `projects/polymarket/crusaderbot/services/copy_trade/__init__.py`
- `projects/polymarket/crusaderbot/services/copy_trade/scaler.py`
- `projects/polymarket/crusaderbot/services/copy_trade/wallet_watcher.py`
- `projects/polymarket/crusaderbot/infra/migrations/009_copy_trade.sql`
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py`
- `projects/polymarket/crusaderbot/bot/keyboards/copy_trade.py`
- `projects/polymarket/crusaderbot/tests/test_copy_trade.py`
- `projects/polymarket/crusaderbot/reports/forge/p3b-copy-trade.md`

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/registry.py` — added `bootstrap_default_strategies`.
- `projects/polymarket/crusaderbot/domain/strategy/__init__.py` — re-exports `bootstrap_default_strategies`.
- `projects/polymarket/crusaderbot/main.py` — 2-line wire-up: import `bootstrap_default_strategies`; call inside `lifespan` after `init_cache()`.
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registered `/copytrade` command + `^copytrade:` callback.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

No risk gate file modified. No execution path modified. No CLOB client modified. No activation guard touched. The `ExitDecision` / `SignalCandidate` / `MarketFilters` / `UserContext` types from P3a are unchanged.

## 4. What is working

- `bootstrap_default_strategies()` registers `copy_trade@1.0.0` with all three risk profiles. Re-invoking is a no-op (skips already-registered names) so calling from `main.py` lifespan on every boot is safe — verified by `test_bootstrap_is_idempotent`.
- `CopyTradeStrategy.scan` returns:
  - `[]` when the user has no active copy targets (`test_scan_returns_empty_when_no_targets`).
  - one `SignalCandidate(confidence=0.75, side='YES'|'NO', metadata.source_tx_hash=…)` per fresh leader BUY (`test_scan_emits_signal_for_fresh_buy`).
  - `[]` when the only candidate trade was already in `copy_trade_events` (`test_scan_dedupes_already_mirrored_trades`).
  - `[]` when every candidate trade is older than 5 minutes (`test_scan_drops_stale_trades_outside_window`).
  - `[]` when the user's bankroll cannot satisfy the $1 floor (`test_scan_skips_trade_when_size_below_floor`).
- `scaler.scale_size`:
  - applies the proportional rule when the cap doesn't bind (`test_scale_size_proportional_rule`).
  - clips to `user_available × max_position_pct` when proportional exceeds the cap (`test_scale_size_position_cap_binds_when_proportional_too_large`).
  - returns `0.0` below `$1` (`test_scale_size_below_floor_returns_zero`); honours the boundary (`test_scale_size_at_exactly_one_dollar_passes_floor`).
  - returns `0.0` for every degenerate input — zero / negative leader trade, zero / negative bankroll, zero / negative balance, out-of-range `max_position_pct` (9 parametrised cases).
- `wallet_watcher.fetch_recent_wallet_trades`:
  - returns the API response when it is a list (`test_fetch_recent_wallet_trades_returns_list`).
  - skips the network call entirely on a blank wallet address (`test_fetch_recent_wallet_trades_blank_address_skips_call`).
  - returns `[]` on 5 s timeout (`test_fetch_recent_wallet_trades_swallows_timeout`).
  - returns `[]` on any unexpected exception (`test_fetch_recent_wallet_trades_swallows_unexpected_error`).
  - returns `[]` if the API responds with a non-list shape (`test_fetch_recent_wallet_trades_rejects_non_list_response`).
  - serialises back-to-back calls behind the 1 req/s budget — second call observes ≥ interval delay (`test_rate_limit_serialises_back_to_back_calls`).
- `wallet_watcher.fetch_leader_open_condition_ids` filters the leader's most-recent action per condition: BUY = still open, SELL = exited; first-action-per-condition wins on the newest-first walk (`test_fetch_leader_open_condition_ids_filters_buys_only`).
- `CopyTradeStrategy.evaluate_exit`:
  - returns `hold` when metadata is missing (`test_evaluate_exit_holds_when_metadata_missing`).
  - returns `hold` when the leader still holds the condition (`test_evaluate_exit_holds_when_leader_still_in`).
  - returns `should_exit=True, reason='strategy_exit', metadata.reason='leader_exit'` when the leader is no longer in the position (`test_evaluate_exit_signals_strategy_exit_when_leader_left`).
  - returns `hold` (not exit) on fetch failure — preferring a delayed close to a wrong close (`test_evaluate_exit_holds_when_fetch_fails`).
- `CopyTradeStrategy.default_tp_sl()` returns `(0.25, 0.10)` per WARP🔹CMD spec.
- `_normalise_side` only emits a side for `BUY` legs (`SELL` becomes `None` so it is treated as a leader-exit signal upstream, not a mirror). `_parse_trade_timestamp` accepts unix int, ISO-8601 with `Z`, and rejects garbage.
- Telegram `/copytrade`:
  - `_normalise_wallet` accepts `0x` + exactly 40 hex chars (case-insensitive) and rejects every malformed input I parameterised.
  - `MAX_COPY_TARGETS_PER_USER == 3` is the cap exercised at the handler boundary.
  - `_truncate_wallet` produces the `0xXXXXXXXX…XXXX` format keys in messages and keyboards.
- Migration `009_copy_trade.sql` is idempotent: every `CREATE TABLE` and `CREATE INDEX` uses `IF NOT EXISTS`, matching the `006_redeem_queue.sql` convention.
- Suite: `pytest projects/polymarket/crusaderbot/tests/ -q` reports `245 passed`. Baseline before this lane was 196 (152 prior + 44 P3a). 196 + 49 new = 245 — no regression.

## 5. Known issues

- **`infra/migrations/` runner divergence (carried from P3a, NOT introduced by P3b).** `database.run_migrations()` reads `Path(__file__).parent / "migrations"` (i.e. the legacy `migrations/` directory). Migration `009_copy_trade.sql` is committed under `infra/migrations/` per the WARP🔹CMD task spec — same as `008_strategy_tables.sql`. The DDL exists in repo but does NOT auto-apply at startup until WARP🔹CMD resolves the runner-path decision (move runner to `infra/migrations/` *or* mirror these files into `migrations/`). Until then, `copy_targets` and `copy_trade_events` will not exist in a fresh DB — the strategy load will fail at the `_load_active_copy_targets` query, but the WARP•SENTINEL audit can verify the SQL logic in isolation. P3b does NOT also drop a copy of the SQL into `migrations/` because that would presume the runner-path decision, and the P3a forge report explicitly handed that decision to WARP🔹CMD.
- **`ExitDecision` reason encoding.** WARP🔹CMD task body specifies `reason="leader_exit"` for the leader-driven close. The P3a foundation `ExitDecision.__post_init__` invariant pins `should_exit=True ↔ reason="strategy_exit"` — `VALID_EXIT_REASONS = ("strategy_exit", "hold")`. Modifying the foundation invariant is out of scope for P3b (P3a is still in CMD review). The leader-driven distinction is preserved as `metadata["reason"] = "leader_exit"`. Downstream telemetry / exit watcher attribution can branch on `metadata.reason` to surface the leader-exit path while the foundation contract stays untouched. WARP🔹CMD may want to extend `VALID_EXIT_REASONS` in P3c if more granular reason taxonomy is required.
- **Leader bankroll estimate.** The strategy treats `target.leader_bankroll_estimate` as optional and routes to `mirror_size_direct(...)` (1:1 mirror, capped at the user position cap) when the column is absent. This preserves proportionality across leader trade sizes — a $5 leader trade mirrors at $5, a $500 leader trade caps at the user's position cap — rather than collapsing every signal to the user's cap as a synthetic-bankroll proportional rule would. A real Polymarket-positions-based estimator is deferred to P3c+; the column is not yet on the table because no estimator writes to it. WARP🔹CMD may want to add `leader_bankroll_estimate DOUBLE PRECISION` in a follow-up migration to flip the strategy back onto the proportional path.
- **Open-position approximation.** `fetch_leader_open_condition_ids` derives "open" from the most recent BUY/SELL per condition on the `/activity` Data API endpoint. This is conservative (errs toward keeping the position open) but will miss a position the leader closed via a partial sell + re-buy on the same condition. A first-class positions API integration is the right fix in P3d when the exit watcher consumes this surface.
- **Rate limiter is process-local.** The 1 req/s gate uses an `asyncio.Lock` + module-global timestamp — correct for one process, but multi-process deployments (workers + API split, or N Fly.io machines) each carry their own limiter. This matches the existing CrusaderBot architecture (single-process Fly machine today). A redis-backed limiter is a follow-up if multi-machine rollout happens.

## 6. What is next

P3c — Signal Following strategy as the second concrete `BaseStrategy` consumer. After P3c the registry catalog lights up with two strategies; P3d wires the per-user signal scan loop into the existing risk gate and execution queue. WARP🔹CMD must still resolve the `infra/migrations/` runner path (see P3a known issue + this report).

Validation Tier: MAJOR
Claim Level: STRATEGY SIGNAL GENERATION — `scan()` returns SignalCandidates only, no order placement, no execution-path I/O.
