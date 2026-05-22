# WARP•SENTINEL — CrusaderBot Core Audit 2026-05-21

**Mode:** CORE AUDIT (explicit WARP🔹CMD request)
**Issue:** #1271
**Branch:** `WARP/sentinel-core-audit-2026-05-21`
**Base:** `main` post-WARP-61 (SHA `7cbd8b8`)
**Environment:** prod posture (ENFORCED)
**Tier:** MAJOR
**Auditor:** WARP•SENTINEL

---

## 1. Audit Summary

Full read-only audit across 8 subsystems (Bot Runtime, Backend, Frontend/WebTrader, Telegram, Copy Wallet E2E, Confluence Scalper E2E, Database/Migrations, Safety Invariants). Every finding cites `file:line`. No memory assumptions.

The system is overwhelmingly in good shape. Core trading safety — risk gate (10 steps), execution router (5 activation guards), kill switch, exit watcher, Telegram retry/backoff, fly.toml guards — is correctly implemented and gated. WebTrader and Telegram MVP surfaces are coherent with backend state, presets are aligned across all three call-sites (`bot/presets.py`, `services/notification_service.py`, `webtrader/backend/router.py:_PRESET_PARAMS`, `webtrader/frontend/.../AutoTradePage.tsx:STRATEGY_PRESETS`).

**Critical findings:** 1 (H2 threading import violation — defensive, low blast-radius but explicit CLAUDE.md HARD RULE breach).
**Architectural drift:** 1 P1 (orphaned `copy_targets` scanner alongside the live `copy_trade_tasks` monitor).
**Misc:** 1 P2 (redundant strategy bootstrap call), 1 P3 (legacy filename retained for import stability).

**Verdict:** **BLOCKED** — one hard-rule invariant FAIL. Fix is small (≤10 lines). After remediation, system is APPROVED-eligible.

---

## 2. Safety Invariants (H1–H8) — Explicit PASS/FAIL

| # | Rule | Status | Evidence |
|---|------|--------|----------|
| H1 | No `except: pass` in runtime path | **PASS** | Repo-wide grep over `**/*.py` (excl. tests/archive) returns zero matches. Only doc-string reference is `domain/execution/exit_watcher.py:31` (documenting the rule itself). |
| H2 | No `threading` import in async context | **FAIL (P0)** | `domain/strategy/registry.py:11` `import threading`; lines `30`, `39`, `52` use `threading.Lock()` for singleton double-checked locking. Violates CLAUDE.md HARD RULE *"Concurrency: asyncio only — never threading"*. |
| H3 | No hardcoded secrets / API keys | **PASS** | Regex sweep across `*.py`, `*.toml`, `*.env*` for `api_key|secret_key|password|PRIVATE_KEY =\s*"[A-Za-z0-9]{20,}"`: zero matches outside `os.getenv` / `os.environ`. |
| H4 | No full Kelly (`a=1.0` or `kelly_fraction=1.0`) | **PASS** | `domain/risk/constants.py:30/35/40/47` — risk profiles cap at `kelly: 0.25` (aggressive). `domain/risk/gate.py:358` clamps per-profile kelly against `K.KELLY_FRACTION`. `domain/risk/hardening.py:86` enforces `0 < kelly <= K.KELLY_FRACTION`. |
| H5 | `ENABLE_LIVE_TRADING=false` in fly.toml | **PASS** | `fly.toml:24` — `ENABLE_LIVE_TRADING = "false"` |
| H6 | `EXECUTION_PATH_VALIDATED=false` in fly.toml | **PASS** | `fly.toml:25` — `EXECUTION_PATH_VALIDATED = "false"` |
| H7 | `CAPITAL_MODE_CONFIRMED=false` in fly.toml | **PASS** | `fly.toml:26` — `CAPITAL_MODE_CONFIRMED = "false"` |
| H8 | No `phase*/` folder in repo | **PASS** | `find . -type d -name 'phase*'` under `projects/polymarket/crusaderbot/` returns zero matches. |

**H2 detail:** The `threading.Lock` is used only to guard `StrategyRegistry._singleton` initialization (classic double-checked locking). Functional risk is near-zero (CrusaderBot runs as a single asyncio event loop; the lock is never contended), but the HARD RULE is unconditional. Fix: replace with module-level lazy init (`_singleton = StrategyRegistry()` at import) or `asyncio.Lock` accessed from an async classmethod — the synchronous `instance()` accessor needs lifecycle review.

---

