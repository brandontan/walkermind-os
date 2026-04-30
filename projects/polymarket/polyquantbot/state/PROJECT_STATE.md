Last Updated : 2026-04-30 16:10
Status       : WARP/real-clob-execution-path merged via PR #813 (SHA 6916a09e). WARP/capital-mode-confirm chunk1 (DB+store+guard+API+Telegram) merged via PR #815 (SHA 6ea3b457, SENTINEL APPROVED 97/100). WARP/capital-mode-confirm follow-up (this PR #818) extends to LIVE INTEGRATION: strict check_with_receipt() at runtime call sites in PaperBetaWorker + ClobExecutionAdapter, revoke 503 on persistence failure. 21/21 P8-E + 30/30 RCLOB + 100/100 prior P8 + 46/46 settlement+telegram regression. Awaiting WARP•SENTINEL MAJOR. EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / ENABLE_LIVE_TRADING all NOT SET. No live-trading-ready or production-capital-ready claim.

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
- WARP/capital-mode-confirm chunk1 merged to main via PR #815 (merge SHA 6ea3b457); SENTINEL APPROVED 97/100, 0 critical. NARROW INTEGRATION only — DB layer + store + guard + API + Telegram scaffold. check_with_receipt() defined but not wired into runtime live call sites (deferred to follow-up lane).
- WARP/capital-mode-confirm follow-up (this lane, PR #818): LIVE INTEGRATION — strict check_with_receipt() enforcement at PaperBetaWorker.run_once() and ClobExecutionAdapter.submit_order(); ClobExecutionAdapter mode='live' fail-fast at construction without confirmation_store; revoke persistence failure now distinguished via CapitalModeRevokeFailedError → 503 (instead of misreporting no_active). 21/21 P8-E (P8E-01..P8E-21) + 30/30 RCLOB + 100/100 prior P8 + 21/21 settlement + 25/25 telegram regression.

[IN PROGRESS]
- WARP/capital-mode-confirm follow-up (PR #818): WARP•FORGE complete after Codex P1 fix; awaiting WARP•SENTINEL MAJOR validation. Source: projects/polymarket/polyquantbot/reports/forge/capital-mode-confirm.md.
- EXECUTION_PATH_VALIDATED NOT SET — SENTINEL approved real CLOB foundation; WARP🔹CMD env-gate decision required.
- CAPITAL_MODE_CONFIRMED NOT SET — pending capital-mode-confirm follow-up SENTINEL + WARP🔹CMD env decision + operator-issued DB receipt via /capital_mode_confirm.
- ENABLE_LIVE_TRADING NOT SET — guard remains off; no live-trading authority claimed.

[NOT STARTED]
- Final public product completion, launch assets, and handoff (Priority 9).

[NEXT PRIORITY]
- WARP•SENTINEL: validate WARP/capital-mode-confirm follow-up (Tier MAJOR, PR #818). Source: projects/polymarket/polyquantbot/reports/forge/capital-mode-confirm.md. After SENTINEL verdict, return to WARP🔹CMD for: (1) merge PR #818, (2) set EXECUTION_PATH_VALIDATED + CAPITAL_MODE_CONFIRMED env vars in deployment, (3) operator issues /capital_mode_confirm two-step on operator Telegram, (4) Priority 8 closeable, (5) scope Priority 9.

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

