# WARP•SENTINEL — P3c Signal Following Strategy Audit

Branch: `WARP/CRUSADERBOT-P3C-SIGNAL-FOLLOWING`
PR: #892
Head SHA: ae38bcfeb08f21371bc237a91a75cccbb4ea1f3a
Base: main @ d725038f
Validation Tier: MAJOR
Claim Level audited: STRATEGY SIGNAL GENERATION — `scan()` + `evaluate_exit()` over operator-curated feeds. No execution path, no risk gate, no capital logic, no activation guard touched.
Source forge report: `projects/polymarket/crusaderbot/reports/forge/p3c-signal-following.md`
Environment: staging / paper-trading validation. Activation guards must remain NOT SET. No live/prod activation decision is in scope here.

---

## TEST PLAN

Phases run, per WARP🔹CMD scope:

- Phase 0 — Pre-test: report path/sections, branch traceability, PROJECT_STATE / WORKTODO / CHANGELOG sync, locked structure, hard prohibitions.
- Phase 1 — Functional per module: SignalFollowingStrategy, signal_evaluator, SignalFeedService, /signals handler, keyboard, dispatcher, migration 010, registry bootstrap.
- Phase 3 — Failure modes: DB down on scan / evaluate_exit, malformed payload, expired publications, subscription cap race, unknown / inactive feed, stale exit-signal re-entry safety.
- Phase 4 — Async safety: advisory-lock serialisation, no `threading`, no blocking external HTTP introduced, transaction boundary correctness.
- Phase 5 — Risk-rule code review: no execution path touched, no risk gate / capital logic / activation guard / Kelly constants mutated.

Phases not in this audit (per scope): Phase 2 end-to-end pipeline, Phase 6 latency budgets, Phase 7 infra (Redis/PostgreSQL/Telegram), Phase 8 Telegram alert events. The strategy plane is data-only and does not exercise pipeline / latency / infra surfaces.

---

## FINDINGS

### Phase 0 — Pre-test (PASS)

