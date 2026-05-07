Last Updated : 2026-05-07 20:58 Asia/Jakarta
Status       : P3c Signal Following strategy MERGED PR #892 (5ee8487e), SENTINEL APPROVED 100/100, 428/428 tests green. PR #895 fix(risk gate): signal_following allow-listed in STRATEGY_AVAILABILITY (MINOR, FOUNDATION, d25f4fda). P3d — Per-user signal scan loop + execution queue wiring — is the next active MAJOR lane. R12 final Fly.io deployment blocked on P3d + activation guard review. Activation guards NOT SET.

[COMPLETED]
- R12c — Auto-Close / Take-Profit exit watcher — PR #865 MERGED 2026-05-05 (MAJOR, SENTINEL APPROVED 95/100)
- R12d — Telegram Position UX (live monitor + force close) — PR #868 MERGED 4f5e12201964 (STANDARD)
- R12e — Auto-Redeem System — PR #869 MERGED 7f8af0b90993 (MAJOR, SENTINEL CONDITIONAL 64/100 — conditions resolved PR #879)
- R12f — Operator Dashboard + Kill Switch + Job Monitor — PR #874 MERGED 2026-05-05 (STANDARD)
- P3a — Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + migration 008) — PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)
- P3b — Copy Trade strategy (CopyTradeStrategy + scaler + wallet_watcher + migration 009 + /copytrade Telegram + registry bootstrap) — PR #877 MERGED 2026-05-06 a369129d (MAJOR, SENTINEL CONDITIONAL 71/100 resolved)
- R12 Live Readiness batch — Live Opt-In Checklist + Live→Paper Auto-Fallback + Daily P&L Summary — PR #883 MERGED 5a9cb22a (STANDARD, NARROW INTEGRATION)
- Cleanup legacy polyquantbot directory — PR #891 MERGED (MINOR, Issue #890 closed)
- P3c — Signal Following strategy — PR #892 MERGED (5ee8487e), MAJOR, SENTINEL APPROVED 100/100
- PR #895 — fix(risk gate): signal_following allow-listed in STRATEGY_AVAILABILITY — MERGED d25f4fda (MINOR, FOUNDATION)

[IN PROGRESS]
- P3d — Per-user signal scan loop + execution queue wiring (MAJOR — not started, dispatching next)

[NOT STARTED]
- R12 — Deployment (Fly.io) final (MAJOR — blocked on P3d complete + activation guards reviewed)

[NEXT PRIORITY]
- Dispatch P3d — Per-user signal scan loop + execution queue wiring (MAJOR — wires registry into risk gate)
- After P3d: live activation sequence gated on EXECUTION_PATH_VALIDATED + CAPITAL_MODE_CONFIRMED + ENABLE_LIVE_TRADING
- After P3d: R12 final Fly.io deployment (MAJOR — last R12 lane, blocked on P3d + activation guards)

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-R12 cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) — follow-up
- F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py (ruff cleanup lane, LOW)
- MIN-01 P3b: user_id type annotations missing in 3 copy_trade handler helpers (deferred follow-up)
- MIN-02 P3b: phase comment in dispatcher.py (deferred follow-up)
- MIN-03 P3b: copy_trade_events.copy_target_id nullable FK (deferred follow-up)
- ROADMAP R12d/R12e/R12f lane IDs use original planned names (Live Opt-In Checklist / Live→Paper Fallback / Daily P&L); PROJECT_STATE + WORKTODO use actual executed names (Telegram Position UX / Auto-Redeem / Operator Dashboard) — deferred ROADMAP restructure, WARP🔹CMD decision required

<!-- CD verify: 2026-05-07 20:58 -->
