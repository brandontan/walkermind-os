Last Updated : 2026-06-05 00:05
Status       : WARP-74 live reconciliation MERGED #1613 + mig 082 applied to prod; WARP-72 Phase 1 SHADOW collecting factor_vector dataset (4 settled, need ~50-100); WARP-69 auto-trade per-user hardening audit PR #1615 open (held for data window); staging proof pending before LIVE flip.

[COMPLETED]
- WARP-74 live reconciliation epic MERGED #1613 (c5f0ed1) — generalized live reconciler + kill-switch broker cancel_all + mig 082 applied to Supabase prod; SENTINEL APPROVED 97/100 0 critical
- WARP-74 Chunk A MERGED #1612 (4b742f2) — live-order orphan+drift detection/telemetry, no capital action; SENTINEL APPROVED 95/100 0 critical
- WARP-72 factor dataset persistence MERGED #1609 (e497b57) — mig 081, durable factor_vectors table + per-candle UPSERT + settlement backfill
- WARP-72 Phase 1 factor signals MERGED #1608 (8277937) — momentum signals + labeled vector emit, SHADOW-only, CI green; SENTINEL APPROVED
- WARP-57 SENTINEL re-audit APPROVED 86/100 0 critical (PR #1261 SHA aa4fe24c) — copy_targets schema mismatch resolved; MEDIUM-4 copy scanner swap deferred
- WARP-55 MERGED (abd3b43dbe10) — RUNTIME_EVIDENCE.md 7/7 P2 finish criteria proven; CrusaderBot closed beta DONE
- WARP/ROOT/oracle-rtds-frame-fix MERGED — live RTDS frame confirmed (crypto_prices_chainlink), SOL asset-aware band fix; MAJOR; report: reports/forge/oracle-rtds-frame-fix.md
- WARP/ROOT/oracle-price-to-beat-buffer MERGED — buffer-at-open price_to_beat, live e2e BTC/ETH/SOL all oracle_edge_status=computed; report: reports/forge/oracle-price-to-beat-buffer.md
- WARP/sentinel-candle-oracle SENTINEL APPROVED 96/100 0 critical — full oracle epic Chunks 1-3 validated at a92fec2; report: reports/sentinel/candle-oracle.md
- WARP/ROOT/sl-cap-risk-profile MERGED #1599 (3df5c93) — PAPER SL fill capped at stop-threshold price, LIVE uses real mark; SENTINEL APPROVED; report: reports/forge/sl-cap-risk-profile.md

[IN PROGRESS]
- WARP-69 (WARP/ROOT/auto-trade-per-user) PR #1615 open/held — audit + hardening of existing per-user autonomous loop (auto_trade_on canonical opt-in, no parallel gate); no capital-path defect; 12 tests, zero prod change; F1+F3 findings promoted to WARP-75; report: reports/forge/auto-trade-per-user-hardening.md
- WARP-74 staging proof: simulate crash mid-close (confirm no orphan) + confirm kill-switch cancels all resting GTC orders via broker cancel_all_orders — operator acceptance gate before LIVE flip
- WARP-72 Phase 1 shadow observation: factor_vector dataset accruing in paper (13 rows, 4 settled); need ~50-100 settled per asset/TF before Phase 2 weight derivation
- Bankroll CB 7d paper observation started 2026-05-31 (ends ~2026-06-07): confirm no spurious trips + persisted state survives Fly deploys
- WARP/ROOT/max-concurrent-ui-parity PR open — MINOR, WebTrader MaxConcurrentControl for max_concurrent_override; tsc + vite clean; report: reports/forge/max-concurrent-ui.md
- Paper observation (directive-strategy-alignment): confirm flip_hunter entries 0.10-0.35 at 60-180s before close; confirm dual-leg top-up completes the expensive leg

[NOT STARTED]
- Wire share_trade_kb into trade close call sites when PNL > 0 — surface ready, wiring deferred
- Referral payout activation — separate lane, WARP🔹CMD decision required
- Fee collection activation — separate lane, WARP🔹CMD decision required
- @require_access_tier('PREMIUM') on trading command handlers — separate lane, deferred

[NEXT PRIORITY]
- WARP-74 staging proof: crash sim (no orphan closing position) + kill-switch broker cancel-all confirmation — must pass before real-money LIVE flip
- WARP🔹CMD merge review: WARP/ROOT/strategy-real-clob-sourcing + WARP/ROOT/playbook-game-sourcing (weather/playbook zero-opens root cause fixed; both PRs open)
- WARP-72 Phase 2 (data-derived scorer weights) unblocked only after ~50-100 settled factor_vectors per asset/TF — currently 4 settled, collection in progress

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