- Forge report at `projects/polymarket/crusaderbot/reports/forge/p3c-signal-following.md` — correct path, correct slug naming (`p3c-signal-following.md`, no phase prefix, no date suffix), all 6 mandatory sections present (`What was built`, `Current system architecture`, `Files created / modified`, `What is working`, `Known issues`, `What is next`). Required metadata (`Validation Tier: MAJOR`, `Claim Level: STRATEGY SIGNAL GENERATION`, `Validation Target`, `Not in Scope`, `Suggested Next Step`) all present. Source: forge report lines 1–8, 12–128.
- Branch traceability: `git rev-parse HEAD` on the audit checkout returns `ae38bcfeb08f21371bc237a91a75cccbb4ea1f3a`, exact match to the task target SHA. Forge report line 3 declares `WARP/CRUSADERBOT-P3C-SIGNAL-FOLLOWING`. `git log origin/main..HEAD` shows 9 commits cleanly attributed to the lane (chunk 2–6 + 4 review fixes).
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`: 7 ASCII-bracket sections preserved. `Last Updated: 2026-05-07 16:30 Asia/Jakarta`. Status reflects "P3c Signal Following strategy FORGE COMPLETE … WARP•SENTINEL MAJOR audit required before merge". `[NEXT PRIORITY]` carries the correct sentinel handoff text and the source path. State file lines 1–2, 25, 32. No drift versus WORKTODO / CHANGELOG.
- `state/WORKTODO.md` Right Now block updated to P3c lane; Phase 3 checklist row for P3c is unchecked with the correct status note. State file lines 6, 23.
- `state/CHANGELOG.md` line 1 carries the P3c append entry (`2026-05-07 16:30 Asia/Jakarta | WARP/CRUSADERBOT-P3C-SIGNAL-FOLLOWING | …`). Append-only invariant preserved.
- Hard prohibitions: zero `phase*/` directories anywhere in the repo (`find . -type d -name 'phase*'` returns empty). Zero `phase*/` imports in P3c sources (AST scan + grep). Zero shims / re-export files. Migration at `projects/polymarket/crusaderbot/migrations/010_signal_following.sql` (NOT `infra/migrations/`), matching the existing 008/009 convention and the runner expectation.
- Lint: `ruff check .` from the crusaderbot working directory — `All checks passed!`
- Implementation evidence exists for every claimed surface (strategy, evaluator, service, migration, handler, dispatcher, tests).

### Phase 1 — Functional (PASS)

- `SignalFollowingStrategy` implements all three abstract hooks:
  - `name = "signal_following"`, `version = "1.0.0"`, `risk_profile_compatibility = ["conservative", "balanced", "aggressive"]` (`signal_following.py:61–63`).
  - `default_tp_sl()` returns the spec value `(0.20, 0.08)` (`signal_following.py:65–66`).
  - `scan()` delegates to `evaluate_publications_for_user`; outer `try/except` swallows any evaluator-side failure into an empty list rather than raising into the scheduler (`signal_following.py:68–93`). Verified by `test_strategy_scan_swallows_evaluator_exception` and `test_strategy_scan_delegates_to_evaluator`.
  - `evaluate_exit()` honours both trigger forms: (a) origin row's `exit_published_at` set → exit (`signal_following.py:138–141`); (b) later `exit_signal=TRUE` row on same `feed_id`+`market_id` strictly after the anchor → exit (`signal_following.py:151–162`). Hold path on missing metadata, missing anchor, no exit row, DB error. Returns `ExitDecision(should_exit=True, reason="strategy_exit", metadata={"reason": "signal_exit_published", "feed_id": …})` — preserves the foundation `should_exit ⇒ reason='strategy_exit'` invariant while encoding the sub-reason in metadata (`signal_following.py:177–185`).
- `signal_evaluator.evaluate_publications_for_user` (`signal_evaluator.py:215–263`):
  - `_load_active_subscriptions` joins `signal_feeds` and filters `f.status='active'` AND `s.unsubscribed_at IS NULL` — paused / archived feeds are silently dropped from the user's scan (`signal_evaluator.py:165–182`).
  - `_load_active_publications` filters `exit_signal=FALSE AND exit_published_at IS NULL AND published_at > subscribed_at AND (expires_at IS NULL OR expires_at > NOW())` — expired publications are filtered at the SQL boundary (`signal_evaluator.py:185–207`).
  - Per-feed publication-fetch failure is caught and the loop continues on the next subscription (`signal_evaluator.py:241–246`). Per-publication candidate-build failure is caught and the loop continues on the next publication (`signal_evaluator.py:255–260`). Verified by `test_evaluate_handles_publication_fetch_failure`.
  - `_passes_market_filters` honours blacklist always; categories filter conservative-skips when payload is silent (`signal_evaluator.py:96–114`). Six parametrised tests cover the matrix.
  - `_resolve_size_usdc` applies the `available × capital_pct` cap, $10 default, $1 floor → 0.0 to drop (`signal_evaluator.py:117–143`). Five tests.
  - `_resolve_confidence` clamps into `[0.0, 1.0]`, default 0.6 (`signal_evaluator.py:146–157`). Four tests.
- `SignalFeedService` (`signal_feed_service.py`):
  - `create_feed` is idempotent on slug (`SELECT … WHERE slug = $1` short-circuits before INSERT, `signal_feed_service.py:97–104`). Slug regex `^[a-z0-9][a-z0-9_-]{1,49}$` enforced at the service boundary (`signal_feed_service.py:34, 78–88`); empty / uppercase / single-char / dot / non-ASCII / dash-prefix all rejected. Tests cover each rejection.
  - `publish_signal` validates feed_id (UUID-coercible), market_id (non-empty), side (`YES`/`NO`); inserts with `exit_signal=FALSE` (`signal_feed_service.py:117–157`).
  - `publish_exit` validates feed_id and market_id; inserts with `exit_signal=TRUE` and `signal_type='exit'` (`signal_feed_service.py:160–192`).
  - `subscribe` (`signal_feed_service.py:200–271`) is the cap-critical path. Inside `async with conn.transaction()`, the very first `execute` is `SELECT pg_advisory_xact_lock(hashtext($1))` keyed on `str(uuid_user)`. Then: feed lookup → unknown_feed / feed_inactive; existing-active lookup → exists; COUNT(*) of active subs → cap_exceeded at or above 5; INSERT user_signal_subscriptions + UPDATE signal_feeds.subscriber_count both inside the same transaction. Verified by `test_subscribe_returns_subscribed_under_cap_with_advisory_lock` (asserts BEGIN → advisory_lock → COMMIT order, and increments are paired) and `test_subscribe_returns_cap_exceeded_at_or_above_cap` (no INSERT issued at the cap).
  - `unsubscribe` is idempotent — `UPDATE … WHERE unsubscribed_at IS NULL RETURNING id` returning None means no flip happened, function returns False without raising (`signal_feed_service.py:274–312`). Counter decrement uses `GREATEST(subscriber_count - 1, 0)` to floor at 0.
- `migrations/010_signal_following.sql` reviewed by inspection:
  - Three tables present: `signal_feeds`, `signal_publications`, `user_signal_subscriptions`. Every CREATE statement uses `IF NOT EXISTS` (lines 47, 71, 96).
  - FK CASCADE: `signal_publications.feed_id → signal_feeds(id) ON DELETE CASCADE` (line 73); `user_signal_subscriptions.feed_id → signal_feeds(id) ON DELETE CASCADE` (line 99); `user_signal_subscriptions.user_id → users(id) ON DELETE CASCADE` (line 98).
  - Partial UNIQUE on active subscriptions: `uq_user_signal_subscriptions_active ON (user_id, feed_id) WHERE unsubscribed_at IS NULL` (lines 104–106). This is the DB-level dedup boundary that pairs with the application-side cap.
  - Hot-path indexes: `idx_signal_publications_feed_published(feed_id, published_at DESC)` (lines 85–86) accelerates the scan-loop read; `idx_user_signal_subscriptions_user_active(user_id) WHERE unsubscribed_at IS NULL` (lines 108–110) accelerates the per-user subscription join.
  - `slug VARCHAR(60) UNIQUE` at the column level; the application-side cap is the tighter 50 (`MAX_SLUG_LEN`). DB column allowing 60 is harmless because the service layer never persists >50.
  - Path matches the runner: `projects/polymarket/crusaderbot/migrations/` (existing convention, used by 008 + 009). Not under the legacy `infra/migrations/` path, per issue spec.
- Bootstrap (`registry.py:153–174`):
  - `bootstrap_default_strategies` iterates `(CopyTradeStrategy, SignalFollowingStrategy)`. Idempotency check via `reg.get(cls.name)` — KeyError on missing → register; existing → silently skip. Lazy import inside the function avoids the registry ↔ strategies cycle. Verified by `test_bootstrap_registers_both_strategies` and `test_bootstrap_is_idempotent_with_both_strategies`.
- `/signals` Telegram surface (`bot/handlers/signal_following.py`):
  - Tier 2 (`Tier.ALLOWLISTED`) gate enforced at the entry-point of `signals_command` and again on `signals_callback` (`signal_following.py:135, 322`). Defense in depth — a Tier 1 user who somehow obtains the inline keyboard cannot trigger an unsubscribe.
  - Slug regex imported from `services.signal_feed.SLUG_PATTERN` so the bot accepts exactly what `create_feed` admits (`signal_following.py:54`). `test_handler_and_service_share_slug_pattern` enforces this single source of truth.
  - Cap surfacing reads the service-layer result code (`signal_following.py:245–249`) and renders the Max-N message containing the literal `MAX_SUBSCRIPTIONS_PER_USER` value.
  - Markdown V1 metacharacter escape on operator-supplied `feed_name` and `description` before `ParseMode.MARKDOWN` reply (`signal_following.py:73–89, 181, 205, 208`). `_escape_md` doubles backslash first then escapes the legacy V1 metaset (`_ * \` [`). Slugs are not escaped because the slug regex already forbids every Markdown metacharacter.
  - Result codes mapped: `cap_exceeded` / `exists` / `feed_inactive` / `unknown_feed` / `subscribed` each render distinct user-actionable text (`signal_following.py:244–272`).
