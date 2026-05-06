Last Updated : 2026-05-06 08:16 Asia/Jakarta
Status       : R12 post-merge state sync MERGED PR #887. All R12 lanes complete. P3c next. Activation guards NOT SET.

[COMPLETED]
- R12a — CI/CD Pipeline GitHub Actions + Fly.io — PR #855 MERGED 2026-05-04 (STANDARD)
- R12b — Fly.io health probes + operator alerts + JSON logging — PR #856 MERGED (STANDARD)
- R12c — Auto-Close / Take-Profit exit watcher — PR #865 MERGED 2026-05-05 (MAJOR, SENTINEL APPROVED 95/100)
- R12d — Telegram Position UX (live monitor + force close) — PR #868 MERGED (STANDARD)
- R12e — Auto-Redeem System — PR #869 MERGED (MAJOR, SENTINEL CONDITIONAL 64/100 — conditions resolved PR #879)
- R12f — Operator Dashboard + Kill Switch + Job Monitor — PR #874 MERGED 2026-05-05 (STANDARD)
- P3a — Strategy Registry Foundation — PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)
- P3b — Copy Trade strategy — PR #877 MERGED 2026-05-06 a369129d (MAJOR, SENTINEL CONDITIONAL 71/100 resolved)
- R12 Live Readiness batch — Live Opt-In Checklist + Live→Paper Auto-Fallback + Daily P&L Summary — PR #883 MERGED 5a9cb22a (STANDARD, NARROW INTEGRATION)
- PR #887 — chore: R12 post-merge state sync (WARP/CRUSADERBOT-R12-POST-MERGE-SYNC, MINOR) — MERGED 2026-05-06

[IN PROGRESS]
- None

[NOT STARTED]
- R12 — Deployment (Fly.io) final (MAJOR — blocked on P3c/P3d complete)
- P3c — Signal Following strategy (MAJOR)
- P3d — Per-user signal scan loop + execution queue wiring (MAJOR)

[NEXT PRIORITY]
- P3c — Signal Following strategy (MAJOR). Next lane. Branch: WARP/CRUSADERBOT-P3C-*
- After P3c + P3d: live activation sequence gated on EXECUTION_PATH_VALIDATED + CAPITAL_MODE_CONFIRMED + ENABLE_LIVE_TRADING
- After P3c + P3d: R12 final Fly.io deployment (MAJOR — last R12 lane, blocked on P3c/P3d + activation guards)

[KNOWN ISSUES]
- /deposit no tier gate (intentional, non-blocking)
- services/* dead code (LOW, post-R12 cleanup)
- check_alchemy_ws is TCP-only (no full WS handshake) — follow-up
- F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py (ruff cleanup lane, LOW)
- MIN-01 P3b: user_id type annotations missing in 3 copy_trade handler helpers (deferred follow-up)
- MIN-02 P3b: phase comment in dispatcher.py (deferred follow-up)
- MIN-03 P3b: copy_trade_events.copy_target_id nullable FK (deferred follow-up)
- ROADMAP R12d/R12e/R12f lane IDs use original planned names (Live Opt-In Checklist / Live→Paper Fallback / Daily P&L); PROJECT_STATE + WORKTODO use actual executed names (Telegram Position UX / Auto-Redeem / Operator Dashboard) — deferred ROADMAP restructure, WARP🔹CMD decision required
