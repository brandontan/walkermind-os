# WARP•FORGE — P3c Signal Following Strategy

Branch: `WARP/CRUSADERBOT-P3C-SIGNAL-FOLLOWING`
Validation Tier: MAJOR
Claim Level: STRATEGY SIGNAL GENERATION — scan() + evaluate_exit() over an operator-curated feed model. No execution path, no risk gate, no capital logic touched.
Validation Target: SignalFollowingStrategy implements all three BaseStrategy hooks; bootstrap_default_strategies() idempotent with both P3b + P3c strategies; migration 010 creates 3 tables (signal_feeds + signal_publications + user_signal_subscriptions) with IF NOT EXISTS guards and partial UNIQUE on active subscriptions; SignalFeedService idempotent across create_feed / publish_signal / publish_exit / subscribe / unsubscribe; signal_evaluator emits SignalCandidates strictly from DB reads (no HTTP); /signals Telegram surface gated at Tier 2 with MAX 5 active subscriptions per user; full unit suite green.
Not in Scope: P3d per-user scan loop, execution queue wiring, risk-gate integration, operator-side publishing UI, backtesting, Polymarket metadata join inside scan().
Suggested Next Step: WARP•SENTINEL MAJOR audit on this branch (audit phases 1, 3, 4, 5 most relevant — strategy plane is data-only, infra/latency phases minimal). After SENTINEL APPROVED, P3d wires SignalFollowingStrategy + CopyTradeStrategy into the user-level scan loop and execution queue.

---

## 1. What was built

P3c implements the operator-curated feed model behind `SignalFollowingStrategy`. Three durable tables back the surface; one service module owns the operator + user write paths; one evaluator owns the filter-and-score pipeline that turns publications into `SignalCandidate` objects; one Telegram surface lets users opt in or out at Tier 2.

- `SignalFollowingStrategy` (`name=signal_following`, `version=1.0.0`, all three risk profiles compatible) implements the BaseStrategy ABC. `scan()` delegates to `signal_evaluator.evaluate_publications_for_user`; `evaluate_exit()` queries `signal_publications` for either trigger form (originating publication retired in place via `exit_published_at`, OR a later publication on the same feed+market with `exit_signal=TRUE`). `default_tp_sl()` returns `(0.20, 0.08)`.
- Registry bootstrap is idempotent across both P3b CopyTrade + P3c SignalFollowing. `bootstrap_default_strategies()` may be called multiple times in `main.py` lifespan and from tests after `_reset_for_tests()` without raising or duplicating.
- `SignalFeedService` is the operator + user write surface. Every method is idempotent: `create_feed` returns the existing row for an existing slug rather than UPDATE-ing; `subscribe` short-circuits on already-active subscriptions and refuses past the 5-cap under a `pg_advisory_xact_lock(hashtext(user_id))`; `unsubscribe` silently no-ops on already-unsubscribed pairs. The `subscriber_count` denormalisation is maintained inside the same transaction as the subscription flip.
- `signal_evaluator` emits one `SignalCandidate` per publication that survives the filter envelope. Filtering is best-effort over the publication payload (no HTTP): `blacklisted_market_ids` is always honoured; `categories` is honoured when the payload carries category metadata, and conservative-skipped when the filter is set but the payload is silent (mirrors the P3b copy_trade behaviour); `min_liquidity` and `max_time_to_resolution_days` are not enforced because the issue spec forbids HTTP fetches inside `scan()`.
- Migration `010_signal_following.sql` adds `signal_feeds` (slug UNIQUE, status DEFAULT 'active', subscriber_count DEFAULT 0), `signal_publications` (FK signal_feeds, payload JSONB, exit_signal DEFAULT FALSE, expires_at NULLABLE, exit_published_at NULLABLE), and `user_signal_subscriptions` (FK signal_feeds + users, unsubscribed_at NULLABLE). All `IF NOT EXISTS`. Partial `UNIQUE INDEX ... WHERE unsubscribed_at IS NULL` is the dedup boundary for active subscriptions; matching partial INDEX accelerates the hot read on the strategy scan loop.
- `/signals` Telegram surface adds list / catalog / on / off subcommands plus an inline keyboard for one-tap unsubscribe. Tier 2 (`ALLOWLISTED`) gate is enforced once at the top-level dispatcher so every subcommand inherits it. Slug validator rejects anything outside `^[a-z0-9][a-z0-9_-]{1,59}$`. Cap surfacing is read directly from the service layer's result code.

No execution path. No risk gate. No CLOB client. No activation guard. No HTTP fetch from inside the strategy scan.