- Dispatcher wiring (`bot/dispatcher.py:67–68, 101–102`):
  - `CommandHandler("signals", signal_following.signals_command)` registered.
  - `CallbackQueryHandler(signal_following.signals_callback, pattern=r"^signals:")` registered.
  - No collision with existing `signals:`-prefixed handlers; pre-existing `setup:`, `wallet:`, `copytrade:` etc. patterns untouched.
- Inline keyboard (`bot/keyboards/signal_following.py`): one row per active subscription, each row is `[🛑 Off <truncated_name>]` with `callback_data=f"signals:off:{slug}"`. Test `test_signal_callback_data_under_telegram_64byte_limit` verifies the 50-char slug + 12-byte prefix stays within Telegram's 64-byte ceiling at the worst case.
- Test suite — actual run on the audit checkout:
  - `pytest projects/polymarket/crusaderbot/tests/test_signal_following.py -q` → **84 passed in 0.52 s**.
  - `pytest projects/polymarket/crusaderbot/tests/ -q` → **428 passed, 1 deprecation warning, 12.45 s**. No regressions in any pre-existing suite (R1–R12 surfaces all green). Forge report's "67 new tests" claim is conservative — pytest collects 84 distinct test functions in the new file.

### Phase 3 — Failure modes (PASS)

