Last Updated : 2026-04-29 07:24
Status       : P8-B capital risk controls hardening built -- CapitalRiskGate (config-driven limits, 5-gate LIVE guard) + WalletFinancialProvider wiring + OrchestratorService enrichment hook; 12/12 tests (CR-13..CR-22), 35/35 total (P8-A+B); WARP•SENTINEL MAJOR validation required before merge. sentinel-timeout-resilience rule patch built, WARP🔹CMD review pending.

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

[IN PROGRESS]
- COMMANDER review for PR #781 (Priority 6 Phase C) pending merge decision.
- P8-A capital readiness foundation (WARP/capital-readiness-p8a) -- CapitalModeConfig + BoundaryRegistry + 16/16 tests (CR-01..CR-12); WARP•SENTINEL MAJOR validation required. Report: projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8a.md.
- P8-B capital risk controls hardening -- CapitalRiskGate (config-driven limits, 5-gate LIVE guard) + WalletFinancialProvider protocol + OrchestratorService enrichment hook; 12/12 tests (CR-13..CR-22). WARP•SENTINEL MAJOR validation required. Report: projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8b.md.
- WalkerMind OS identity rebranding (NWAP/rebranding-identity-fix) -- WARP CMD review pending. PR #782 held due to drift; replaced by this fix PR.
- Legacy string cleanup (WARP/cleanup-legacy-refs) -- WARP/cleanup-legacy-refs branch opened, forge report at projects/polymarket/polyquantbot/reports/forge/cleanup-legacy-refs.md; WARP CMD review pending.
- Structure build continues under forge-merge mode; do not claim public-ready, live-trading-ready, or production-capital-ready until Priority 8 SENTINEL MAJOR sweep is complete.
- Agent env file registration (WARP/register-agent-env-files) -- CURSOR.md and ONA.md registered in AGENTS.md and CLAUDE.md; WARP🔹CMD review pending. Report: projects/polymarket/polyquantbot/reports/forge/register-agent-env-files.md.
- sentinel-timeout-resilience rule patch (WARP/sentinel-timeout-resilience) -- 4 surgical edits to CLAUDE.md and AGENTS.md; WARP🔹CMD review pending. Report: projects/polymarket/polyquantbot/reports/forge/sentinel-timeout-resilience.md.

[NOT STARTED]
- P8-C live execution readiness audit (§52) -- validate live CLOB path, replace price_updater stub, wire allow_real_settlement; clears EXECUTION_PATH_VALIDATED gate.
- P8-D security + observability hardening (§53) -- per-user isolation, admin audit log, production alerting; clears SECURITY_HARDENING_VALIDATED gate.
- P8-E capital validation + claim review (§54) -- dry-run, staged rollout, docs review, final sign-off; sets CAPITAL_MODE_CONFIRMED.
- Final public product completion, launch assets, and handoff (Priority 9).

[NEXT PRIORITY]
- WARP•SENTINEL MAJOR validation required for P8-B. Source: projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8b.md. Tier: MAJOR. Branch: WARP/capital-readiness-p8b.
- WARP•SENTINEL MAJOR validation required for P8-A. Source: projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8a.md. Tier: MAJOR. Branch: WARP/capital-readiness-p8a.
- WARP🔹CMD review required for register-agent-env-files. Source: projects/polymarket/polyquantbot/reports/forge/register-agent-env-files.md. Tier: MINOR.
- WARP🔹CMD review required for sentinel-timeout-resilience. Source: projects/polymarket/polyquantbot/reports/forge/sentinel-timeout-resilience.md. Tier: MINOR.

[KNOWN ISSUES]
- PaperBetaWorker.price_updater() is a no-op stub -- unrealized PnL updates require real market price polling (deferred to post-Priority-3 market data integration lane).
- handle_wallet_lifecycle_status() is not yet wired to a Telegram command -- function exists and is tested but routing is deferred.
- Wallet lifecycle live PostgreSQL validation is deferred to pre-public sweep.
- Portfolio routes hardcode tenant_id=system and user_id=paper_user -- per-user route binding deferred to full multi-user rollout.
- Portfolio unrealized PnL relies on current_price in paper_positions -- live mark-to-market deferred to market data integration lane.
- WalletCandidate financial fields (balance_usd, exposure_pct, drawdown_pct) default to 0.0 -- risk gate thresholds will not trigger in orchestration routing until market data integration is complete.
- No migration runner configured -- 001_settlement_tables.sql must be applied manually or via operator tooling; auto-create in _apply_schema() remains the runtime path.
- OperatorConsole.apply_admin_intervention() does not persist intervention record -- service layer callers must handle explicitly; Telegram /settlement_intervene reply surfaces this note.
- get_failed_batches() always returns [] -- batch results not persisted in current settlement persistence layer; /failed_batches Telegram reply acknowledges this explicitly.
