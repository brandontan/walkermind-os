Last Updated : 2026-05-08 18:30 Asia/Jakarta
Status       : Ops dashboard + Tier 2 operator seed (WARP/CRUSADERBOT-OPS-DASHBOARD-TIER2-FIX) FORGE complete on STANDARD / NARROW INTEGRATION. New: GET /ops HTML dashboard (auto-refresh 30s, kill/resume buttons, mobile-friendly inline CSS, no external deps), POST /ops/kill + POST /ops/resume delegating to domain.ops.kill_switch.set_active with audit.log writes tagged source=ops_dashboard_web, scripts/seed_operator_tier.py reading ADMIN_USER_IDS and upserting users at access_tier>=2 (idempotent, exit 0/2/3/4), Fly [deploy] release_command wiring. 42 new tests (17 seed + 25 ops). 556/556 tests green (was 514). Ruff clean on changed files. Activation guards remain NOT SET. Auth on /ops* deferred post-demo (in-code TODO). Lane 1C (CRU-5) PR #908 SENTINEL APPROVED 98/100 awaiting WARP🔹CMD merge. Lane 2C MERGED PR #907. R12 Lane 1B MERGED PR #901. Operator prod verification per runbooks pending — 7 deferred artefacts (Issue #900).

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

[IN PROGRESS]
- Ops dashboard + Tier 2 operator seed — WARP/CRUSADERBOT-OPS-DASHBOARD-TIER2-FIX. Tier STANDARD / Claim NARROW INTEGRATION / SENTINEL NOT REQUIRED. New api/ops.py (GET /ops + POST /ops/kill + POST /ops/resume), scripts/seed_operator_tier.py wired into fly.toml [deploy] release_command, runbook refresh, 42 new tests, 556/556 green, ruff clean. Forge report: projects/polymarket/crusaderbot/reports/forge/ops-dashboard-tier2-fix.md. Awaiting WARP🔹CMD review + merge decision.
- Lane 1C — Demo Data Seeding (CRU-5) PR #908 SENTINEL APPROVED 98/100, awaiting WARP🔹CMD merge. WARP/CRUSADERBOT-DEMO-SEED-DATA. Tier STANDARD / Claim NARROW INTEGRATION. Migration 014 (is_demo flag on 10 tables + rollback block), seed_demo_data.py (DEMO_SEED_ALLOW=1), cleanup_demo_data.py (DEMO_CLEANUP_CONFIRM=1, post-commit verify), docs/runbook/demo-data.md. Forward + idempotent re-run + rollback + re-apply all clean against fresh DB. Seed produces 12 demo markets, 2 feeds, 2 demo users, 10 pubs, 34 paper trades over 7 days; /signals catalog shows 2 active feeds; /pnl ledger sums non-trivial today. Cleanup deletes 135 demo rows leaving non-demo records intact (every DELETE WHERE is_demo=TRUE or FK-chain-to-is_demo=TRUE; single transaction; post-commit verify). 514/514 tests green. Sentinel report: projects/polymarket/crusaderbot/reports/sentinel/demo-seed-data.md.

[NOT STARTED]
- R12 final Fly.io deployment closure (after Lane 1C MERGED + operator prod verification artefacts attached to Issue #900).

[NEXT PRIORITY]
- WARP🔹CMD review + merge decision on WARP/CRUSADERBOT-OPS-DASHBOARD-TIER2-FIX (STANDARD / NARROW INTEGRATION, SENTINEL not required).
- Operator sets `ADMIN_USER_IDS` Fly secret (comma-separated Telegram user ids) so the release_command has work to do on next deploy. Also set `OPS_SECRET` Fly secret — without it `POST /ops/kill` and `POST /ops/resume` return 503 and the dashboard buttons stay disabled (`X-Ops-Token` header or `?token=` param required).
- WARP🔹CMD merge decision on PR #908 (Lane 1C SENTINEL APPROVED 98/100). Optional pre-merge fix-forward on three doc-row 32→34 drifts (forge §1, CHANGELOG entry, runbook table) — non-blocking.
- Operator executes 7 prod verification artefacts per runbooks (Issue #900): /health 200 in prod, Sentry test event in prod project, Fly.io alert simulation, /kill ack < 3s, /resume, /ops_dashboard screenshot, rollback dry-run.
- Activation guards remain NOT SET throughout.

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-R12 cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) — follow-up
- lib/ F401 leakage (LOW, 5 occurrences across lib/strategies/logic_arb.py, lib/strategies/value_investor.py, lib/strategies/weather_arb.py, lib/strategy_base.py) — pre-existing repo-root ruff failure surfaced by Codex on PR #899; deferred to WARP/LIB-F401-CLEANUP (post-demo MINOR) per WARP🔹CMD scope-boundary hold; cross-project impact requires audit before cleanup
- ENABLE_LIVE_TRADING code default in config.py:88 is True (legacy); fly.toml [env] block overrides to "false" so prod posture is correct. Code default disagrees with intent of "all guards default OFF" — deferred to post-demo MINOR alignment lane WARP/config-guard-default-alignment.
- R12 Lane 1B prod verification artefacts (7 deferred Done-Criteria items: /health 200 in prod, Sentry test event in prod project, Fly.io alert simulation timings, /kill ack timing, /resume timing, /ops_dashboard screenshot, rollback dry-run outcome) are runbook-documented but operator-executed; explicitly NOT CLAIMED CLOSED by PR #901. See reports/forge/r12-prod-paper-deploy.md §5b for the full deferred-criteria table. Issue #900 stays open until operator attaches the seven artefacts.


<!-- CD verify: 2026-05-08 00:30 -->
