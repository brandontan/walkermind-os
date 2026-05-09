Last Updated : 2026-05-09 22:30 Asia/Jakarta
Status       : Post-merge sync. PR #908 (Lane 1C Demo Data Seeding, WARP/CRUSADERBOT-DEMO-SEED-DATA, ca5f6f57), PR #910 (Ops Dashboard + Tier 2 Operator Seed, WARP/CRUSADERBOT-OPS-DASHBOARD-TIER2-FIX, cabdc42f), PR #912 (Phase 4B Execution Rewire, WARP/CRUSADERBOT-PHASE4B-EXECUTION-REWIRE, cb920661), and PR #913 (Phase 4C Order Lifecycle, WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE, f326879d) all MERGED to main on 2026-05-08 / 2026-05-09. No open PRs. Activation guards (ENABLE_LIVE_TRADING / USE_REAL_CLOB / EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED) remain NOT SET. Awaiting WARP🔹CMD next-lane dispatch.

[COMPLETED]
- R12e — Auto-Redeem System — PR #869 MERGED 7f8af0b90993 (MAJOR, SENTINEL CONDITIONAL 64/100 — conditions resolved PR #879)
- R12f — Operator Dashboard + Kill Switch + Job Monitor — PR #874 MERGED 2026-05-05 (STANDARD)
- P3a — Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + migration 008) — PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)
- P3b — Copy Trade strategy (CopyTradeStrategy + scaler + wallet_watcher + migration 009 + /copytrade Telegram + registry bootstrap) — PR #877 MERGED 2026-05-06 a369129d (MAJOR, SENTINEL CONDITIONAL 71/100 resolved)
- R12 Live Readiness batch — Live Opt-In Checklist + Live→Paper Auto-Fallback + Daily P&L Summary — PR #883 MERGED 5a9cb22a (STANDARD, NARROW INTEGRATION)
- Cleanup legacy polyquantbot directory — PR #891 MERGED (MINOR, Issue #890 closed)
- P3c — Signal Following strategy — PR #892 MERGED (5ee8487e), MAJOR, SENTINEL APPROVED 100/100
- P3d — Per-user signal scan loop + execution queue wiring — PR #897 MERGED (bb08092), MAJOR, SENTINEL APPROVED 94/100. 464/464 tests green.
- Pre-flight cleanup — F401/MIN-01/02/03/ROADMAP naming drift — PR #899 MERGED (STANDARD, NARROW INTEGRATION, WARP/CRUSADERBOT-PREFLIGHT-CLEANUP)
- R12 Lane 1B — Sentry SDK wiring, /health demo-readiness, /kill /resume aliases, 3 runbooks — PR #901 MERGED (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 95/100, WARP/CRUSADERBOT-R12-PROD-PAPER-DEPLOY)
- Lane 2C — Telegram demo polish (CRU-6) — PR #907 MERGED (MINOR, Claim NONE, WARP/CRUSADERBOT-DEMO-POLISH). /about + /status + /demo + refreshed /start + /help. 60s per-user rate limit on /demo. 22 new tests, 501/501 green at merge.
- Phase 4A CLOB Adapter — PR #911 MERGED (MAJOR, SENTINEL APPROVED 89/100, WARP/CRUSADERBOT-PHASE4A-CLOB-ADAPTER). New integrations/clob/ package: ClobAdapter (EIP-712 L1 + HMAC-SHA256 L2 + builder headers, tenacity 5xx-only retry, 4xx no-retry), MarketDataClient (unauth reads), MockClobClient (deterministic, network-free), get_clob_client() factory (USE_REAL_CLOB default False). 624/624 tests green. Ruff clean. Live callers NOT rewired (Phase 4B). OrderBuilder on-chain schema Phase 4C. Activation guards remain NOT SET.
- Lane 1C — Demo Data Seeding (CRU-5) — PR #908 MERGED 2026-05-08 ca5f6f57 (STANDARD, NARROW INTEGRATION, SENTINEL APPROVED 98/100, WARP/CRUSADERBOT-DEMO-SEED-DATA). Migration 014 (is_demo flag on 10 tables + rollback block), seed_demo_data.py (DEMO_SEED_ALLOW=1), cleanup_demo_data.py (DEMO_CLEANUP_CONFIRM=1, post-commit verify), docs/runbook/demo-data.md. 514/514 tests green at merge. Sentinel report: projects/polymarket/crusaderbot/reports/sentinel/demo-seed-data.md.
- Ops Dashboard + Tier 2 Operator Seed — PR #910 MERGED 2026-05-08 cabdc42f (STANDARD, NARROW INTEGRATION, SENTINEL NOT REQUIRED, WARP/CRUSADERBOT-OPS-DASHBOARD-TIER2-FIX). New api/ops.py (GET /ops + POST /ops/kill + POST /ops/resume), scripts/seed_operator_tier.py wired into fly.toml [deploy] release_command (installed-package path `python -m crusaderbot.scripts.seed_operator_tier`), kill-switch runbook refresh, 42 new tests (17 seed + 25 ops), ruff clean. Auth on /ops* deferred post-demo. Forge report: projects/polymarket/crusaderbot/reports/forge/ops-dashboard-tier2-fix.md.
- Phase 4B Execution Rewire — PR #912 MERGED 2026-05-09 cb920661 (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 92/100, WARP/CRUSADERBOT-PHASE4B-EXECUTION-REWIRE). domain/execution/live.py migrated off py-clob-client SDK onto get_clob_client() / ClobClientProtocol. Dry-run mode, guard routing (incl. USE_REAL_CLOB-when-live), GTC/FOK, idempotency, ClobAuthError + ClobConfigError pre-submit classification, close_position USE_REAL_CLOB=False guard. 27 new hermetic unit tests. Forge report: projects/polymarket/crusaderbot/reports/forge/execution-rewire.md. Sentinel report: projects/polymarket/crusaderbot/reports/sentinel/execution-rewire.md.
- Phase 4C Order Lifecycle — PR #913 MERGED 2026-05-09 f326879d (MAJOR, NARROW INTEGRATION, SENTINEL APPROVED 96/100 FINAL at HEAD a484012, WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE). ClobAdapter extended (tick_size + neg_risk on post_order; cancel_all_orders / get_fills [maker_address+client-side filter] / get_open_orders). domain/execution/lifecycle.py OrderLifecycleManager polls live orders; paper-mode bails to touch+stale (no synthesis); fills derived from client.get_order() payload via _broker_fills. Migration 015_order_lifecycle.sql idempotent (orders columns + new fills table). APScheduler job registered every ORDER_POLL_INTERVAL_SECONDS=30 with max_instances=1, coalesce=True. 29/29 lifecycle tests + 30/30 Phase 4A regression green at HEAD. Forge report: projects/polymarket/crusaderbot/reports/forge/order-lifecycle.md. Sentinel report (FINAL): projects/polymarket/crusaderbot/reports/sentinel/order-lifecycle.md.

