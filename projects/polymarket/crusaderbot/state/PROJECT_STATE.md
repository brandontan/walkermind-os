Last Updated : 2026-05-08 00:30 Asia/Jakarta
Status       : P3d MERGED (PR #897, bb08092). 464/464 tests green. Strategy plane complete. Awaiting R12 final Fly.io deployment.

[COMPLETED]
- PR #852 — feat(crusaderbot): import full Replit build R1-R11
- PR #853 — sentinel: crusaderbot-replit-import PASS (post-fix)
- C1 resolved: KELLY_FRACTION applied, capital_alloc_pct capped <1.0
- C2 resolved: migrations/004 idempotent DO $$ blocks
- C3 resolved: Tier 3 promotion gated on MIN_DEPOSIT_USDC
- R12b — Fly.io health probes + operator alerts + JSON logging (PR #856 merged)
- PR #857 — chore: state sync post-PR #856
- PR #858 — chore: state sync post-PR #857
- PR #860 — chore: ROADMAP R12b drift fix + WORKTODO init (STANDARD, merged)
- R12a — CI/CD Pipeline GitHub Actions + Fly.io — PR #855 MERGED 2026-05-04 (STANDARD)
- R12c — Auto-Close / Take-Profit exit watcher — PR #865 MERGED 2026-05-05 (MAJOR, SENTINEL APPROVED 95/100)
- R12d — Telegram Position UX (live monitor + force close) — PR #868 MERGED 4f5e12201964 (STANDARD)
- R12e — Auto-Redeem System — PR #869 MERGED 7f8af0b90993 (MAJOR, SENTINEL CONDITIONAL 64/100 — conditions resolved PR #879)
- R12f — Operator Dashboard + Kill Switch + Job Monitor — PR #874 MERGED 2026-05-05 (STANDARD)
- P3a — Strategy Registry Foundation (BaseStrategy ABC + StrategyRegistry + migration 008) — PR #876 MERGED 2026-05-05 (STANDARD, FOUNDATION)
- P3b — Copy Trade strategy (CopyTradeStrategy + scaler + wallet_watcher + migration 009 + /copytrade Telegram + registry bootstrap) — PR #877 MERGED 2026-05-06 a369129d (MAJOR, SENTINEL CONDITIONAL 71/100 resolved)
- R12 Live Readiness batch — Live Opt-In Checklist + Live→Paper Auto-Fallback + Daily P&L Summary — PR #883 MERGED 5a9cb22a (STANDARD, NARROW INTEGRATION)
- Cleanup legacy polyquantbot directory — PR #891 MERGED (MINOR, Issue #890 closed)
- P3c — Signal Following strategy — PR #892 MERGED (5ee8487e), MAJOR, SENTINEL APPROVED 100/100
- P3d — Per-user signal scan loop + execution queue wiring — PR #897 MERGED (bb08092), MAJOR, SENTINEL APPROVED 94/100. Crash-recovery resume path, subscribe/unsubscribe enrollment, dual-layer dedup, migration 011+012. 464/464 tests green.

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
- F401 unused imports: bot/dispatcher.py, bot/handlers/dashboard.py, cache.py, config.py, domain/risk/gate.py, scheduler.py, services/signal_scan/signal_scan_job.py (ruff cleanup lane, LOW)
- MIN-01 P3b: user_id type annotations missing in 3 copy_trade handler helpers (deferred follow-up)
- MIN-02 P3b: phase comment in dispatcher.py (deferred follow-up)
- MIN-03 P3b: copy_trade_events.copy_target_id nullable FK (deferred follow-up)
- ROADMAP R12d/R12e/R12f lane IDs use original planned names (Live Opt-In Checklist / Live→Paper Fallback / Daily P&L); PROJECT_STATE + WORKTODO use actual executed names (Telegram Position UX / Auto-Redeem / Operator Dashboard) — deferred ROADMAP restructure, WARP🔹CMD decision required

<!-- CD verify: 2026-05-08 00:30 -->
