# WARP•SENTINEL REPORT — p3b-copy-trade

Date: 2026-05-05 22:45 Asia/Jakarta
Branch: WARP/CRUSADERBOT-P3B-COPY-TRADE
PR: #877
Score: 71/100
Verdict: CONDITIONAL

## Summary

P3b implements `CopyTradeStrategy` as the first concrete consumer of the P3a BaseStrategy foundation. Signal generation, sizing arithmetic, wallet polling, Telegram surface, and dedup logic are correctly implemented with no critical safety violations. Two MAJOR findings prevent unconditional approval: the migration runner path divergence (tables 008+009 never auto-applied at startup — P0 merge blocker per issue requirements), and a private-attribute access in `bootstrap_default_strategies` that breaks StrategyRegistry encapsulation. Nine audit focus items assessed; seven pass cleanly.

## Findings

### Critical (0)

- None.

### Major (2)

- [MAJ-01] **Migration runner path — P0 merge blocker.** `database.run_migrations()` reads `Path(__file__).parent / "migrations"` (i.e. `projects/polymarket/crusaderbot/migrations/`, confirmed files 001–007 only). `009_copy_trade.sql` lives at `projects/polymarket/crusaderbot/infra/migrations/`. Tables `copy_targets` (P3b schema) and `copy_trade_events` are **never auto-applied at startup**. On a fresh DB, any call to `_load_active_copy_targets` raises `asyncpg.UndefinedTableError`. Strategy is non-functional until WARP🔹CMD resolves the runner-path decision. Declared in forge report as known/inherited from P3a. Classification: **P0 — must resolve before merge.** — `projects/polymarket/crusaderbot/infra/migrations/009_copy_trade.sql` (entire file not picked up by runner)

- [MAJ-02] **Bootstrap private-attribute access.** `bootstrap_default_strategies` uses `if cls.name in reg._strategies` to test for an already-registered name. `StrategyRegistry` exposes `list_available()` and `get(name)` as public API; the idempotency check should use `try: reg.get(cls.name) / except KeyError: reg.register(cls())` instead of reaching into internal state. Breaks encapsulation; silently couples bootstrap to the internal dict name. — `projects/polymarket/crusaderbot/domain/strategy/registry.py:160`

### Minor (3)

- [MIN-01] `user_id` parameter lacks type annotation in three handler helpers: `_list_active_targets(user_id)`, `_insert_active_target(user_id, wallet: str)`, `_deactivate_target(user_id, wallet: str)`. — `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py:79,106,148`

- [MIN-02] Comment `# P3b copy-trade strategy command surface.` in `bot/dispatcher.py:52` references a phase token, violating the no-phase-reference comment rule in AGENTS.md.

- [MIN-03] `copy_trade_events.copy_target_id UUID REFERENCES copy_targets(id) ON DELETE CASCADE` is nullable (no `NOT NULL`). Application code never inserts NULL but the schema does not enforce it. — `projects/polymarket/crusaderbot/infra/migrations/009_copy_trade.sql:153`

## Claim Verification

Declared: STRATEGY SIGNAL GENERATION — `scan()` returns SignalCandidates only, no order placement, no execution-path I/O

Evidence: `scan()` returns `list[SignalCandidate]` with read-only DB access (`_load_active_copy_targets`, `_already_mirrored`). `evaluate_exit()` returns `ExitDecision` (hold or strategy_exit). No broker calls, no CLOB client interaction, no risk gate touched. `bootstrap_default_strategies()` wires registry infrastructure only — not execution.

Verdict: MATCH

## Trading Safety

N/A — task does not touch trading execution logic.

Scoped observations (signal layer only):

- `MIN_TRADE_SIZE_USDC = 1.0` floor enforced in both `scale_size` and `mirror_size_direct`. PASS
- `mirror_size_direct` fallback when `leader_bankroll_estimate` absent prevents position-cap collapse. PASS
- `evaluate_exit` returns `hold` on API failure — no premature force-close on outage. PASS
- `ENABLE_LIVE_TRADING` guard present in `main.py`; not bypassed by this PR. PASS
- No Kelly (α) constant in scope; `max_position_pct > 1.0` guard in scaler returns 0.0. PASS

## Scope Verification

Declared scope: CopyTradeStrategy + scaler + wallet_watcher + /copytrade Telegram + migration 009 + registry bootstrap + tests

