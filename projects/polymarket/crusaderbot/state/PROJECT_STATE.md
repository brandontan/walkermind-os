Last Updated : 2026-05-06 03:11 Asia/Jakarta
Status       : Migration path fix MERGED (PR #881 — 538fd999). 008_strategy_tables.sql now in migrations/ — runner applies at startup. Next: P3c Signal Following strategy. Paper-default. EXECUTION_PATH_VALIDATED NOT SET.

[COMPLETED]
- R12a — CI/CD Pipeline GitHub Actions + Fly.io — PR #855 MERGED 2026-05-04 (STANDARD)
- R12c — Auto-Close / Take-Profit exit watcher — PR #865 MERGED 2026-05-05 (MAJOR, SENTINEL APPROVED 95/100)
- R12d — Telegram Position UX (live monitor + force close) — PR #868 MERGED 4f5e12201964 (STANDARD)
- R12e — Auto-Redeem System — PR #869 MERGED 7f8af0b90993 (MAJOR, SENTINEL CONDITIONAL 64/100 — conditions resolved PR #879)
- R12f — Operator Dashboard + Kill Switch + Job Monitor — PR #874 MERGED 2026-05-05 (STANDARD)
- P3a — Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + migration 008) — PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)
- P3b — Copy Trade strategy (CopyTradeStrategy + scaler + wallet_watcher + migration 009 + /copytrade Telegram + registry bootstrap) — PR #877 MERGED 2026-05-06 a369129d (MAJOR, SENTINEL CONDITIONAL 71/100 resolved)
- PR #881 — fix(crusaderbot): move 008_strategy_tables.sql infra/migrations/ -> migrations/ (MINOR, FILE MOVE ONLY, 538fd999)

[IN PROGRESS]
- None

[NOT STARTED]
- R12d — Live Opt-In Checklist (MAJOR — hard gate before EXE)
- R12e — Live → Paper Auto-Fallback (MAJOR)
- R12f — Daily P&L Summary (STANDARD)
- R12 — Deployment (Fly.io) final (MAJOR — blocked on all R12 lanes + P3 complete)
- P3c — Signal Following strategy (MAJOR)
- P3d — Per-user signal scan loop + execution queue wiring (MAJOR)

[NEXT PRIORITY]
- P3c — Signal Following strategy (second BaseStrategy consumer). Branch: WARP/CRUSADERBOT-P3C-*
- After P3c + P3d: live activation sequence gated on EXECUTION_PATH_VALIDATED + CAPITAL_MODE_CONFIRMED + ENABLE_LIVE_TRADING

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-R12 cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) — follow-up
- F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py (ruff cleanup lane, LOW)
- MIN-01 P3b: user_id type annotations missing in 3 copy_trade handler helpers (deferred follow-up)
- MIN-02 P3b: phase comment in dispatcher.py (deferred follow-up)
- MIN-03 P3b: copy_trade_events.copy_target_id nullable FK (deferred follow-up)