- DB down on scan: `signal_following.py:88–93` swallows any exception from `evaluate_publications_for_user` into an empty list and a WARNING log line. The evaluator-internal per-feed loop also swallows publication-fetch failures (`signal_evaluator.py:241–246`). A single bad row cannot crash the user's scan tick. Tests: `test_strategy_scan_swallows_evaluator_exception`, `test_evaluate_handles_publication_fetch_failure`.
- DB down on evaluate_exit: the `try/except` at `signal_following.py:163–170` returns `ExitDecision(should_exit=False, reason="hold")` — a transient DB hiccup must NEVER flip a position to exit. This is the safety-critical invariant for the strategy plane, and it is correctly implemented. Test: `test_evaluate_exit_holds_on_db_error`.
- Malformed payload: `signal_evaluator._payload_dict` (`signal_evaluator.py:73–88`) handles dict / JSON string / invalid JSON / non-object / None — every non-conforming input degrades to `{}` rather than raising. `_build_candidate` is wrapped in the per-publication `try/except` so a malformed row is skipped, not fatal. Tests cover all four input shapes.
- Expired publications: SQL filter `expires_at IS NULL OR expires_at > NOW()` at `signal_evaluator.py:202` excludes expired rows at the DB boundary. The `idx_signal_publications_feed_published(feed_id, published_at DESC)` index supports the read pattern.
- Subscription cap race: the entire `subscribe` body runs inside `async with conn.transaction()` with `pg_advisory_xact_lock(hashtext(user_id))` as the first execute call (`signal_feed_service.py:228–232`). Concurrent `/signals on` calls from the same user serialise on the lock; the cap check (`active_count >= 5`) and INSERT cannot interleave to produce a 6th active row. `test_subscribe_returns_subscribed_under_cap_with_advisory_lock` asserts BEGIN → advisory_lock → COMMIT order and increment pairing. `test_subscribe_returns_cap_exceeded_at_or_above_cap` asserts no INSERT runs at cap.
- Unknown / inactive feed: `subscribe` returns `unknown_feed` / `feed_inactive` codes (`signal_feed_service.py:237–240`); handler renders distinct user-actionable text (`signal_following.py:257–268`). No silent failure, no crash.
- Stale-exit re-entry safety: `evaluate_exit` bounds the (b)-trigger lookup by `published_at > anchor` (`signal_following.py:158`). Anchor priority: origin publication's `published_at` (`:141`) → position `opened_at`/`created_at` (`:144–147`). With no anchor available, the evaluator holds (`:148–149`) — it cannot distinguish stale from fresh exits, so the safe choice is hold, not exit. Tests: `test_evaluate_exit_ignores_stale_exit_signal_published_before_origin`, `test_evaluate_exit_holds_when_no_anchor_available`.

### Phase 4 — Async safety (PASS)