## 2. Current system architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Operator surface (manual / future operator UI — out of P3c scope)       │
│    SignalFeedService.create_feed / publish_signal / publish_exit         │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     P3c persistence (migration 010)                      │
│  signal_feeds — operator-managed catalogue (slug UNIQUE, status)         │
│  signal_publications — entry + exit rows (exit_signal, expires_at,       │
│                        exit_published_at, payload JSONB)                 │
│  user_signal_subscriptions — partial UNIQUE on active rows               │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  /signals Telegram surface (Tier 2 gate, MAX 5 active per user)          │
│    list | catalog | on <slug> | off <slug> + inline keyboard             │
│  delegates writes to SignalFeedService.subscribe / unsubscribe           │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  signal_evaluator.evaluate_publications_for_user (pure DB, no HTTP)      │
│    blacklist (always) + categories (best-effort) + size + confidence     │
│    -> SignalCandidate[]                                                  │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  SignalFollowingStrategy (BaseStrategy ABC)                              │
│    scan(market_filters, user_context) -> SignalCandidate[]               │
│    evaluate_exit(position) -> ExitDecision (strategy_exit/hold)          │
│    default_tp_sl() -> (0.20, 0.08)                                       │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │ (P3d wires this into the scan loop)
                                ▼
                    Risk gate -> Execution (downstream — UNTOUCHED)
