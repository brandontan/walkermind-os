Last Updated : 2026-06-05 15:30
Status       : WARP-76 PAPER-public hardening (M1 gate) COMPLETE — ALL 4 CHUNKS MERGED: H1 #1622, H2 #1623, H3 #1624, H4 #1625. H4 audit: 140 PASS / 20 N/A-operator / 1 FAIL fixed (/signals/recent signal_publications leak → scoped to user_signal_subscriptions). WARP-72 Phase 2 scorer PARKED (SCORER_ACTIVE=False); WARP-74 live reconciliation MERGED #1613; WARP-75 consent hardening PR #1617 open.

[COMPLETED]
- WARP-76 H4 multi-user isolation audit MERGED #1625 (WARP/isolation-audit) — 161 queries on positions/orders/wallets/user_settings/signal_publications/ledger audited: 140 PASS, 20 N/A-operator (admin-gated), 1 FAIL FIXED: /signals/recent returned all feeds' signals to every user → scoped to caller's active user_signal_subscriptions (mirrors signal_evaluator read contract); cross-user leakage test + SQL-contract test; report: reports/forge/isolation-audit.md
- WARP-76 H3 feed-loss fail-safe MERGED #1624 (WARP/feed-loss-failsafe) — ORACLE_FEED_TIMEOUT_SEC=120; oracle.is_feed_down; run_once + run_close_sweep_fast halt + page on feed loss, auto-resume + page on recovery; STANDARD; report: reports/forge/feed-loss-failsafe.md
- WARP-76 H2 monitoring/alerting MERGED #1623 (WARP/monitoring-alerting) — operator daily-P&L summary + structured user_id/market_id/rule trade logs; 3/4 alerts already wired by WARP-74; report: reports/forge/monitoring-alerting.md
- WARP-76 H1 auth/bcrypt CI test fix MERGED #1622 (WARP/auth-test-fix) — 5 suites degrade to documented SKIP in dep-less envs; report: reports/forge/auth-test-fix.md
- WARP-69 per-user autonomous loop hardening audit MERGED #1615 (eebca68) — auto_trade_on canonical opt-in, no parallel gate; no capital-path defect; 12 hermetic tests, zero prod change; report: reports/forge/auto-trade-per-user-hardening.md
- WARP-74 live reconciliation epic MERGED #1613 (c5f0ed1) — generalized live reconciler + kill-switch broker cancel_all + mig 082 applied to Supabase prod; SENTINEL APPROVED 97/100 0 critical
- WARP-74 Chunk A MERGED #1612 (4b742f2) — live-order orphan+drift detection/telemetry, no capital action; SENTINEL APPROVED 95/100 0 critical
- WARP-72 factor dataset persistence MERGED #1609 (e497b57) — mig 081, durable factor_vectors table + per-candle UPSERT + settlement backfill
- WARP-72 Phase 1 factor signals MERGED #1608 (8277937) — momentum signals + labeled vector emit, SHADOW-only, CI green; SENTINEL APPROVED
- WARP-57 SENTINEL re-audit APPROVED 86/100 0 critical (PR #1261 SHA aa4fe24c) — copy_targets schema mismatch resolved; MEDIUM-4 copy scanner swap deferred
- WARP-55 MERGED (abd3b43dbe10) — RUNTIME_EVIDENCE.md 7/7 P2 finish criteria proven; CrusaderBot closed beta DONE
- WARP/ROOT/oracle-rtds-frame-fix MERGED — live RTDS frame confirmed (crypto_prices_chainlink), SOL asset-aware band fix; MAJOR; report: reports/forge/oracle-rtds-frame-fix.md
- WARP/ROOT/oracle-price-to-beat-buffer MERGED — buffer-at-open price_to_beat, live e2e BTC/ETH/SOL all oracle_edge_status=computed; report: reports/forge/oracle-price-to-beat-buffer.md
- WARP/sentinel-candle-oracle SENTINEL APPROVED 96/100 0 critical — full oracle epic Chunks 1-3 validated at a92fec2; report: reports/sentinel/candle-oracle.md
[IN PROGRESS]
- WARP-75 (WARP/ROOT/auto-trade-consent-hardening) PR #1617 open — F1 onboarding no longer side-effect-enables auto_trade_on (explicit opt-in only); F3 run_once warns instead of silent-skip (unmapped preset + opted-in-unenrolled); 16 tests; STANDARD; report: reports/forge/auto-trade-consent-hardening.md
- WARP-74 Lane 2 staging proof harness BUILT (WARP/live-staging-proof) — tests/staging/test_live_reconcile_staging.py covers all 5 acceptance cases (kill cancel-all / unknown-order adopt-page-halt / closing rollback-page-finalize / drift broker+db-only / infra-degraded paper fallback) against a REAL broker on an isolated wallet; DB side is a recording fake (never writes prod); STAGING_WALLET_KEY-guarded (9 skipped/0-fail without wallet); operator runbook docs/runbooks/warp74-staging-proof.md; build-only pending operator wallet provision; report: reports/forge/live-staging-proof.md
- WARP-72 Phase 2 scorer MERGED #1618 (e9ac72d) — StrategyScorer + scorer_trainer + scorer_ab, SHADOW-only; ADDITIVE Oracle deny-gate; SCORER_ACTIVE=False; 18 tests; report: reports/forge/smart-strike-scorer.md
- WARP-72 weights derivation (claude/scorer-weights-derived) PR open — real BTC/5m+ETH/5m weights from live factor_vectors replace the stub; A/B holdout +0.315 win-rate (scorer>router); caveat: favorite/underdog asymmetry, win-rate != EV; report: reports/forge/smart-strike-scorer-weights-ab.md
- Bankroll CB 7d paper observation started 2026-05-31 (ends ~2026-06-07): confirm no spurious trips + persisted state survives Fly deploys
- WARP/ROOT/max-concurrent-ui-parity PR open — MINOR, WebTrader MaxConcurrentControl for max_concurrent_override; tsc + vite clean; report: reports/forge/max-concurrent-ui.md
- Paper observation (directive-strategy-alignment): confirm flip_hunter entries 0.10-0.35 at 60-180s before close; confirm dual-leg top-up completes the expensive leg

[NOT STARTED]
- Wire share_trade_kb into trade close call sites when PNL > 0 — surface ready, wiring deferred
- Referral payout activation — separate lane, WARP🔹CMD decision required
- Fee collection activation — separate lane, WARP🔹CMD decision required
- @require_access_tier('PREMIUM') on trading command handlers — separate lane, deferred

[NEXT PRIORITY]
- WARP-76 M1 PAPER-public hardening COMPLETE — all 4 PRs merged (#1622/#1623/#1624/#1625). Next: WARP🔹CMD decide next phase (WARP-74 Lane 2 staging proof, WARP-75 consent hardening, or open-position-per-user SENTINEL).
- WARP-74 Lane 2 staging proof: harness + runbook BUILT (WARP/live-staging-proof) — operator to provision isolated throwaway wallet + minimal USDC on a SEPARATE staging app (never prod), run all 5 cases per docs/runbooks/warp74-staging-proof.md, file the 4-artifact evidence bundle; must pass before real-money LIVE flip
- WARP🔹CMD merge review: WARP/ROOT/strategy-real-clob-sourcing + WARP/ROOT/playbook-game-sourcing (weather/playbook zero-opens root cause fixed; both PRs open)
- WARP-72 Phase 2 scorer: PARKED in shadow indefinitely — SCORER_ACTIVE=False; EV A/B (CMD-directed) showed scorer LOSES to router on holdout avg EV/trade (ev_delta -0.065; net-negative EV) despite +0.219 win-rate edge, cutover criterion NOT met. Router retained. CMD re-eval at ~400-500 settled rows/cell — CMD-triggered only, NO auto-rerun. Report: reports/forge/smart-strike-scorer-ev-ab.md

[KNOWN ISSUES]
- Weather + Playbook zero-opens: fixed in PRs WARP/ROOT/strategy-real-clob-sourcing + WARP/ROOT/playbook-game-sourcing — pending WARP🔹CMD merge + Fly redeploy
- late_entry_v3 OOS edge UNPROVEN: market_snapshots empty (SCAN_SNAPSHOT_ENABLED OFF); enable snapshot capture + accrue MIN_OOS_TRADES before re-running late_entry_oos.py (WARP-58)
- Cross-surface display-parity divergence: equity/P&L-window/unrealized-mark computed differently on WebTrader vs Telegram — shared computation lane deferred
- WARP/ROOT/risk-path-hardening PRs open: crash-recovery gate bypass (C-1 MAJOR) + weather gate step 4 unknown_strategy (C-2) — SENTINEL required before merge
- WARP/ROOT/open-position-per-user PR open: per-user limit replaces global 5-ceiling per owner directive 2026-06-03; MAJOR — SENTINEL required; report: reports/forge/open-position-per-user.md
- WARP/ROOT/playbook-feed-adapters PR open: MAJOR SENTINEL required (Injury Alpha + Public Fade full claim logic + ESPN/Odds API adapters); report: reports/forge/playbook-feed-adapters.md
- Multiple PRs pending WARP🔹CMD review: ux-fixes, auto-page-strategy-features, runtime-config-admin, warp54-audit-followups, scanner-market-detail, webtrader-ui-consistency
- crusaderbot-logo.png not in repo — WebTrader logo renders broken until PNG committed to webtrader/frontend/public/
- fly CLI unavailable in cloud execution environment — Fly.io deploys require WARP🔹CMD manual execution from fly CLI machine
- WARP-57 MEDIUM-4 deferred: production scanner (services/copy_trade/monitor.py) reads copy_trade_tasks but MVP writes copy_targets — end-to-end mirror inactive until swap lane