## 3. Bot Runtime (A1–A6)

**A1 Scheduler — PASS.** `scheduler.py:582-685` registers all required jobs:
- `signal_scan` (line 589, interval `SIGNAL_SCAN_INTERVAL`)
- `signal_following_scan` (592)
- `portfolio_snapshots` (616, interval `PORTFOLIO_SNAPSHOT_INTERVAL`) ✓
- `exit_watch` (610)
- `startup_recovery_log` (676) — one-shot `date` trigger calling `log_resumed_open_positions` ✓ (A5)
- `order_lifecycle`, `ws_connect`, `ws_watchdog`, `redeem`, `resolution`, `sweep`, plus 4 cron-based reports.

Job-tracker listener at `scheduler.py:681-684` mirrors `EVENT_JOB_SUBMITTED|EXECUTED|ERROR` into `job_runs`. Per-job try/except wrapping in callables (`sync_markets:51`, `watch_deposits:144`, `run_signal_scan:262/269`) — no crash propagation to the scheduler loop. `asyncio.get_running_loop()` defensive at `scheduler.py:570`.

**A2 Signal scan loop — PASS.** `services/signal_scan/signal_scan_job.py`:
- `_PRESET_ALLOWED` (line 101) correctly maps all 9 presets. `confluence_scalper` → `frozenset({"confluence_scalper"})` only (line 109); `full_auto` and `None` include scalper + lib strategies (110–111); no bleed.
- `_coerce_jsonb` (line 120) normalises JSONB to dict/list with fallback — prevents `ValueError` on non-dict columns.
- Per-user exception isolation: `except Exception as exc` at lines 481, 530, 543, 561, 648, 656, 664 with structured logging; one bad user cannot crash the tick.
- Phase A (lib strategies) + Phase B (`confluence_scalper`) present and ordered (lines 822-836). Registry KeyError → `confluence_scalper_not_registered` debug log (line 780).

**A3 Strategy registry — PASS (with P2 note).** `domain/strategy/registry.py:174-184` `bootstrap_default_strategies` registers all four: `CopyTradeStrategy`, `MomentumReversalStrategy`, `SignalFollowingStrategy`, `ConfluenceScalperStrategy`. Idempotent via `reg.get(cls.name)` → KeyError → register. Called from `main.py:76` (lifespan). **P2:** `main.py:77` also calls `seed_defaults()` which is an alias for the same function (`registry.py:187-191`) — harmless but redundant.

**A4 Kill switch — PASS.** `domain/ops/kill_switch.py:96, 159, 222-228` reads/writes the **`system_settings`** table (not `system_flags`) using key `kill_switch_active` and `kill_switch_lock_mode`. `is_active()` (line 119+) is the gate read by the risk path. History writes to `kill_switch_history` (line 182). Lock mode (line 222-251) cascades: sets `users.auto_trade_on=FALSE` and `user_settings.trading_mode='paper'` atomically inside `conn.transaction()`.

**A5 Exit watcher — PASS.** `services/exit_watcher.py` (referenced via `scheduler.check_exits:343` → `exit_watcher.run_once()`) returns `RunResult` mapped into `job_runs.metadata` (lines 344-349). Startup recovery log (`log_resumed_open_positions`, scheduler 352-384) writes resumed open paper/live counts to `job_runs.metadata` for operator visibility. User-scoping is enforced inside `exit_watcher` via the registry's `list_open_for_exit`.

**A6 Notifications — PASS.** `notifications.py:13` imports `BadRequest, NetworkError, RetryAfter, TimedOut`. Line 26 caps `RetryAfter.retry_after` at 30s; line 32 caps 4 attempts. Line 89-90 retry predicate: `retry_if_exception_type((NetworkError, TimedOut, RetryAfter)) & retry_if_not_exception_type(BadRequest)` — BadRequest excluded from retry (non-transient). `delivery_dropped` logged at `services/notification_service.py:183` and `services/trade_notifications/notifier.py:527`.

---

## 4. Backend System (B1–B7)

**B1 FastAPI main — PASS.** `main.py:51-100` lifespan order:
1. `monitoring_sentry.init_sentry()` (line 56)
2. `validate_required_env()` (61)
3. `init_pool()` (74) → `run_migrations()` (75)
4. `init_cache()` (76)
5. `bootstrap_default_strategies()` (76) + `seed_defaults()` (77) — see A3 P2
6. WebTrader SSE listener (line 85)
7. Telegram bot init/start (87-100)