```

The strategy plane now carries two concrete BaseStrategy implementations registered on the singleton `StrategyRegistry`. Both are idempotently bootstrapped at process startup. P3d will own the per-user scan loop, the persisted dedup ledger for emitted publications, and the wire into the existing risk gate.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/010_signal_following.sql`
- `projects/polymarket/crusaderbot/domain/strategy/strategies/signal_following.py`
- `projects/polymarket/crusaderbot/services/signal_feed/__init__.py`
- `projects/polymarket/crusaderbot/services/signal_feed/signal_feed_service.py`
- `projects/polymarket/crusaderbot/services/signal_feed/signal_evaluator.py`
- `projects/polymarket/crusaderbot/bot/handlers/signal_following.py`
- `projects/polymarket/crusaderbot/bot/keyboards/signal_following.py`
- `projects/polymarket/crusaderbot/tests/test_signal_following.py`
- `projects/polymarket/crusaderbot/reports/forge/p3c-signal-following.md` (this file)

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/strategies/__init__.py` — exports `SignalFollowingStrategy`
- `projects/polymarket/crusaderbot/domain/strategy/registry.py` — `bootstrap_default_strategies` iterates `(CopyTradeStrategy, SignalFollowingStrategy)`
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registers `/signals` CommandHandler + `signals:` CallbackQueryHandler

State files (this lane closure):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

No production runtime files outside the strategy plane were touched. No execution path, risk gate, CLOB client, scheduler, or activation guard modified.

## 4. What is working

- BaseStrategy contract: `SignalFollowingStrategy().default_tp_sl() == (0.20, 0.08)`. All three abstract hooks implemented; class registers cleanly via `StrategyRegistry.register(cls())`. Verified by `test_signal_following_default_tp_sl_matches_spec`, `test_signal_following_strategy_attributes`, `test_bootstrap_registers_both_strategies`.
- Registry bootstrap idempotency: a second `bootstrap_default_strategies(reg)` call on a registry that already holds both strategies adds no duplicates and does not raise. Verified by `test_bootstrap_is_idempotent_with_both_strategies`.
- scan() defensive path: an evaluator-side exception (DB down, malformed publication, etc.) returns an empty list rather than crashing the user's scan tick. Verified by `test_strategy_scan_swallows_evaluator_exception` and `test_evaluate_handles_publication_fetch_failure`.
- evaluate_exit() — both trigger forms map cleanly to the foundation `ExitDecision(should_exit=True, reason='strategy_exit', metadata={'reason': 'signal_exit_published', ...})` invariant. Hold paths covered for missing metadata, no exit row, and DB error. Verified by `test_evaluate_exit_emits_strategy_exit_when_publication_retired`, `test_evaluate_exit_emits_strategy_exit_when_separate_exit_signal`, `test_evaluate_exit_holds_when_no_exit_row_found`, `test_evaluate_exit_holds_on_db_error`, `test_evaluate_exit_holds_when_no_feed_id_in_metadata`, `test_evaluate_exit_holds_when_no_market_id`.
- Filter logic: blacklist always honoured; categories filter conservative-skips when payload silent (mirrors P3b copy_trade); default-permissive filters allow valid publications through. Verified by 6 `_passes_market_filters` parametrised tests.
- Size resolution: payload `size_usdc` capped to `available × capital_pct`, $1 floor honoured, zero-allocation and zero-balance both return 0.0 to skip. Default $10 fallback when payload omits the size. Verified by 5 `_resolve_size_usdc` tests.
- Confidence resolution: payload value clamped into `[0.0, 1.0]`; default 0.6 when missing or invalid. Verified by 4 `_resolve_confidence` tests.
- Subscription cap enforcement: `subscribe()` returns `cap_exceeded` at or above MAX_SUBSCRIPTIONS_PER_USER (5) without issuing an INSERT; `subscribed` under the cap wraps the work in `BEGIN`/`COMMIT` with `pg_advisory_xact_lock(hashtext(user_id))` as the first execute call. `subscriber_count` is incremented on subscribe, decremented (floored at 0) on unsubscribe, both inside the same transaction as the row flip. Verified by `test_subscribe_returns_cap_exceeded_at_or_above_cap`, `test_subscribe_returns_subscribed_under_cap_with_advisory_lock`, `test_unsubscribe_returns_true_and_decrements_count`.
- Service result codes: `unknown_feed` / `feed_inactive` / `exists` / `cap_exceeded` / `subscribed` all returned correctly under fixture-driven scenarios. Verified by 5 dedicated tests.
- Idempotent feed creation: re-calling `create_feed` with an existing slug returns the existing row without issuing an INSERT. Verified by `test_create_feed_returns_existing_when_slug_exists`.
- Input validation on operator surface: `publish_signal` rejects bad sides, empty market IDs, and non-UUID feed IDs; `publish_exit` rejects empty market IDs; `create_feed` rejects empty slugs. 4 dedicated tests.
- Migration 010 idempotency: every CREATE statement guarded by `IF NOT EXISTS`. Partial UNIQUE on `(user_id, feed_id) WHERE unsubscribed_at IS NULL` is the dedup boundary for active subscriptions. Path matches the runner expectation (`migrations/`, not `infra/migrations/`).
- /signals handler: Tier 2 gate enforced at dispatcher; usage hint includes the cap; slug validator rejects whitespace, single chars, and non-slug forms; on/off paths surface `cap_exceeded`/`subscribed`/`exists`/`feed_inactive`/`unknown_feed` to the user with the correct text. List view attaches the inline keyboard when the user has subscriptions. Verified by 10 handler tests + 2 keyboard shape tests.
- Test suite: 67 new tests added. `test_signal_following.py` runs in ~0.5 s on the local sandbox. No regression in the existing crusaderbot suite (the only baseline failures are pre-existing sandbox environment gaps — `web3` and `eth_account` modules not installed — which fail at import time on `test_redeem_workers.py`, `test_activation_handlers.py::test_dispatcher_routes_activation_confirm_before_setup`, `test_daily_pnl_summary.py::test_scheduler_registers_daily_pnl_summary_job`; none touch the P3c plane).

## 5. Known issues

- min_liquidity / max_time_to_resolution_days filters are not enforced for signal_following (no HTTP fetch is allowed inside `scan()`). Operators are trusted to pre-filter on liquidity + resolution distance before publishing. Documented in `signal_evaluator` module docstring; surface-area to add a Polymarket join in P3d if WARP🔹CMD wants stricter enforcement, but that is intentionally out of P3c scope.
- The strategy emits one SignalCandidate per surviving publication on every scan tick. Per-publication-per-user dedup is the responsibility of the downstream P3d scan loop (analogous to copy_trade_events for P3b); P3c does not introduce a `signal_following_events` ledger because no execution path is wired yet.
- `signal_publications.exit_signal=TRUE` rows currently store `side='YES'` as a fixed sentinel. The exit trigger is a feed+market-level event, not an outcome-token-level one, so the side value is unused on read. Acceptable as-is; if the operator wants the exit row to carry the side of the closing leg, P3d can extend the schema.
- `subscriber_count` denormalisation is updated inside the same transaction as the subscription flip, so it stays consistent under serial workloads. Two operators flipping the same feed concurrently are serialised by the per-user advisory lock on subscribe, but the feed row itself is not lock-guarded; if a future feature unlocks bulk subscription scripts, swap to an aggregate query rather than a maintained counter.

## 6. What is next

WARP•SENTINEL MAJOR audit on `WARP/CRUSADERBOT-P3C-SIGNAL-FOLLOWING`. After SENTINEL APPROVED:

- P3d implements the per-user signal scan loop that consumes both CopyTrade + SignalFollowing strategies, persists per-user dedup of emitted candidates, and wires the surviving candidates through the existing risk gate to the execution queue.
- After P3d ships and is sentinel-approved, R12 final Fly.io deployment can proceed (the last R12 lane, currently blocked on P3c + P3d + activation guard review).

Activation guards (`EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `ENABLE_LIVE_TRADING`) remain NOT SET. P3c does not change that posture — the strategy plane is signal-generation only and never reaches the execution layer.