Actual files changed: `bot/dispatcher.py`, `bot/handlers/copy_trade.py`, `bot/keyboards/copy_trade.py`, `domain/strategy/__init__.py`, `domain/strategy/registry.py`, `domain/strategy/strategies/__init__.py`, `domain/strategy/strategies/copy_trade.py`, `infra/migrations/009_copy_trade.sql`, `main.py`, `reports/forge/p3b-copy-trade.md`, `services/copy_trade/__init__.py`, `services/copy_trade/scaler.py`, `services/copy_trade/wallet_watcher.py`, `state/CHANGELOG.md`, `state/PROJECT_STATE.md`, `tests/test_copy_trade.py`

Verdict: CLEAN — all changed files within declared scope; no surprise files

## Audit Focus — 9 Items (issue #878)

1. **MIGRATION RUNNER PATH** — MAJOR [MAJ-01] — P0 merge blocker. `009_copy_trade.sql` NOT picked up by runner. Tables absent on fresh DB.
2. **Per-follower dedup** `UNIQUE(copy_target_id, source_tx_hash)` — PASS. Constraint verified in migration SQL and in `_already_mirrored()` query.
3. **WalletWatcherUnavailable exit path returns hold** — PASS. `evaluate_exit` catches `Exception` (including `WalletWatcherUnavailable`), returns `ExitDecision(should_exit=False, reason="hold")`. Test `test_evaluate_exit_holds_on_wallet_watcher_unavailable` confirms.
4. **mirror_size_direct for unknown bankroll, $1 floor enforced** — PASS. `leader_bankroll_estimate=None/0` routes to `mirror_size_direct`; `MIN_TRADE_SIZE_USDC=1.0` enforced in both sizing paths.
5. **Atomic cap pg_advisory_xact_lock** — PASS. Lock acquired first inside transaction, count read under lock, insert/update after cap check. Test confirms order: BEGIN → lock → count → insert → COMMIT.
6. **Schema co-existence legacy wallet_address + target_wallet_address backfill** — PASS. `ADD COLUMN IF NOT EXISTS`, guarded `DO` blocks, conditional `NOT NULL` addition. Sequence is correct for both fresh and upgraded DBs.
7. **Signal generation only, scan() returns SignalCandidates** — PASS. No execution I/O. No broker call. No risk gate touched.
8. **Tier 2 gate on all /copytrade commands** — PASS. `_ensure_tier(update, Tier.ALLOWLISTED)` at entry-point before sub-command dispatch; callback handler also gated independently.
9. **Rate limiter 1 req/s global across all wallet watchers** — PASS. Module-global `asyncio.Lock` + monotonic timestamp. Test `test_rate_limit_serialises_back_to_back_calls` confirms second call observes ≥ interval delay.

## Score Breakdown

| Category | Weight | Raw | Notes |
|---|---|---|---|
| Architecture | 20% | 16/20 | MAJ-02 private attr access (-4) |
| Functional | 20% | 20/20 | All 9 audit focus items addressed |
| Failure modes | 20% | 20/20 | Timeout, HTTP error, WalletWatcherUnavailable, dedup all handled |
| Risk | 20% | 20/20 | N/A for signal layer; scoped checks pass |
| Infra + TG | 10% | 10/10 | Tier gate correct; dispatcher wiring clean |
| Latency | 10% | 10/10 | 5s timeout, 1 req/s rate limit in place |
| Penalty: MAJ-01 (migration P0) | | -10 | Tables never applied at startup |
| Penalty: MIN-01/02/03 | | -9 | 3 minor findings @ -3 each |

Final Score: **71/100**

## Recommendation

CONDITIONAL — WARP🔹CMD can merge after conditions met:

1. **[REQUIRED — P0]** Resolve migration runner path: move `database.run_migrations()` to read from `infra/migrations/` OR copy 008+009 into `migrations/`. Decision belongs to WARP🔹CMD. This is the sole merge gate.
2. **[RECOMMENDED]** Fix `bootstrap_default_strategies` to use public `StrategyRegistry` API instead of `reg._strategies` (one-line change).
3. **[DEFERRED]** MIN-01 type annotations, MIN-02 comment cleanup, MIN-03 nullable FK — acceptable in follow-up lane.