No import-time side effects bypass lifespan; all global mutable state (`bot_app`, `scheduler_app`, `_webhook_secret`) is set inside `lifespan()`.

**B2 Trade Engine — PASS.** `services/trade_engine/engine.py:130-180` `TradeEngine.execute()`:
- Gate evaluated first (line 141 `_risk_evaluate(gate_ctx)`).
- `_router_execute` (line 180) called ONLY when `gate_result.approved` is true (line 153 short-circuits on rejection).
- Pipeline event logged on every evaluation (lines 145-150).
- Kelly-adjusted size committed via `gate_result.final_size_usdc or signal.proposed_size_usdc` (line 178). No activation-guard mutation inside engine.

**B3 Risk Gate — PASS.** `domain/risk/gate.py`:
- `ForeignKeyViolationError` caught explicitly at line 63 (asyncpg) — demoted to DEBUG path.
- `idempotency_keys` 30-min window at lines 115 (read) and 125 (insert).
- `SIGNAL_STALE_SECONDS=14400` enforced at line 318 (`if age > K.SIGNAL_STALE_SECONDS`).
- All 10 gate steps present (`activation guards → kill switch → cooldown → cooloff → balance → daily loss → drawdown → market liquidity/age → freshness → idempotency`). Confirmed no `except: pass` anywhere in the file.

**B4 Execution Router — PASS.** `domain/execution/router.py:26-80`:
- `chosen_mode == "live"` branch invokes `live_engine.assert_live_guards` (line 35) before any submission.
- Guard failure → audit `live_blocked_fallback_paper` (line 45) → route to paper (line 49). GUARD_BYPASS_ATTEMPT logged at WARNING.
- `LivePostSubmitError` re-raised at line 65 (refuses paper duplication of already-submitted live order — critical).
- `LivePreSubmitError` (line 78) → safe paper fallback.

**B5 Database Layer — PASS (spot-check).** `database.py` exposes `init_pool/get_pool/close_pool/run_migrations`. All DB queries inspected in this audit (kill switch, copy_trade_tasks repo, signal_scan, risk gate, scheduler.watch_deposits, webtrader/backend/router.py) use parameterised `$1`/`$2` placeholders — no string interpolation.

**B6 Admin Endpoints — PASS.** `api/admin.py`:
- Line 1-26: module-level note + `expected = get_settings().ADMIN_API_TOKEN`; raises 503 when unset (line 25-26).
- All 7 endpoints (`/status:31`, `/live-gate:62`, `/dry-run:141`, `/kill:203`, `/force-redeem:212`, `/sentry-test:220`) re-read `Authorization: Bearer` header and compare to `expected` via `secrets.compare_digest` (per pattern at lines 33, 71, 154, 206, 214, 229).
- `/admin/dry-run` synthetic-user path: `ForeignKeyViolationError` demoted to DEBUG (confirmed pattern matches `gate.py:63`).

**B7 Health Endpoint — PASS.** `api/health.py:49-59` `_runtime_mode()` returns `"paper"` whenever ANY of the 3 activation guards is not `true`. `APP_VERSION` resolution at line 108 prefers env, falls back through `FLY_RELEASE_VERSION` → `"unknown"`. Fire-and-forget alert dispatch (line 128) does not extend `/health` latency.

---

## 5. Frontend / WebTrader (C1–C5)

**C1 AutoTradePage — PASS.** `webtrader/frontend/src/pages/AutoTradePage.tsx:15` declares `STRATEGY_PRESETS`. Line 71 = `ensemble`, line 80 = `confluence_scalper` with `name: "Crypto Scalper"` (81), line 89 = `full_auto`. `handleActivatePreset` (line 182) calls `api.activatePreset(key)`. `STRATEGY_PRESETS.map` renders all 9 presets (line 335). Active preset highlight via `find(p => p.key === state.active_preset)` (line 260).

**C2 WebTrader API client — PASS.** `webtrader/frontend/src/lib/api.ts`:
- `Authorization: Bearer ${token}` injected on every authenticated call (line 10).
- `getAutotrade` (41), `activatePreset` (43), `setRiskProfile` (44), `updateMarketFilters` (65) — all typed and present.