- `grep -E 'threading|Thread\(|ThreadPoolExecutor'` across all P3c surface files (`strategy/strategies/signal_following.py`, `services/signal_feed/__init__.py`, `signal_evaluator.py`, `signal_feed_service.py`, `bot/handlers/signal_following.py`, `bot/keyboards/signal_following.py`) returns zero matches. No threading introduced.
- `grep -E 'httpx\.|requests\.get|requests\.post|urllib\.request'` across the same surface returns zero matches. No blocking external HTTP introduced. `scan()` is pure DB per spec. `signal_evaluator` module docstring documents the deliberate non-enforcement of `min_liquidity` / `max_time_to_resolution_days` because HTTP is forbidden inside the scan path (`signal_evaluator.py:14–19`).
- Transaction boundaries: `subscribe` and `unsubscribe` each wrap their critical section in `async with conn.transaction()`. `subscribe` issues the advisory lock as the first execute, ensuring the lock is held for the duration of the cap check + INSERT + counter UPDATE (`signal_feed_service.py:228–270`).
- Read paths (`_load_active_subscriptions`, `_load_active_publications`, `list_user_subscriptions`, `get_feed_by_slug`, `list_active_feeds`) acquire a fresh pool connection without an outer transaction — appropriate for read-only fetches under asyncpg, no race in the read path.
- `evaluate_exit` issues two reads inside a single `async with pool.acquire()` block (`signal_following.py:127–162`) — no transaction needed (read-only) but the connection is shared so the two queries see a consistent snapshot for the duration of the call.

### Phase 5 — Risk-rule code review (PASS)

- `git diff --stat origin/main…HEAD` for the risk / execution / activation surface returns **empty**. Files audited for diff: `domain/risk/`, `domain/execution/`, `services/router.py`, `domain/activation/`, `config.py`, `.env.example`, `main.py`, `scheduler.py`, `services/redeem/`, `services/exit_watcher.py`. None of these are modified by this PR.
- `grep -E 'KELLY|MAX_POSITION_PCT|DAILY_LOSS|MAX_DRAWDOWN|kill_switch|ENABLE_LIVE_TRADING|EXECUTION_PATH_VALIDATED|CAPITAL_MODE_CONFIRMED'` across all P3c surface files returns **zero matches**. The strategy plane never references the risk constants, the kill switch, or any activation guard. Kelly fraction (0.25) is not in scope here and is unchanged.
- No execution path: `SignalFollowingStrategy.scan` returns `list[SignalCandidate]`. No CLOB client import, no `submit_order` / `place_order` / `router.execute` call. `evaluate_exit` returns an `ExitDecision` data object — the actual close decision is consumed downstream by P3d / the existing exit watcher, neither of which is touched by this PR.
- No capital logic mutation: `_resolve_size_usdc` reads `user_context.capital_allocation_pct` (already-clamped per-user value, untouched by this PR) and applies the multiplicative cap. No `*_pct` setters. No ledger writes from the strategy plane.
- No activation-guard bypass: the activation guards live in `domain/activation/` and `services/router.py`, both untouched. The `/signals` Tier 2 gate is independent of the live-trading guards (Tier 2 = ALLOWLISTED, capital deployment requires Tier 3 + activation guards + live-mode at the execution layer).

---

## CRITICAL ISSUES

**None found.**

No file:line evidence of: silent failure, threading, blocking HTTP in the strategy scan path, risk-gate bypass, capital-logic mutation, activation-guard touch, kill-switch touch, hardcoded secret, full-Kelly usage, phase folder, shim, compatibility layer, or report drift.

---

## STABILITY SCORE

| Dimension                         | Weight | Score | Reasoning                                                                                                       |
| --------------------------------- | -----: | ----: | --------------------------------------------------------------------------------------------------------------- |
| Architecture                      |    20% |    20 | Locked structure preserved; migration at correct path; no shims; idempotent bootstrap; single-source slug.      |
| Functional                        |    20% |    20 | 84/84 P3c tests pass; full crusaderbot suite 428/428; ruff clean; all BaseStrategy hooks honoured.              |
| Failure modes                     |    20% |    20 | DB-down → empty/hold (never exit); malformed payload skipped; expired SQL-filtered; cap race lock-serialised.   |
| Risk                              |    20% |    20 | Zero diff to risk/execution/activation; no Kelly/cap/kill-switch reference; no execution path; no capital op.   |
| Infra + Telegram                  |    10% |    10 | Tier 2 gate at command + callback; MAX 5 surfaced; callback_data ≤ 64 B; MD V1 escape on operator strings.      |
| Latency                           |    10% |    10 | Pure DB; indexed feed_id + active subs; no HTTP; per-feed exception isolation.                                  |
| **TOTAL**                         |  **100%** | **100/100** |                                                                                                                 |

