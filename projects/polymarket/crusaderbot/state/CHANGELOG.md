2026-05-06 08:16 Asia/Jakarta | WARP/CRUSADERBOT-R12-POST-MERGE-SYNC | PR #887 merged — R12 post-merge state sync lane closed. PROJECT_STATE.md pruned to cap + PR #887 entry added. All R12 lanes complete. P3c is next.
2026-05-06 07:27 Asia/Jakarta | WARP/CRUSADERBOT-R12-POST-MERGE-SYNC | [CORRECTION] "All drift resolved" in run-3 entry was premature — ROADMAP R12d/e/f lane naming drift vs PROJECT_STATE+WORKTODO is deferred in KNOWN ISSUES, not resolved. Status-field sync (❌→✅) is complete. Naming restructure requires WARP🔹CMD decision.
2026-05-06 07:20 Asia/Jakarta | WARP/CRUSADERBOT-R12-POST-MERGE-SYNC | state sync run 3 — forge report updated to close Issue #888. All drift resolved. Tier: MINOR.
2026-05-06 07:04 | WARP/CRUSADERBOT-R12-POST-MERGE-SYNC | post-merge state sync for PR #883 (R12 Live Readiness 5a9cb22a): ROADMAP R12d/R12e/R12f marked Done, P3b marked Done (PR #877 a369129d), WORKTODO Right Now updated, PROJECT_STATE NEXT PRIORITY updated to P3c. Closes #884, #885. Tier: MINOR.
2026-05-05 23:55 Asia/Jakarta | WARP/CRUSADERBOT-R12-LIVE-READINESS | R12 Live Readiness batch — three lanes shipped together. (1) domain/activation/live_checklist.evaluate runs 8 gates in fixed order (3 env flags + active subaccount/confirmed deposit + strategy/risk profile configured + 2FA via system_settings 2fa_enabled:{user_id} fail-closed default + Tier 4 operator approval); writes one audit.log row per evaluation; render_telegram emits numbered fix list. /live_checklist Telegram command + CONFIRM-text-dialog gate on autotrade toggle when trading_mode='live' (case-sensitive CONFIRM only — anything else cancels). (2) domain/execution/fallback.trigger flips user_settings.trading_mode='live'→'paper' idempotently with audit + Telegram notify; trigger_all_live_users does single-SQL cascade for the kill-switch lock path. Wired into router (post-submit error + ENABLE_LIVE_TRADING=false pre-submit), risk gate (step 1 kill-switch + step 6 drawdown) only when ctx.trading_mode='live', and ops/kill_switch.set_active(action='lock') (UPDATE user_settings inside the lock txn). Open positions are NOT closed — only NEW signals are deflected. (3) jobs/daily_pnl_summary.run_job registered in scheduler at hour=23 minute=0 anchored to Asia/Jakarta; per-user message: realized P&L (ledger trade_close+redeem today) / unrealized P&L (open positions YES/NO ret formula × size) / fees paid (abs ledger fee today) / open count / exposure% / mode. Opt-in toggle stored as system_settings daily_summary_off:{user_id} (default ON, migration-free). /summary_on, /summary_off Telegram commands. Per-user failures swallowed and counted; batch always returns aggregate stats. 52 new tests across test_live_checklist (14), test_fallback (12 incl. cascade), test_daily_pnl_summary (16), test_activation_handlers (10); full crusaderbot suite 279→331 green. No migrations created. No capital execution logic touched. Tier: STANDARD. Claim: NARROW INTEGRATION.
2026-05-06 05:01 Asia/Jakarta | WARP/CRUSADERBOT-R12-LIVE-READINESS | R12 live readiness batch: Live Opt-In Checklist (8-gate, audit trail, /live_checklist Telegram), Live-to-Paper Fallback (idempotent, open-positions safe, wired into router+risk gate+kill switch), Daily P&L Summary (23:00 WIB scheduler, opt-out via system_settings, migration-free). 331/331 tests green (+52 new). No activation guards set. PR #883 MERGED 5a9cb22a. Tier: STANDARD. Claim: NARROW INTEGRATION.