**C3 WebTrader backend router — PASS.** `webtrader/backend/router.py`:
- `_PRESET_PARAMS` (line 426) includes `confluence_scalper`: `{risk_profile: "balanced", capital_alloc_pct: 0.40, tp_pct: 0.08, sl_pct: 0.04}` (line 439).
- `POST /autotrade/preset` (451-475): validates key (line 453), DB write (461), returns `{"active_preset": body.preset_key}` (475).
- `GET /autotrade` (line 388+) returns `risk_profile, capital_alloc_pct, tp_pct, sl_pct, active_preset`; line 397 surfaces `active_preset`.
- `/dashboard` (line 605+) returns `trading_mode` (618) and `paper_mode` (634) booleans.
- SSE listener at `webtrader/backend/sse.py` (mounted from `main.py:85`). Channel names visible in router queries — `cb_orders`, `cb_fills`, `cb_positions`, `cb_portfolio` confirmed via downstream mig 029.

**C4 WebTrader build — PASS.** `Dockerfile`:
- Stage 1 (`FROM node:20-slim AS frontend-build`, line 2): `npm ci` (line 5), `npm run build` (line 10), output `/build/dist/` (comment line 11).
- Stage 2 line 32: `COPY --from=frontend-build /build/dist /app/crusaderbot/webtrader/frontend/dist`.
- `main.py:291-293` mounts `/dashboard` via custom `SPAStaticFiles` (line 272) which serves `index.html` for SPA deep links.

**C5 TopBar & Dashboard — PASS.** `webtrader/frontend/src/components/TopBar.tsx`:
- Prop `tradingMode?: string` (line 17), defaulted to `"paper"` (line 24).
- `isLive = tradingMode === "live"` (line 30); Paper banner gated by `!isLive`.
- Analytics decoupling (`Promise.allSettled` in dashboard fetch) verified in router.py response path (paper_mode independent of analytics).

---

## 6. Telegram Bot (D1–D6)

**D1 MVP handler tree — PASS.** `bot/handlers/mvp/` contains: `__init__.py`, `_send.py`, `_users.py`, `autotrade.py`, `copy_wallet.py`, `dashboard.py`, `help.py`, `markets.py`, `onboarding.py`, `portfolio.py`, `settings.py`. All 11 modules present.

**D2 Root menu & routing — PASS (spot-check).** Callback prefix isolation enforced by dispatcher patterns (`copy:*`, `pos:*`, `sf:*`, `set:*`). Onboarding wizard and dashboard reachable from root. No dead-import scan in scope (would require running the bot); however, MVP handler list above has zero references to removed modules.

**D3 Copy Wallet (post WARP-59) — PASS.** `bot/handlers/mvp/copy_wallet.py`:
- Zero `copy_targets` refs (grep clean).
- `_read_wallets` (line 51-54) SELECTs from `copy_trade_tasks` with alias `wallet_address AS address`.
- `do_start_copying` (line 130-196) manual upsert: SELECT existing id (159-160), UPDATE if found (169-171, `copy_mode='fixed'`), else INSERT (184-186) with canonical columns `(user_id, wallet_address, task_name, status, copy_mode, copy_amount, nickname, ...)`.
- `do_pause` (218-225): `UPDATE copy_trade_tasks SET status=...` scoped by user_id.

**D4 Keyboards — PASS (spot-check).** Keyboard builders in `bot/keyboards/mvp/` return `InlineKeyboardMarkup`. Callback data conforms to per-screen prefix convention. No stale references to removed handlers detected in the MVP tree.

**D5 Onboarding wizard — PASS.** `bot/handlers/mvp/onboarding.py` present in tree; full step-by-step state-machine review out of scope for this audit but file is non-empty and registered.

**D6 Presets & settings — PASS.** `bot/presets.py:25` `PRESET_CONFIG` includes `confluence_scalper` (157-161) with `strategies: ["confluence_scalper"]`. `PRESET_ORDER` (177) lists it at index pointing to "confluence_scalper" entry (line 185). Labels: `services/notification_service.py:49` and `services/trade_notifications/notifier.py:126` both map `"confluence_scalper": "🚀 Crypto Scalper"`.

---

## 7. Copy Wallet E2E (E) — P1 ARCHITECTURAL DRIFT

**MVP write path → `copy_trade_tasks`:** ✓ `bot/handlers/mvp/copy_wallet.py:184` INSERT, manual upsert pattern.

**Canonical scanner (`services/copy_trade/monitor.py`):** ✓ Loads via `domain/copy_trade/repository.py:133 list_active_tasks()` which queries `SELECT … FROM copy_trade_tasks WHERE status='active'` (line 22-23). Wired to scheduler as `copy_trade_monitor` job (`scheduler.py:603`).

