Last Updated : 2026-04-29 19:00
Status       : P8-A through P8-D all merged to main. register-agent-env-files, sentinel-timeout-resilience, commander-pr-comment-rule all merged. P8 core build complete. PR notification workflow hardened (pr-notify-robust). Next: P8-E capital validation + claim review.

[COMPLETED]
- Priority 1 Telegram live baseline truth-sync lane is closed with recorded live command evidence under projects/polymarket/polyquantbot/reports/forge/.
- Ops handoff pack lane is completed with operator runbook, Fly runtime troubleshooting, Telegram runtime troubleshooting, Sentry quick-check, and reusable runtime evidence checklist under projects/polymarket/polyquantbot/docs/.
- Phase 10.8 logging/monitoring hardening is closed as merged-main truth via PR #734, PR #736, and PR #737.
- Phase 10.9 security baseline hardening is closed with final SENTINEL APPROVED gate for PR #742 at projects/polymarket/polyquantbot/reports/sentinel/phase10-9_01_pr742-security-baseline-hardening-validation.md.
- Priority 3 paper trading product completion is merged to main via PR #770; compact SENTINEL gate record APPROVED 95/100 with zero critical issues.
- Priority 4 wallet lifecycle foundation is merged to main via PR #772; COMMANDER degen structure review accepted and full SENTINEL is deferred to pre-public sweep.
- Priority 5 portfolio management logic is merged to main via PR #774; 29/29 tests passing (PM-01..PM-28 + PM-13b).
- Priority 6 Phase A and Phase B multi-wallet orchestration are merged to main via PR #776 and PR #779.
- Priority 7 settlement-retry-reconciliation is merged to main via PR #777; 66/66 tests passing (ST-01..ST-38c).
- Gate 1a DDL migration file for settlement tables is merged to main via PR #786 from WARP/settlement-ddl-migration.
- Gate 1b FastAPI settlement operator routes merged to main via PR #787 from WARP/settlement-operator-routes; 9/9 tests (ST-39..ST-47).
- Gate 1c Telegram settlement wiring merged to main via PR #789 from WARP/settlement-telegram-wiring; 8/8 tests (ST-48..ST-55). Priority 7 settlement lane fully closed.
- P8-A capital readiness foundation merged to main via PR #790 (WARP/capital-readiness-p8a); 16/16 tests (CR-01..CR-12).
- P8-B capital risk controls hardening merged to main via PR #794 (WARP/capital-readiness-p8b); 12/12 tests (CR-13..CR-22).
- P8-C live execution readiness merged to main via PR #795 (WARP/capital-readiness-p8c); SENTINEL CONDITIONAL 78/100, 0 critical.
- P8-D security + observability hardening merged to main via PR #800 (WARP/capital-readiness-p8d); SENTINEL APPROVED 97/100, 0 critical. FLAG-1 fix, /capital_status, audit log, alerts validated.
- Agent env file registration merged to main via PR #792 (WARP/register-agent-env-files); CURSOR.md and ONA.md registered in AGENTS.md and CLAUDE.md.
- Sentinel timeout resilience merged to main via PR #797 (WARP/sentinel-timeout-resilience); timeout handling and chunking recovery rules updated in AGENTS.md and CLAUDE.md.
- Commander PR comment rule merged to main via PR #799 (WARP/commander-pr-comment-rule); PR COMMENT AUTO-POST RULE added to COMMANDER.md.
- PR notification workflow hardened via WARP/pr-notify-robust-ce09; retry+backoff, all 7 PR events, Slack fallback, enriched payload, PR comment on open.

[IN PROGRESS]
- P8-E capital validation + claim review (§54) in progress -- dry-run, staged rollout, docs review, final sign-off required; sets CAPITAL_MODE_CONFIRMED.
- Structure build continues under forge-merge mode; do not claim public-ready, live-trading-ready, or production-capital-ready until P8-E capital validation sweep is complete.

[NOT STARTED]
- Final public product completion, launch assets, and handoff (Priority 9).

[NEXT PRIORITY]
- P8-E capital validation + claim review (§54): WARP•FORGE task required -- dry-run, staged rollout, docs review, claim cleanup, final sign-off; sets CAPITAL_MODE_CONFIRMED.

[KNOWN ISSUES]
- PaperBetaWorker.price_updater() raises LiveExecutionBlockedError in live mode (P8-C hardened) -- real market data integration still deferred; unrealized PnL will not update in live mode until implemented.
- handle_wallet_lifecycle_status() is not yet wired to a Telegram command -- function exists and is tested but routing is deferred.
- Wallet lifecycle live PostgreSQL validation is deferred to pre-public sweep.
- Portfolio routes hardcode tenant_id=system and user_id=paper_user -- per-user route binding deferred to full multi-user rollout.
- Portfolio unrealized PnL relies on current_price in paper_positions -- live mark-to-market deferred to market data integration lane.
- WalletCandidate financial fields (balance_usd, exposure_pct, drawdown_pct) default to 0.0 -- risk gate thresholds will not trigger in orchestration routing until market data integration is complete.
- No migration runner configured -- 001_settlement_tables.sql must be applied manually or via operator tooling; auto-create in _apply_schema() remains the runtime path.
- OperatorConsole.apply_admin_intervention() does not persist intervention record to DB -- audit log emitted via structlog (operator_admin_intervention_audit) on every intervention; DB persistence deferred to P9 storage lane.
- get_failed_batches() always returns [] -- batch results not persisted in current settlement persistence layer; /failed_batches Telegram reply acknowledges this explicitly.
