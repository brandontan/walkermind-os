Last Updated : 2026-05-08 05:37 Asia/Jakarta
Status       : Pre-flight cleanup WARP/CRUSADERBOT-PREFLIGHT-CLEANUP MERGED PR #899 (STANDARD, NARROW INTEGRATION). Strategy plane (P3a/P3b/P3c/P3d) complete. R12 final Fly.io deployment is the remaining lane (MAJOR).

[COMPLETED]
- R12c — Auto-Close / Take-Profit exit watcher — PR #865 MERGED 2026-05-05 (MAJOR, SENTINEL APPROVED 95/100)
- R12d — Telegram Position UX (live monitor + force close) — PR #868 MERGED 4f5e12201964 (STANDARD)
- R12e — Auto-Redeem System — PR #869 MERGED 7f8af0b90993 (MAJOR, SENTINEL CONDITIONAL 64/100 — conditions resolved PR #879)
- R12f — Operator Dashboard + Kill Switch + Job Monitor — PR #874 MERGED 2026-05-05 (STANDARD)
- P3a — Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + migration 008) — PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)
- P3b — Copy Trade strategy (CopyTradeStrategy + scaler + wallet_watcher + migration 009 + /copytrade Telegram + registry bootstrap) — PR #877 MERGED 2026-05-06 a369129d (MAJOR, SENTINEL CONDITIONAL 71/100 resolved)
- R12 Live Readiness batch — Live Opt-In Checklist + Live→Paper Auto-Fallback + Daily P&L Summary — PR #883 MERGED 5a9cb22a (STANDARD, NARROW INTEGRATION)
- P3c — Signal Following strategy — PR #892 MERGED (5ee8487e), MAJOR, SENTINEL APPROVED 100/100
- P3d — Per-user signal scan loop + execution queue wiring — PR #897 MERGED (bb08092), MAJOR, SENTINEL APPROVED 94/100. Crash-recovery resume path, subscribe/unsubscribe enrollment, dual-layer dedup, migration 011+012. 464/464 tests green.
- Pre-flight cleanup — MERGED PR #899 (WARP/CRUSADERBOT-PREFLIGHT-CLEANUP, STANDARD, NARROW INTEGRATION): 15 F401 cleared, MIN-01/02/03 resolved, migration 013 copy_trade_events.copy_target_id FK ON DELETE CASCADE → ON DELETE SET NULL, ROADMAP R12d/R12e/R12f naming aligned.

[IN PROGRESS]
- None

[NOT STARTED]
- R12 — Deployment (Fly.io) final (MAJOR — P3d unblock complete, activation guards review required before live)

[NEXT PRIORITY]
- R12 final Fly.io deployment (MAJOR — last R12 lane). Activation sequence gated on EXECUTION_PATH_VALIDATED + CAPITAL_MODE_CONFIRMED + ENABLE_LIVE_TRADING — review required before any flag is set.

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-R12 cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) — follow-up
- lib/ F401 leakage (LOW, 5 occurrences across lib/strategies/logic_arb.py, lib/strategies/value_investor.py, lib/strategies/weather_arb.py, lib/strategy_base.py) — pre-existing repo-root ruff failure surfaced by Codex on PR #899; deferred to WARP/LIB-F401-CLEANUP (post-demo MINOR) per WARP🔹CMD scope-boundary hold; cross-project impact requires audit before cleanup

<!-- CD verify: 2026-05-08 00:30 -->