**P1 FINDING — Orphan scanner still wired:** `domain/signal/copy_trade.py:22-23` `CopyTradeStrategy.scan()` reads from the **legacy `copy_targets` table** (`SELECT id, target_wallet_address, scale_factor, last_seen_tx FROM copy_targets WHERE user_id=$1 AND status='active'`). It writes back `last_seen_tx` to `copy_targets` at line 75. This class is instantiated at `scheduler.py:237` (`_strategies = {"copy_trade": CopyTradeStrategy()}`) and invoked by `run_signal_scan` (line 240) for any user whose `user_settings.strategy_types` contains `"copy_trade"`.

**Impact:** Two parallel scanners exist. The canonical `copy_trade_monitor` (mig 018 path) works. The legacy `CopyTradeStrategy` reads a different table that the MVP no longer writes to (post-WARP-59). Result: in normal MVP usage the legacy scanner is silent (no rows), but if any legacy `copy_targets` data exists (e.g. from `bot/handlers/setup.py:431` or `bot/handlers/copy_trade.py:519`), it will emit candidates that bypass the new task-level controls (`allow_topups`, `copy_direction`, `execution_mode`).

The CORE AUDIT mandate explicitly states `domain/signal/copy_trade.py` should read `copy_trade_tasks` via `list_active_tasks`. It does not. Migration `042_drop_legacy_sessions.sql:8-13` documents the deferred cleanup ("Cleanup of copy_targets requires a coordinated Python removal lane first") — that lane has not landed.

**Recommendation (P1):** Either delete `CopyTradeStrategy` from `domain/signal/copy_trade.py` + remove from `scheduler.py:237/256`, OR rewrite it to delegate to `domain/copy_trade/repository.list_active_tasks` and emit candidates per task. Then run the deferred `DROP TABLE copy_targets` migration (and remove `bot/handlers/setup.py:405-431` + `bot/handlers/copy_trade.py:478-538`).

---

## 8. Confluence Scalper E2E (F) — PASS

- **Strategy:** `domain/strategy/strategies/confluence_scalper.py:114` `_evaluate_market` runs the 5 filter gates inside `scan()` — no `raise` escapes per Phase B contract (verified by no top-level `raise` outside the explicit guard returns).
- **Eligibility:** `domain/strategy/eligibility.py:31` `CONFLUENCE_SCALPER_ASSET_PATTERN` compiled regex with word boundaries (line 64 `pattern.search`). 14-asset list is encoded in the pattern.
- **Phase B scan:** `services/signal_scan/signal_scan_job.py:774-836` — registry lookup with KeyError→None guard (line 780 `confluence_scalper_not_registered` debug), `_preset_allows` gate, exception caught and `user_log.warning("confluence_scalper_run_failed", error=...)` (836), counter incremented (`confluence_signals` per strategy_count line 889).
- **Preset isolation:** `_PRESET_ALLOWED["confluence_scalper"] = frozenset({"confluence_scalper"})` (line 109) — no bleed into lib strategies. `full_auto` and `None` include scalper (110-111) — correct.
- **WebTrader card:** `_PRESET_PARAMS["confluence_scalper"]` present at `webtrader/backend/router.py:439`; frontend renders card at `AutoTradePage.tsx:80` with `name: "Crypto Scalper"`.

---

## 9. Database & Migrations (G) — PASS (with P3)

- **Sequence:** `migrations/001_init.sql` through `045_add_role_column.sql` — sequential, no gaps. Total 45 migrations.
- **`access_tier` column removal:** `migrations/044_drop_access_tier.sql:13` `ALTER TABLE users DROP COLUMN IF EXISTS access_tier`. Migration 045 introduces `users.role` replacement. Python writers of `access_tier` removed per WARP-51 (migration comment line 3-10).
  - **P3 cosmetic:** `bot/middleware/access_tier.py` filename retained for import-path stability (file docstring lines 4-15 explicitly notes the rename was deliberate; module contents are role-based, not tier-based). Acceptable but the filename is a stale signal.
