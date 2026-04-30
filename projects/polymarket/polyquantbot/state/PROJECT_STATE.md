Last Updated : 2026-04-30 21:30
Status       : Priority 8 BUILD COMPLETE (PR #813 + #815 + #818 all merged; SENTINEL APPROVED 98/97/100). Pre-work sync merged via PR #821 (WARP/worktodo-priority8-sync). Priority 9 lane execution active: Lane 4 (WARP/p9-repo-hygiene-final) in progress — archive sweep moved 456 stale reports (>7 days) under reports/archive/forge|sentinel/, ROADMAP P9 lane list added, WORKTODO P1–P7 hygiene swept (deferred items intentionally kept open — onboarding/persistence-test/per-wallet-exposure/docs-sync still tracked correctly). EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / ENABLE_LIVE_TRADING all NOT SET. No live-trading-ready or production-capital-ready claim.

[COMPLETED]
- P8-A capital readiness foundation merged to main via PR #790 (WARP/capital-readiness-p8a); 16/16 tests (CR-01..CR-12).
- P8-B capital risk controls hardening merged to main via PR #794 (WARP/capital-readiness-p8b); 12/12 tests (CR-13..CR-22). RISK_CONTROLS_VALIDATED ready.
- P8-C live execution readiness merged to main via PR #795 (WARP/capital-readiness-p8c); SENTINEL CONDITIONAL 78/100, 0 critical. FLAG-1 carried to P8-D.
- P8-D security + observability hardening merged to main via PR #800 (WARP/capital-readiness-p8d); SENTINEL APPROVED 97/100, 0 critical. FLAG-1 fixed. SECURITY_HARDENING_VALIDATED ready.
- P8-E capital validation sweep complete via WARP/capital-validation-p8e; dry-run PASS 4/4, 70/70 P8 tests passing, docs audit clean, boundary registry updated.
- WARP/real-clob-execution-path merged to main via PR #813 (merge SHA 6916a09e); SENTINEL APPROVED 98/100, 0 critical. 30/30 RCLOB + 70/70 P8 regressions passing. NARROW INTEGRATION only — adapter/mock/live market-data guard foundation.
- WARP/capital-mode-confirm chunk1 merged to main via PR #815 (merge SHA 6ea3b457); SENTINEL APPROVED 97/100, 0 critical. NARROW INTEGRATION only — DB layer + store + guard + API + Telegram scaffold.
- WARP/capital-mode-confirm follow-up merged to main via PR #818 (merge SHA 5d314839); SENTINEL APPROVED 100/100, 0 critical. LIVE INTEGRATION — check_with_receipt() strictly enforced at both production call sites. 167/167 tests pass. Priority 8 build complete. Awaiting WARP🔹CMD env-gate + operator confirmation to activate.
- WARP/worktodo-priority8-sync merged to main via PR #821 (Tier MINOR); pre-Priority-9 state truth sync — WORKTODO P8 SENTINEL closure + Right Now / Simple Execution Order alignment + Priority 9 plan reference added to PROJECT_STATE NEXT PRIORITY.

[IN PROGRESS]
- EXECUTION_PATH_VALIDATED NOT SET — env-gate decision required (WARP🔹CMD + Mr. Walker).
- CAPITAL_MODE_CONFIRMED NOT SET — pending env decision + operator-issued DB receipt via /capital_mode_confirm two-step.
- ENABLE_LIVE_TRADING NOT SET — guard remains off; no live-trading authority claimed.

[NOT STARTED]
- Priority 9 Lane 1 (WARP/p9-public-product-docs) — README + docs sync + launch summary + onboarding/support docs.
- Priority 9 Lane 2 (WARP/p9-ops-handoff) — deployment guide + secrets/env guide.
- Priority 9 Lane 3 (WARP/p9-monitoring-admin-surfaces) — admin index + operator checklist + release dashboard.
- Priority 9 Lane 5 (WARP/p9-final-acceptance) — acceptance ceremony; gated on P8 activation + Lanes 1–4 merged.

[NEXT PRIORITY]
- WARP🔹CMD: Priority 8 build complete. To activate: (1) set EXECUTION_PATH_VALIDATED + CAPITAL_MODE_CONFIRMED env vars in deployment, (2) operator issues /capital_mode_confirm two-step on Telegram → DB receipt persisted, (3) Priority 8 closeable.
- WARP🔹CMD: Lane 4 (WARP/p9-repo-hygiene-final) merge gate. After merge, scope Lanes 1+2 in parallel (zero file overlap), then Lane 3, then Lane 5 (gated).

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