[IN PROGRESS]
- None — awaiting WARP🔹CMD next-lane dispatch.

[NOT STARTED]
- R12 final Fly.io deployment closure (operator prod verification artefacts attached to Issue #900).

[NEXT PRIORITY]
- WARP🔹CMD dispatches next development lane.
- Operator sets `ADMIN_USER_IDS` Fly secret (comma-separated Telegram user ids) so the release_command has work to do on next deploy. Also set `OPS_SECRET` Fly secret — without it `POST /ops/kill` and `POST /ops/resume` return 503 and the dashboard buttons stay disabled (`X-Ops-Token` header or `?token=` param required).
- Operator executes 7 prod verification artefacts per runbooks (Issue #900): /health 200 in prod, Sentry test event in prod project, Fly.io alert simulation, /kill ack < 3s, /resume, /ops_dashboard screenshot, rollback dry-run.
- Optional post-merge fix-forward on three Lane 1C doc-row 32→34 drifts (forge §1, CHANGELOG entry, runbook table) — non-blocking.
- Activation guards remain NOT SET throughout.

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-R12 cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) — follow-up
- lib/ F401 leakage (LOW, 5 occurrences across lib/strategies/logic_arb.py, lib/strategies/value_investor.py, lib/strategies/weather_arb.py, lib/strategy_base.py) — pre-existing repo-root ruff failure surfaced by Codex on PR #899; deferred to WARP/LIB-F401-CLEANUP (post-demo MINOR) per WARP🔹CMD scope-boundary hold; cross-project impact requires audit before cleanup
- ENABLE_LIVE_TRADING code default in config.py:153 is True (legacy); fly.toml [env] block overrides to "false" so prod posture is correct. Code default disagrees with intent of "all guards default OFF" — deferred to post-demo MINOR alignment lane WARP/config-guard-default-alignment.
- R12 Lane 1B prod verification artefacts (7 deferred Done-Criteria items: /health 200 in prod, Sentry test event in prod project, Fly.io alert simulation timings, /kill ack timing, /resume timing, /ops_dashboard screenshot, rollback dry-run outcome) are runbook-documented but operator-executed; explicitly NOT CLAIMED CLOSED by PR #901. See reports/forge/r12-prod-paper-deploy.md §5b for the full deferred-criteria table. Issue #900 stays open until operator attaches the seven artefacts.
- integrations/polymarket.py _build_clob_client() is dead code in live execution path (Phase 4B replaced it); still referenced by submit_live_redemption() indirectly. Cleanup deferred to WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP (MINOR, post-Phase-4B merge).


<!-- CD verify: 2026-05-09 16:00 -->