---

## GO-LIVE STATUS

**APPROVED** for merge.

Score 100/100. Zero critical issues. Phase 0 fully clean (paths, naming, sections, state sync, structure). All four Phase-1 modules (strategy / evaluator / service / handler) implement their contracts and are exercised by 84 hermetic tests that all pass on the audit checkout. Phase 3 failure-mode envelope is correct on every safety-critical edge: DB hiccups never flip a position to exit, the per-user cap is serialised by an advisory lock under transaction, expired and stale-exit rows are filtered at the SQL boundary, and unknown / inactive feeds surface as actionable user errors instead of crashes. Phase 4 introduces no threading and no blocking external HTTP; the strategy plane is pure async DB. Phase 5 is the strongest signal: the diff against `domain/risk/`, `domain/execution/`, `services/router.py`, `domain/activation/`, `config.py`, `.env.example`, `main.py`, `scheduler.py`, `services/redeem/`, `services/exit_watcher.py` is **empty**. Kelly stays at 0.25 fractional, position cap stays at 10%, kill-switch behaviour stays unchanged, and all three activation guards (`EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `ENABLE_LIVE_TRADING`) remain NOT SET as required by WARP🔹CMD.

Merge gate result: this verdict authorises **merge of PR #892 to main** at WARP🔹CMD discretion. It does **NOT** authorise live activation, capital deployment, or any flip of the activation guards. P3c lands the strategy plane only — the wire into risk + execution remains P3d's responsibility, and live-mode activation remains gated on the existing checklist.

Environment caveats (per WARP🔹CMD scope):

- Validated for **staging / paper-trading**. The migration, the service, and the strategy were exercised by hermetic tests with mocked asyncpg connections; no real Postgres run was performed in this audit.
- Activation guards must remain NOT SET. P3c must not be promoted to live without the existing live-checklist gates passing on staging first.
- Out of audit scope: pipeline end-to-end, latency, infra (Redis / PostgreSQL / Telegram health), Telegram alert events. The strategy plane is data-only and does not exercise those surfaces.

---

## FIX RECOMMENDATIONS

No critical or blocking fixes required.

Non-blocking follow-ups (track for P3d or post-merge cleanup, none of these gate the merge):

1. **MIN-04 (LOW) — operator-side `subscriber_count` concurrency.** The denormalised `signal_feeds.subscriber_count` is updated inside the per-user `subscribe` transaction, but the feed row itself is not lock-guarded for the increment / decrement. Two operators flipping the same feed concurrently are serialised only by the per-user advisory lock; a future bulk operator script could drift the counter. Forge already flagged this as a known issue (forge report line 119). Recommend swapping to an aggregate `SELECT COUNT(*) … WHERE unsubscribed_at IS NULL` for the catalog view if a bulk operator surface ever lands. Until then, the counter is decorative — the per-user cap is independently enforced via `COUNT(*)` under the advisory lock, so no safety-critical invariant depends on `subscriber_count` accuracy.
2. **MIN-05 (LOW) — `signal_publications.exit_signal=TRUE` rows store `side='YES'` as a fixed sentinel.** The exit trigger is feed + market scoped, so the side value on an exit row is unread. Forge known issue (forge report line 118). Acceptable as-is; if a future operator surface wants exit rows to carry the closing-leg side, extend the schema in P3d rather than retrofitting here.
3. **MIN-06 (LOW) — `min_liquidity` / `max_time_to_resolution_days` filters not enforced inside `scan()`.** Per spec — no HTTP in scan. Operators are trusted to pre-filter. Forge known issue (forge report line 116). Document upgrade path in P3d if WARP🔹CMD wants stricter enforcement; would require a Polymarket metadata join or a denormalised cache populated by a separate background job.
4. **MIN-07 (LOW) — per-publication-per-user dedup deferred to P3d.** The strategy emits one `SignalCandidate` per surviving publication on every scan tick; without a `signal_following_events` ledger, a P3d scan loop must own per-user dedup before the candidate hits the risk gate (mirrors the P3b copy_trade pattern with `copy_trade_events`). Forge known issue (forge report line 117). This is a P3d implementation contract, not a P3c bug.
5. **MIN-08 (INFO) — migration verified by inspection only.** Mocked-connection tests do not exercise the actual Postgres CREATE / FK / partial-UNIQUE behaviour. Recommend WARP🔹CMD trigger a staging-DB run of `database.run_migrations()` before promoting the lane to a fly.io review env. SQL is idempotent (every CREATE has `IF NOT EXISTS`) so re-runs are safe.

---

## TELEGRAM PREVIEW

Reproduces the operator + user experience the /signals surface ships with. Lifted directly from the handler source — no invented copy.

### `/signals` (Tier 2 user, no args)

```
*/signals* commands:
`/signals list`
`/signals catalog`
`/signals on <feed_slug>`
`/signals off <feed_slug>`

Max 5 active subscriptions per account.
```

### `/signals catalog`

```
*Available signal feeds*

`alpha-feed` · Alpha Politics · 142 subs — Curated US politics signals
`beta-sports` · Beta Sports · 87 subs — NFL + NBA event windows

Subscribe with `/signals on <feed_slug>`.
```

(Operator-supplied `name` and `description` are MD V1-escaped on the way out so a feed name like `Alpha_Beta` cannot break the reply.)

### `/signals on alpha-feed` — happy path

```
✅ Subscribed to `alpha-feed`.
```

### `/signals on alpha-feed` — at the cap

```
❌ You already have 5 active signal subscriptions. Turn one off before adding another.
```

### `/signals on bad slug` — slug rejection

```
❌ Invalid feed slug. Use lowercase letters, digits, `_`, or `-`.
```

### `/signals list` — with subscriptions

```
*Active signal subscriptions*

`alpha-feed` · Alpha Politics · added 2026-05-07
`beta-sports` · Beta Sports · added 2026-05-06
```

Each subscription gets a one-tap `[🛑 Off <name>]` inline button. Callback data: `signals:off:<slug>` — guaranteed ≤ 64 bytes.

### `/signals off alpha-feed`

```
🛑 Unsubscribed from `alpha-feed`.
```

### Tier 1 user attempts `/signals`

```
This action requires Tier 2 (allowlisted) access.
```

(Verbatim message comes from the existing `tier_block_message(min_tier)` helper — not introduced by this lane.)

### Operator-side commands

P3c exposes no operator command surface in this PR. Operators interact with the persistence layer via the `SignalFeedService` Python API (`create_feed`, `publish_signal`, `publish_exit`). A future operator UI is explicitly out of P3c scope (forge report line 7, "Not in Scope: ... operator-side publishing UI").

---

## EVIDENCE INDEX

For the WARP🔹CMD merge review:

- PR: https://github.com/bayuewalker/walkermind-os/pull/892
- Branch: `WARP/CRUSADERBOT-P3C-SIGNAL-FOLLOWING`
- Head SHA: `ae38bcfeb08f21371bc237a91a75cccbb4ea1f3a`
- Forge report: `projects/polymarket/crusaderbot/reports/forge/p3c-signal-following.md`
- This report: `projects/polymarket/crusaderbot/reports/sentinel/p3c-signal-following.md`
- Test command (audit reproducer): `cd projects/polymarket/crusaderbot && python -m pytest tests/ -q` → 428 passed.
- Lint command: `cd projects/polymarket/crusaderbot && python -m ruff check .` → All checks passed.
- Diff scope check: `git diff --stat origin/main…HEAD -- domain/risk/ domain/execution/ services/router.py domain/activation/ config.py .env.example main.py scheduler.py services/redeem/ services/exit_watcher.py` → empty.

---

## NEXT GATE

Return to **WARP🔹CMD** for the final merge decision on PR #892. WARP•SENTINEL does not merge.

After merge:

- P3d (per-user signal scan loop + execution queue wiring + per-publication-per-user dedup) becomes the next MAJOR lane.
- R12 final Fly.io deployment remains blocked on P3c merge + P3d sentinel approval + activation-guard review.
- Activation guards (`EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `ENABLE_LIVE_TRADING`) must remain NOT SET. This sentinel verdict does not authorise any guard flip.