- **`copy_trade_tasks` canonical columns:** mig 018 (base table) + mig 035 (`nickname, copy_direction, execution_mode, allow_topups` extension). Confirmed in `bot/handlers/mvp/copy_wallet.py:184-186` INSERT and `domain/copy_trade/repository.py:76-87` INSERT.
- **`portfolio_snapshots` + `cb_portfolio` NOTIFY:** introduced in mig 029 (`029_webtrader_tables.sql`). Snapshot job wired at `scheduler.py:616` with `PORTFOLIO_SNAPSHOT_INTERVAL`.
- **`job_runs.metadata`:** mig 030. Writer at `scheduler.py:564-568` (`metadata = retval if isinstance(retval, dict) else None`) and `domain/ops/job_tracker.py` (`record_job_event` accepts `metadata` kwarg).
- **`user_strategies` + signal_following enrollment:** mig 010, 012 (backfill), 031 (scanner enrollment). JOIN visible in `services/signal_scan/signal_scan_job.py`.
- **No `threading` import in any migration file** (SQL-only).
- **`copy_targets` table:** NOT dropped (per mig 042 comment) — see P1 in §7.

---

## 10. Deferred / P2 Items

| ID | Severity | File:Line | Issue | Suggested Fix |
|----|----------|-----------|-------|---------------|
| F-001 | **P0** | `domain/strategy/registry.py:11,30,39,52` | `threading` import + `threading.Lock` for singleton — violates H2 HARD RULE. | Replace with module-level eager init: `_default_registry = StrategyRegistry()` and a sync `instance()` returning that. Drop the lock entirely. |
| F-002 | P1 | `domain/signal/copy_trade.py:22-23,75` + `scheduler.py:237,256` | Legacy `copy_targets` scanner still wired; canonical scanner is `services/copy_trade/monitor.py` on `copy_trade_tasks`. Architectural drift; risk of double-signal if any `copy_targets` rows exist. | Delete `CopyTradeStrategy` from `domain/signal/copy_trade.py` and unwire from `scheduler.py:237`. Run deferred `DROP TABLE copy_targets` migration; remove `bot/handlers/setup.py:405-431` + `bot/handlers/copy_trade.py:478-538`. |
| F-003 | P2 | `main.py:76-77` | `bootstrap_default_strategies()` then `seed_defaults()` — the latter is an alias for the former (`registry.py:187-191`). Redundant but idempotent. | Remove line 77 (`seed_defaults()` call). |
| F-004 | P3 | `bot/middleware/access_tier.py` (filename) | Filename retained for import-path stability after `access_tier` → `role` rename. | Rename file to `role_guard.py` (or similar) and update imports in a dedicated lane. Cosmetic only. |

---

## 11. Stability Score (0–100)

| Domain | Weight | Score | Notes |
|--------|-------:|------:|-------|
| Architecture | 20% | 18/20 | Clean domain layout; P1 drift on legacy copy_trade scanner. |
| Functional (scheduler, gate, router) | 20% | 20/20 | All paths intact, ordered correctly. |
| Failure modes (retry, dedup, FK demote) | 20% | 19/20 | RetryAfter capped, idempotency window, FK→DEBUG; -1 for orphan scanner path. |
| Risk rules in code | 20% | 19/20 | Kelly capped at 0.25, full Kelly impossible by code, 5-guard live gate; -1 for H2 invariant breach (small functional risk but rule is unconditional). |
| Infra + Telegram | 10% | 10/10 | 7-alert paths logged, BadRequest excluded from retry, delivery_dropped warn. |
| Latency (declared budgets, not measured) | 10% | 9/10 | Job intervals reasonable; no measurement in scope. |
| **Subtotal** | **100%** | **95/100** | |
| **Hard-rule breach penalty (H2)** | — | **-35** | Any H1–H8 FAIL → automatic BLOCKED per CLAUDE.md Sentinel rules. |
| **Final** | | **60/100** | |

---

## 12. Verdict

**Verdict:** `BLOCKED`

**Rationale:** One HARD RULE invariant (H2 — no `threading` in async context) fails at `domain/strategy/registry.py:11`. Per CLAUDE.md Sentinel rules: *"ANY single critical issue = BLOCKED. No exceptions."* Functional impact is minimal (singleton init only, never contended in a single-loop runtime), but the rule is unconditional and remediation is trivial (≤10 lines of code).

**Path to APPROVED:**
1. Fix F-001 (drop `threading` from `domain/strategy/registry.py`).
2. Optionally land F-002 in same or follow-up lane to retire orphan `copy_targets` scanner.
3. Re-run WARP•SENTINEL audit on the remediation branch; expected verdict `APPROVED` (score ≥ 90).

---

**Score: 60/100 | Verdict: BLOCKED**

**NEXT GATE:** Return to WARP🔹CMD for remediation decision (F-001 fix + re-audit).

