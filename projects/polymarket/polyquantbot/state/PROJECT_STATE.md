Last Updated : 2026-04-30 15:25
Status       : WARP/capital-mode-confirm follow-up MERGED to main via PR #818 (merge SHA 5d314839). SENTINEL APPROVED 100/100, 0 critical, 3 advisory (non-blocking). LIVE INTEGRATION — check_with_receipt() strictly enforced at PaperBetaWorker + ClobExecutionAdapter; revoke 503 on persistence failure. 167/167 tests pass. WARP🔹CMD merge complete. EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / ENABLE_LIVE_TRADING all NOT SET. No live-trading-ready or production-capital-ready claim.

[COMPLETED]
- Priority 7 settlement lane fully closed: DDL PR #786, operator routes PR #787, Telegram wiring PR #789; 66/66 tests passing.
- P8-A capital readiness foundation merged to main via PR #790 (WARP/capital-readiness-p8a); 16/16 tests (CR-01..CR-12).
- P8-B capital risk controls hardening merged to main via PR #794 (WARP/capital-readiness-p8b); 12/12 tests (CR-13..CR-22). RISK_CONTROLS_VALIDATED ready.
- P8-C live execution readiness merged to main via PR #795 (WARP/capital-readiness-p8c); SENTINEL CONDITIONAL 78/100, 0 critical. FLAG-1 carried to P8-D.
- P8-D security + observability hardening merged to main via PR #800 (WARP/capital-readiness-p8d); SENTINEL APPROVED 97/100, 0 critical. FLAG-1 fixed. SECURITY_HARDENING_VALIDATED ready.
- Agent env file registration merged to main via PR #792 (WARP/register-agent-env-files).
- Sentinel timeout resilience merged to main via PR #797 (WARP/sentinel-timeout-resilience).
- Commander PR comment rule merged to main via PR #799 (WARP/commander-pr-comment-rule).
- PR notification workflow hardened via WARP/pr-notify-robust-ce09.
- P8-E capital validation sweep complete via WARP/capital-validation-p8e; dry-run PASS 4/4, 70/70 P8 tests passing, docs audit clean, boundary registry updated.
- WARP/real-clob-execution-path merged to main via PR #813 (merge SHA 6916a09e); SENTINEL APPROVED 98/100, 0 critical. 30/30 RCLOB + 70/70 P8 regressions passing. NARROW INTEGRATION only — adapter/mock/live market-data guard foundation.
- WARP/capital-mode-confirm chunk1 merged to main via PR #815 (merge SHA 6ea3b457); SENTINEL APPROVED 97/100, 0 critical. NARROW INTEGRATION only — DB layer + store + guard + API + Telegram scaffold.
- WARP/capital-mode-confirm follow-up merged to main via PR #818 (merge SHA 5d314839); SENTINEL APPROVED 100/100, 0 critical. LIVE INTEGRATION — check_with_receipt() strictly enforced at both production call sites. 167/167 tests pass. Priority 8 build complete. Awaiting WARP🔹CMD env-gate + operator confirmation to activate.

[IN PROGRESS]
- EXECUTION_PATH_VALIDATED NOT SET — env-gate decision required (WARP🔹CMD + Mr. Walker).
- CAPITAL_MODE_CONFIRMED NOT SET — pending env decision + operator-issued DB receipt via /capital_mode_confirm two-step.
- ENABLE_LIVE_TRADING NOT SET — guard remains off; no live-trading authority claimed.

[NOT STARTED]
- Final public product completion, launch assets, and handoff (Priority 9).

[NEXT PRIORITY]
- WARP🔹CMD: Priority 8 build complete. To activate: (1) set EXECUTION_PATH_VALIDATED + CAPITAL_MODE_CONFIRMED env vars in deployment, (2) operator issues /capital_mode_confirm two-step on Telegram → DB receipt persisted, (3) Priority 8 closeable, (4) scope Priority 9.

[KNOWN ISSUES]
- PaperBetaWorker.run_once() skips price_updater() entirely in live mode — market_data_provider injection path in price_updater() is never reached from worker loop (deferred fix; non-critical per SENTINEL F-1).
- handle_wallet_lifecycle_status() is not yet wired to a Telegram command -- function exists and is tested but routing is deferred.
- Wallet lifecycle live PostgreSQL validation is deferred to pre-public sweep.
- Portfolio routes hardcode tenant_id=system and user_id=paper_user -- per-user route binding deferred to full multi-user rollout.
- Portfolio unrealized PnL relies on current_price in paper_positions -- live mark-to-market deferred to market data integration lane.
- WalletCandidate financial fields (balance_usd, exposure_pct, drawdown_pct) default to 0.0 -- risk gate thresholds will not trigger in orchestration routing until market data integration is complete.
- No migration runner configured -- 001_settlement_tables.sql and 002_capital_mode_confirmations.sql must be applied manually or via operator tooling; auto-create in _apply_schema() remains the runtime path.
- OperatorConsole.apply_admin_intervention() does not persist intervention record to DB -- audit log emitted via structlog (operator_admin_intervention_audit) on every intervention; DB persistence deferred to P9 storage lane.
- get_failed_batches() always returns [] -- batch results not persisted in current settlement persistence layer; /failed_batches Telegram reply acknowledges this explicitly.
- Capital-mode pending-token store is in-process (_PENDING_CAPITAL_CONFIRMS in server/api/public_beta_routes.py). Multi-replica deployments will require Redis-backed swap before horizontal scale; current single-machine Fly runtime is acceptable.
- ClobExecutionAdapter mode='mocked' label not enforced against client type — pre-existing risk (SENTINEL F-1, PR #813). Deferred to P9 hardening.
- P8C asyncio.get_event_loop().run_until_complete deprecated pattern breaks test isolation when run after P8E — pre-existing fragility (SENTINEL F-2). Deferred.