2026-05-05 23:30 Asia/Jakarta | WARP/CRUSADERBOT-P3A-STRATEGY-REGISTRY | P3a strategy registry foundation: BaseStrategy ABC (scan/evaluate_exit/default_tp_sl), StrategyRegistry singleton with register/get/list_available/get_compatible (semver + name regex + risk-profile validation, duplicate-name ValueError, unknown-name KeyError), four immutable dataclasses (SignalCandidate, ExitDecision, MarketFilters, UserContext) with __post_init__ invariants, migration 008_strategy_tables.sql (strategy_definitions + user_strategies + user_risk_profile, all IF NOT EXISTS, idempotent). 44 new tests, 196/196 suite green. Foundation only — no execution, no signal generation, no risk gate touched. Migration path placed at infra/migrations/ per task spec; runner-path decision deferred to WARP🔹CMD before P3b. Tier: STANDARD. Claim: FOUNDATION ONLY.
2026-05-06 03:07 Asia/Jakarta | WARP/CRUSADERBOT-FIX-MIGRATION-PATH | fix(crusaderbot): move 008_strategy_tables.sql from infra/migrations/ to migrations/ (PR #881 — 538fd999). FILE MOVE ONLY — similarity 100%, zero byte delta. Runner database.run_migrations() now applies strategy tables (008) at startup. Tier: MINOR. Claim: FILE MOVE ONLY.
2026-05-06 02:55 Asia/Jakarta | WARP/CRUSADERBOT-P3B-COPY-TRADE | P3b copy-trade strategy (PR #877 — a369129d): CopyTradeStrategy scan() + evaluate_exit() + scaler.scale_size + wallet_watcher (5s timeout, 1 req/s rate limit) + migration 009_copy_trade.sql (copy_targets UNIQUE user_id+wallet + copy_trade_events UNIQUE per-follower dedup) + /copytrade Telegram (Tier 2 gate, MAX 3 cap, 0x validator) + registry bootstrap_default_strategies() idempotent. 49 new tests, 245/245 green. SENTINEL CONDITIONAL 71/100 resolved (MAJ-01 migration runner path fixed, MAJ-02 private attr access fixed). Tier: MAJOR. Claim: STRATEGY SIGNAL GENERATION.

2026-05-05 19:10 UTC | WARP/CRUSADERBOT-R12F-OPERATOR-DASHBOARD | R12f operator dashboard built: /ops_dashboard, /killswitch (pause|resume|lock), /jobs, /auditlog. New domain.ops.kill_switch (30s cached non-blocking is_active), domain.ops.job_tracker + APScheduler listener, migration 007_ops.sql (system_settings + kill_switch_history + job_runs, idempotent). Risk gate step [1] now reads via the cached module; legacy database.is_kill_switch_active delegates. Operator-only gate (silent reject). 51 new tests, 140/140 suite green. Tier: STANDARD. Claim: OPERATOR TOOLING ONLY.

2026-05-05 07:49 UTC | #869 feat(crusaderbot): R12e auto-redeem system — 7f8af0b90993 | SENTINEL APPROVED 92/100, 0 critical. NARROW INTEGRATION: instant+hourly workers, redeem_queue, Settings UI, 87/87 tests. EXECUTION_PATH_VALIDATED gate maintained.

---
- 2026-05-06 -- gate: WORKTODO.md + ROADMAP.md + PROJECT_STATE.md full state sync (gate-bot) -- e7d60b89
- 2026-05-05 -- R12f operator dashboard + kill switch -- merge #874 -- STANDARD
- 2026-05-05 -- R12e auto-redeem FORGE -- merge #869 -- MAJOR
- 2026-05-06 — SENTINEL r12e-auto-redeem CONDITIONAL 64/100 — conditions resolved — merge #879 — d74affe4
## 2026-05-05 05:04 UTC — gate: post-merge sync PR #868 [warp-gate[bot]]
- `2026-05-05T11:57:54Z` — feat(crusaderbot): P3a strategy registry foundation (#876) — `4efcbe51`


feat(crusaderbot): R12d telegram position UX merged (#868) — commit 4f5e12201964. Live position monitor (Positions menu): CLOB midpoint mark price (3s cap), unrealized P&L, applied TP/SL. Per-position Force Close: Tier 3 gate, confirmation dialog, ownership-checked DB marker. 20 new tests. Delegates to R12c exit watcher. STANDARD | NARROW INTEGRATION.


2026-05-05 19:45 | WARP/CRUSADERBOT-R12C-EXIT-WATCHER | R12c exit watcher: per-position async worker with priority chain (force_close_intent > tp_hit > sl_hit > strategy_exit > hold), applied_tp_pct/applied_sl_pct snapshot fields with DB-trigger immutability + frozen registry dataclass, close-with-retry helper (1 retry, 5s backoff), close_failure_count tracking + persistent-failure operator alert, five user-side alerts (TP/SL/force-close/strategy-exit/close-failed), migration 005 idempotent (ADD COLUMN IF NOT EXISTS + DO $$ pg_trigger guards + backfill from legacy tp_pct/sl_pct/force_close), emergency.pause_close migrated to position registry, scheduler.check_exits delegates to exit_watcher.run_once. 22 new tests pass, 49/49 total, ruff clean. Tier: MAJOR. Claim: FULL RUNTIME INTEGRATION.

## 2026-05-05 08:35 Asia/Jakarta — gate: R12a CI/CD pipeline ratified (PR #855) [warp-gate[bot]]

WARP•GATE retrospective review — PR already merged 2026-05-04T19:57:21Z.

CHECK-01 PASS — Branch WARP/CRUSADERBOT-R12A-CICD-PIPELINE ✅ valid format
CHECK-02 PASS — Tier: STANDARD, Claim: NARROW INTEGRATION, source: r12a-cicd-pipeline.md ✅
CHECK-03 PASS — No hardcoded secrets/API keys. FLY_API_TOKEN via secrets.* only. No full Kelly. No threading. No silent except. Activation guards all "false" in fly.toml ✅
CHECK-04 PASS — Forge report at reports/forge/r12a-cicd-pipeline.md ✅. Branch ref correct ✅
CHECK-05 PASS — Task scope: CI lint/test + CD deploy scaffold. Actual files: 2 workflows, Dockerfile, fly.toml, pyproject.toml ruff block, tests stub. Fully aligned ✅
CHECK-06 PASS — Claim NARROW INTEGRATION matches evidence (path-scoped CI/CD only, no runtime Python modified) ✅
CHECK-07 PASS — No circular imports. Workflows use pinned actions (checkout@v4, setup-python@v5) ✅
CHECK-08 PASS — test_smoke.py is a CI stub (assert True, sys.version check) — appropriate for R12a scope ✅
CHECK-09 PASS — No dead code. No stubs in production paths ✅

VERDICT: ALL 9 CHECKS PASS. STANDARD tier. Already merged — ratified ✅
GATE ACTION: Post-ratification record only (PR merged pre-gate-pipeline activation).

---

## 2026-05-05 08:35 Asia/Jakarta — gate: removed deprecated WARP Issue Dispatch workflow [warp-gate[bot]]

Deleted: .github/workflows/warp-issue-dispatch.yml (8342 bytes)
Commit: 370137561b1f — author: warp-gate[bot]
Reason: References deprecated "Ona" agent (Gitpod environment, 14 references).
        Ona/Gitpod dispatch is no longer part of WalkerMind OS agent roster.
        Deprecated names per AGENTS.md: NEXUS, FORGE-X, BRIEFER, Ona — NEVER USE.
warp-codx: No dispatch workflow found — clean ✅

---

## 2026-05-05 08:23 Asia/Jakarta — [GATE NOTE] Pre-bot-setup commits attributed to bayuewalker

### Context
GATE identity fix applied 2026-05-05 08:23 WIB. All GATE auto-commits from this point forward
use author override: `warp-gate[bot] <warp-gate[bot]@users.noreply.github.com>` via GitHub
Contents API author field (Option C). Underlying OAuth token remains bayuewalker — see Issue #864
for Option A (GitHub App) backlog.

### Pre-fix commits attributed to bayuewalker (not warp-gate[bot])
- `4eda17c5` — gate: post-merge sync for #861 — PROJECT_STATE.md [warp-gate-bot]
  INCIDENT: Python Unicode escape SyntaxError caused 0-byte content — file wiped. Recovered in c1bf7cf7.
- `c1bf7cf7` — gate: post-merge sync for #861 — PROJECT_STATE.md restored + updated [warp-gate-bot]
  Recovery commit. Content correct.
- `a64e9582` — gate: post-merge sync for #861 — CHANGELOG.md [warp-gate-bot]
  Normal post-merge sync. Content correct.

### Fix applied
- gateWebhook.ts: added GATE_BOT_AUTHOR constant + gateBotCommitBody() helper
- All future GATE direct commits pass explicit author/committer fields to GitHub API
- Root cause documented in Issue #864 (systemic — pre-commit content guard missing)

## 2026-05-05 08:15 Asia/Jakarta — ROADMAP R12b drift fix + WORKTODO init

### Merged
- PR #861: chore(crusaderbot): state sync — ROADMAP R12b drift fix + WORKTODO init
  STANDARD | FOUNDATION. Resolved two carry-forward gaps from PR #857/#858 syncs.
  Closes #859.

### Changes
- projects/polymarket/crusaderbot/state/ROADMAP.md — R12b row: Not Started → Done (Merged via PR #856)
- projects/polymarket/crusaderbot/state/WORKTODO.md — created (was missing)
- projects/polymarket/crusaderbot/state/CHANGELOG.md — lane closure entry appended
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md — Last Updated + NEXT PRIORITY updated
- projects/polymarket/crusaderbot/reports/forge/crusaderbot-state-fix.md — forge report added

### State
- R12b complete. WORKTODO.md initialized. R12a CI/CD pipeline PR open: WARP/CRUSADERBOT-R12A-CICD-PIPELINE — awaiting WARP🔹CMD review.
- Paper mode only. All activation guards OFF.

## 2026-05-05 06:06 Asia/Jakarta — State Sync (PR #857 post-merge)

### Merged
- PR #858: chore(crusaderbot): state sync — PR #857 post-merge
  WARP•ECHO routine. Updated PROJECT_STATE.md (PR #858 completed entry added) and CHANGELOG.md (PR #857 sync entry prepended).

### Changes
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md — PR #858 state sync entry added to [COMPLETED]; Last Updated bumped to 06:06
- projects/polymarket/crusaderbot/state/CHANGELOG.md — PR #857 state sync entry prepended

### State
- R12b complete. R12a CI/CD pipeline PR open (WARP/CRUSADERBOT-R12A-CICD-PIPELINE), awaiting WARP🔹CMD review.
- WORKTODO.md not initialized for CrusaderBot — skipped.
- Paper mode only. All activation guards OFF.

## 2026-05-05 05:46 Asia/Jakarta — State Sync (PR #856 post-merge)

### Merged
- PR #857: chore(crusaderbot): state sync — PR #856 post-merge
  WARP•ECHO routine. Updated PROJECT_STATE.md (R12b merged, R12a in progress) and CHANGELOG.md (R12b entry prepended).

### Changes
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md — Status updated post R12b merge; [COMPLETED] R12b entry added; [IN PROGRESS] R12b removed
- projects/polymarket/crusaderbot/state/CHANGELOG.md — R12b Fly.io Health Alerts entry prepended

### State
- R12b complete. R12a CI/CD pipeline PR open (WARP/CRUSADERBOT-R12A-CICD-PIPELINE).
- WORKTODO.md not initialized for CrusaderBot — skipped.
- Paper mode only. All activation guards OFF.

## 2026-05-05 05:00 Asia/Jakarta — R12b Fly.io Health Alerts

### Merged
- PR #856: feat(crusaderbot): R12b observability — /health probes + operator alerts + JSON logging
  Health probes for 4 deps (database, telegram, alchemy_rpc, alchemy_ws) with asyncio 3s timeout per check, Telegram operator alerts with 2-consecutive-failure threshold + 5-min cooldown per key, JSON request logging, fly.toml 10s interval/grace.

### Changes
- monitoring/health.py — 4-dependency probe with asyncio.wait_for 3s timeout per check
- monitoring/alerts.py — Telegram operator-alert dispatcher (2-fail threshold, 5-min cooldown)
- monitoring/logging.py — JSON formatter + RequestLogMiddleware (method/path/status_code/duration_ms)
- config.py — REQUIRED_ENV_VARS + validate_required_env() key-only; Optional[str] ALCHEMY_WS alias
- api/health.py — route returns documented JSON shape, feeds alert dispatcher
- main.py — env validation + Fly.io machine-restart alert + boot-time dependency probe
- fly.toml — http_checks interval 15s → 10s, grace_period 30s → 10s

### State
- R12b closed. R12a CI/CD pipeline PR open (WARP/CRUSADERBOT-R12A-CICD-PIPELINE).
- All activation guards OFF — paper mode only.
- ROADMAP.md R12b row needs ✅ Done update. WORKTODO.md not initialized for CrusaderBot.

2026-05-04 19:00 | WARP/CRUSADERBOT-R12B-HEALTH-ALERTS | observability layer: /health probes 4 deps with 3s timeout, Telegram operator alerts (2-fail threshold + 5-min cooldown), startup env validation (key-only), JSON request logging, fly.toml interval=10s/grace=10s

## 2026-05-05 00:10 Asia/Jakarta — R1-R11 Import + SENTINEL PASS

**Branches:** `WARP/CRUSADERBOT-REPLIT-IMPORT` → main (PR #852); `claude/audit-crusaderbot-import-Ar983` → main (PR #853, SENTINEL worktree audit)

### Merged
- PR #852: feat(crusaderbot): import full Replit build R1-R11
  42 files, 4,280 lines. Supersedes R1-R4 stubs (PRs #847-#850).
  Source: Replit commit 86f6e55e (6 internal review rounds).
- PR #853: sentinel: crusaderbot-replit-import PASS (post C1/C2/C3 fix)

### SENTINEL findings resolved
- C1: KELLY_FRACTION applied in live sizing path
      capital_alloc_pct capped at <1.0 (max 0.95)
- C2: migrations/004 fully idempotent (DO $$ IF NOT EXISTS)
- C3: Tier 3 promotion gated on MIN_DEPOSIT_USDC cumulative balance

### P1 fixes (pre-SENTINEL)
- deposits unique on (tx_hash, log_index)
- live.close_position: atomic DB claim before SELL submit
- polygon.scan_usdc_transfers: log_index passthrough

### State
- Paper-default: all live activation guards OFF
- PTB: python-telegram-bot pinned >=21.0,<22.0
- Next: R12a CI/CD Pipeline

2026-05-04 00:28 | WARP/crusaderbot-r1-skeleton | R1 skeleton lane. PROJECT_REGISTRY updated (CrusaderBot path → projects/polymarket/crusaderbot, polyquantbot DORMANT). New project tree at projects/polymarket/crusaderbot/ with FastAPI app (main.py + asynccontextmanager lifespan: DB → Redis → migrations → Telegram polling → reverse on shutdown), pydantic-settings config (12 required env vars fail-fast on import + 5 activation guards default OFF), asyncpg pool with rerun-safe run_migrations() (idempotency check on users table), redis.asyncio cache wrapper (JSON serialize internally + ping/get/set/delete), api/health (GET /health + GET /ready returns db/cache/live_trading/paper_mode), bot/dispatcher (Telegram /start "👋 CrusaderBot online. Paper mode active." + /status guard-state visibility), domain/risk/constants (Kelly=0.25, MAX_POSITION_PCT=0.10, MAX_CORRELATED_EXPOSURE=0.40, MAX_CONCURRENT_TRADES=5, DAILY_LOSS_HARD_STOP=-2000, MAX_DRAWDOWN_HALT=0.08, MIN_LIQUIDITY=10000, MIN_EDGE_BPS=200 + 3 risk profiles + STRATEGY_AVAILABILITY + effective_daily_loss most-restrictive helper). migrations/001_init.sql: 16 main-schema tables (users, sessions, wallets, deposits, ledger, user_settings, copy_targets, markets, orders, positions, risk_log, idempotency_keys, fees, referral_codes, kill_switch with seed FALSE row) + audit schema (audit.log) + all indexes. .env.example (no real secrets) + pyproject.toml (Poetry, package-mode=false, all blueprint deps incl. python-telegram-bot/asyncpg/redis/web3/eth-account/py-clob-client/structlog/pydantic-settings) + README. State files (PROJECT_STATE, ROADMAP, CHANGELOG) initialized for new project root. NOT in scope: HD wallet derivation (R2), deposit watcher (R4), signal engine (R6), risk gate execution (R7), paper exec (R8), tests. Documentation + skeleton only — paper mode, all guards OFF, no live trading, no real wallet ops. Tier: STANDARD. Claim: FOUNDATION.

2026-05-04 12:10 | WARP/CRUSADERBOT-R3-ALLOWLIST | R3 operator allowlist + Tier 2 gate lane. New services/allowlist.py: AllowlistStore (asyncio.Lock-guarded set[int]) + module-level helpers add_to_allowlist / remove_from_allowlist / is_allowlisted / get_user_tier (returns 1 if not in allowlist, 2 if in) + tier_label. New bot/middleware/tier_gate.py: require_tier(min_tier) decorator that short-circuits with TIER_DENIED_MESSAGE for under-tier callers (scaffolded but not applied to any current command — R5+ /config, /strategy, /risk, /paper handlers will use it). New bot/handlers/admin.py: handle_allowlist subcommand router for /allowlist [add|remove|list], operator-only via OPERATOR_CHAT_ID match (UNAUTHORIZED reply for non-operator). bot/dispatcher.py modified: registered /allowlist with partial(handle_allowlist, config=) binding; /status now prepends caller's tier (Tier 1 — Browse only / Tier 2 — Community allowlisted) above guard states. /start, /help, /status remain unrestricted across tiers per task spec. main.py UNCHANGED (allowlist is module-level singleton like db/cache — no injection needed). OPERATOR_CHAT_ID reused (no new env var added) per WARP🔹CMD direction. Persistence to Postgres deferred. NOT in scope: trading logic, wallet logic, activation guards, fee system, applying tier gate to existing commands. Tier: STANDARD. Claim: FOUNDATION.

2026-05-04 08:36 | WARP/crusaderbot-r2-onboarding | R2 onboarding + HD wallet generation lane. New wallet/ module: generator.py (derive_address via eth_account BIP44 m/44'/60'/0'/0/{hd_index}, encrypt_pk/decrypt_pk via Fernet) + vault.py (get_next_hd_index from MAX(hd_index)+1, store_wallet, get_wallet — DB UNIQUE constraints on hd_index/deposit_address catch race-condition inserts). New services/ module: user_service.py (get_or_create_user UPSERT keyed on telegram_user_id with COALESCE username refresh, get_user_by_telegram_id, bump_tier with audit.log entry inside same transaction + SELECT FOR UPDATE row lock). New bot/handlers/onboarding.py: handle_start full flow — upsert user → get_wallet → if missing then derive+encrypt+store → reply with welcome + deposit address (markdown tap-to-copy) + min deposit + /menu hint. Idempotent: second /start returns existing address. Private key derived locally, encrypted immediately, variable dropped before any await — never logged, never surfaced in reply. bot/dispatcher.py replaced inline start_handler with partial(handle_start, pool=, config=) binding via functools.partial; setup_handlers(app, *, db_pool, config) signature now requires both keyword-only args (fails fast at startup). main.py lifespan modified (1-line change beyond original task spec — flagged in forge Known Issues) to pass db.pool + settings into setup_handlers. Post-merge sync from PR #847: ROADMAP R1 → ✅ Done; PROJECT_STATE COMPLETED includes R1 skeleton merge. NOT in scope: deposit detection (R4), wallet import, WalletConnect, Tier 2 allowlist (R3), strategy config (R5), signing, live trading, tests. Tier: STANDARD. Claim: FOUNDATION.

2026-05-04 18:30 | WARP/CRUSADERBOT-R4-DEPOSIT-WATCHER | R4 deposit watcher + ledger crediting lane. New services/deposit_watcher.py: asyncio background task subscribing to USDC Transfer events on Polygon via Alchemy WebSocket (eth_subscribe logs filter on USDC contract + Transfer topic), in-process address-map filter (refreshed every 60s) maps to user_id+telegram_user_id, idempotent insert into existing deposits table (UNIQUE tx_hash from R1), credit to sub_account ledger, Tier 3 promotion via user_service.bump_tier on balance >= MIN_DEPOSIT_USDC, Telegram notification "💰 Deposit confirmed: +$X.XX USDC". Reconnect with exponential backoff (1s -> 60s cap), per-event isolation (single bad log won't kill loop). New services/ledger.py: ensure_sub_account / get_balance / credit / debit (scaffold) / get_entries — asyncio.Lock-guarded credit/debit with append-only ledger_entries (sub_account scoped). New db/schema_r4.sql: sub_accounts (1:1 with users via UNIQUE) + ledger_entries (sub_account_id keyed) — IF NOT EXISTS guards; legacy ledger and existing deposits table from R1 untouched. database.run_migrations now also applies schema_r4.sql on every startup (idempotent). New bot/handlers/wallet.py: /wallet (open) shows address+balance+tier label (effective tier = max(db_tier, allowlist_tier)); /deposit (Tier 2+ via require_tier(TIER_ALLOWLISTED)) shows deposit instructions. bot/dispatcher.py registers both via partial(pool=, config=). main.py lifespan starts DepositWatcher after Telegram polling, stops it first on shutdown. config.py + .env.example: added ALCHEMY_POLYGON_RPC_URL, ALCHEMY_POLYGON_WS_URL, USDC_CONTRACT_ADDRESS (native USDC 0x3c499...). pyproject.toml: added websockets ^12.0. Paper mode preserved; all activation guards remain OFF; no real sweep / withdraw / Tier 4 in this lane. Tier: MAJOR. Claim: MAJOR.

2026-05-05 02:00 | WARP/CRUSADERBOT-R12A-CICD-PIPELINE | R12a CI/CD pipeline scaffold lane. New .github/workflows/crusaderbot-ci.yml: lint+test on push to WARP/** and PR to main, path-scoped to projects/polymarket/crusaderbot/** + the workflow file; Python 3.11 with pip cache, installs ruff+pytest only (lean tooling — full deps stay in Docker), runs ruff check . and pytest tests/ -v --tb=short from the crusaderbot working directory; fail-fast, 10-min timeout, concurrency cancels superseded runs. New .github/workflows/crusaderbot-cd.yml: deploys to Fly.io on push to main with the same path filter; uses superfly/flyctl-actions/setup-flyctl@master then flyctl deploy --remote-only --config projects/polymarket/crusaderbot/fly.toml; FLY_API_TOKEN sourced exclusively from secrets.FLY_API_TOKEN (no hardcoding); environment: production slot for future required-reviewer rule; 15-min timeout. New tests/__init__.py + tests/test_smoke.py: trivial pytest entry stub (assert True + sys.version_info >= (3, 11)) — no project imports, no runtime deps required. Dockerfile updated: added non-root system user app (uid/gid 1001), chown -R app:app /app, USER app before CMD; base image (python:3.11-slim), build deps, pyproject install path, and uvicorn entry unchanged. fly.toml updated: header comment documents secrets handling (fly secrets set, never the file); [env] extended with seven activation guards (ENABLE_LIVE_TRADING, EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, RISK_CONTROLS_VALIDATED, SECURITY_HARDENING_VALIDATED, FEE_COLLECTION_ENABLED, AUTO_REDEEM_ENABLED) all "false"; app, region (sin), build, [[services]] internal_port 8080, /health http_check, [metrics], and VM size unchanged. No Python source modified. No real secrets committed. Paper-default preserved end-to-end. Tier: STANDARD. Claim: NARROW INTEGRATION.

2026-05-05 06:18 | WARP/CRUSADERBOT-STATE-FIX | state sync: ROADMAP.md R12b row corrected to Done (PR #856), WORKTODO.md initialized for CrusaderBot

2026-05-04 19:30 | WARP/CRUSADERBOT-R4-DEPOSIT-WATCHER | R4 follow-up — addressed Codex P1 review on PR #850. (1) Atomicity: deposit insert + sub_account upsert + ledger_entries insert now run inside one async with conn.transaction() block in deposit_watcher._credit_deposit (no partial-success window where deposit row exists without ledger row). (2) Log-level idempotency: db/schema_r4.sql additionally adds log_index INTEGER NOT NULL DEFAULT 0 to deposits, drops original UNIQUE (tx_hash) (deposits_tx_hash_key), and adds composite UNIQUE (tx_hash, log_index) — guarded with idempotent IF EXISTS / IF NOT EXISTS DO blocks for rerun safety; deposit_watcher parses logIndex from Alchemy log frames and INSERTs ON CONFLICT (tx_hash, log_index). Refuses logs with no logIndex (cannot dedupe). (3) Reorg gate: deposit_watcher._handle_log now checks log_obj.removed and skips with deposit_watcher.removed_log_skipped warning before any DB write. Reorg-reversal of already-credited deposits is documented as deferred (confirmation-delay model recommended before live activation). Forge report sections 1-2-4-5 updated to reflect; manual verification path expanded with replay-by-(tx_hash,log_index) and removed=true synthetic case.

2026-05-05 21:30 | WARP/CRUSADERBOT-R12D-TELEGRAM-POSITION-UX | R12d Telegram position UX lane. New bot/handlers/positions.py (show_positions / force_close_ask / force_close_confirm) — live position monitor on the 📈 Positions reply-keyboard surface listing every open position with market title (40-char trunc), side, size, avg entry, CLOB midpoint mark price (asyncio.wait_for 3s budget per fetch, gather'd across rows; degrades to "price unavailable" on timeout/empty book), unrealized P&L (USDC + %, YES = (mark-entry)*shares / NO = (entry-mark)*shares, defensive zero-entry guard), and applied_tp_pct/applied_sl_pct snapshot. Tier 2 view / Tier 3 force close via the existing _ensure(update,min_tier) pattern (matches dashboard.py convention; the require_tier decorator wants a pool kwarg this surface does not thread). Per-row [🛑 Force Close <id6>] inline button → "Close <market>? This cannot be undone." confirm dialog → on Confirm calls bot.handlers.emergency.mark_force_close_intent_for_position (new — single-position SQL UPDATE WHERE id=$1 AND user_id=$2 AND status='open' AND force_close_intent=FALSE; idempotent; audit.write self_force_close_position) which the R12c exit watcher consumes on its next tick via the priority chain. Cancel branch writes no marker and no audit entry. New bot/keyboards/positions.py (positions_list_kb + force_close_confirm_kb). New bot/menus/main.py — single source of truth for reply-keyboard label → handler routes; bot/dispatcher.py rewired to delegate via menus.main.get_menu_route + register the new ^position:fc_ask: and ^position:fc_(yes|no): callback patterns. bot/keyboards.py converted to bot/keyboards/__init__.py (verbatim git mv) so the new bot/keyboards/positions.py module fits as a sibling — all existing from ..keyboards import ... resolve unchanged. New tests/test_positions_handler.py — 20 hermetic tests (no DB, no broker, no Telegram): P&L formula YES/NO/loss/zero-entry, formatters, mark fetch midpoint/empty/timeout/no-token/one-sided, keyboard builders, force_close_confirm cancel-no-marker / yes-success / yes-already-queued / yes-position-missing. Full suite 73/73 pass (53 pre-existing + 20 new). NOT in scope: auto-trade toggle, dashboard/portfolio view, withdrawal flow, exit_watcher, order router, risk gate, entry flow, applied_* mutation, activation guards. Legacy dashboard.positions / dashboard.close_position_cb left in place pending WARP🔹CMD retire decision. Tier: STANDARD. Claim: NARROW INTEGRATION.

2026-05-05 05:04 | WARP/CRUSADERBOT-R12D-TELEGRAM-POSITION-UX | R12d telegram position UX: live position monitor (📈 Positions) on main menu + per-position force-close inline button (Tier 3 gated), mark_force_close_intent_for_position idempotent write delegated to R12c exit_watcher priority chain, show_positions asyncio.gather mark-price fetches (3s budget, graceful fallback on timeout/empty book), unrealized P&L formula (YES/NO), tier gates, 20 new tests all pass, 73/73 total. Tier: STANDARD. Claim: NARROW INTEGRATION.
2026-05-05 18:30 | WARP/CRUSADERBOT-R12E-AUTO-REDEEM | R12e auto-redeem system lane. New services/redeem/ module (__init__, redeem_router, instant_worker, hourly_worker) extracts the R10 inline redeem block from scheduler.py and adds the missing failure-tracking + operator-alert surface. New migration 006_redeem_queue.sql creates the redeem_queue table (UUID PK, position_id UNIQUE, status pending|processing|done|failed, failure_count, last_error) with a partial index on pending status and another on failure_count>0; also re-asserts user_settings.auto_redeem_mode for stale staging DBs (idempotent ADD COLUMN IF NOT EXISTS). redeem_router.detect_resolutions polls for newly-resolved markets, atomically flips the markets row, then classifies each position: losers settle inline (status=closed, exit_reason=resolution_loss, pnl=-size, audit redeem_loss, Telegram notify — no on-chain action); winners are enqueued idempotently (ON CONFLICT (position_id) DO NOTHING) and, when the user's auto_redeem_mode='instant', an asyncio task is fired into instant_worker.try_process. instant_worker claims atomically (pending→processing), gates live positions on polygon.gas_price_gwei() > INSTANT_REDEEM_GAS_GWEI_MAX (release without failure penalty on spike OR gas read failure), submits via settle_winning_position, retries once after asyncio.sleep(30) on raise, and on second raise releases with failure_count++ so hourly catches it. hourly_worker.run_once drains all pending rows sequentially (1 tx per position — CTF constraint), increments failure_count on raise, and pages monitoring.alerts._dispatch('redeem_failed_persistent', queue_id, body) once failure_count>=2 (per-key cooldown reuses existing alert path). Every entry point short-circuits with INFO log when AUTO_REDEEM_ENABLED=False (no raise, no crash). New bot/handlers/settings.py + bot/keyboards/settings.py implement the ⚙️ Settings menu with the auto-redeem mode picker (Instant/Hourly, default Hourly, info text "Instant uses more gas. Hourly batches redeems."); bot/dispatcher.py registers the ^settings: callback pattern; bot/menus/main.py routes ⚙️ Settings reply-keyboard label to settings_root (was a placeholder pointing at help_handler). scheduler.py shrunk: check_resolutions and redeem_hourly are now 1-line delegations to the new module; the inline _instant_redeem_for_market / _redeem_position / _ensure_live_redemption helpers are removed (logic moved to redeem_router for symmetry across both workers). New tests/test_redeem_workers.py adds 14 hermetic tests (no DB, no Polygon, no Polymarket, no Telegram) covering activation guard short-circuits, paper success no-gas-check, live gas spike defer, gas RPC failure defer, retry-success-on-second-attempt, double-failure release, race-safe claim returning None, hourly success, hourly increment-no-alert below threshold, hourly alert at threshold, hourly per-row exception isolation, hourly empty-queue noop. Full crusaderbot suite 87/87 pass (73 pre-existing + 14 new). Migration path deviation flagged: task spec said infra/migrations/ but the loader reads migrations/ — used the existing convention so the SQL actually runs at startup (SENTINEL to confirm). Gas threshold deviation flagged: task body said 100 gwei, code uses configurable Settings.INSTANT_REDEEM_GAS_GWEI_MAX (default 200, env-overridable). NOT in scope: exit_watcher, entry flow, risk gate, Kelly sizing, applied_tp/sl_pct, wallet generator, deposit watcher, fee collection, referral payouts, other activation guards, AUTO_REDEEM_ENABLED default flip (R10 inheritance — task forbids touching activation guards), wallet/ledger.py. Tier: MAJOR. Claim: NARROW INTEGRATION.

2026-05-06 07:02 | WARP/CRUSADERBOT-R12-POST-MERGE-SYNC | post-merge state sync: ROADMAP R12d/R12e/R12f marked Done (PR #883), P3b marked Done (PR #877), WORKTODO Right Now updated to P3c lane, PROJECT_STATE NEXT PRIORITY updated
