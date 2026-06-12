# CrusaderBot — FINISHING WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated : 2026-06-13 05:50**

> North Star: **finish CrusaderBot as a trusted, Telegram-first, multi-user, PAPER-mode autonomous trading bot.**
> No feature creep. Runtime truth > cosmetics.

---

## #1807 -- smart-strike-friendly-signal-status-polish

- [x] WARP•FORGE build on work (MINOR — NARROW INTEGRATION).
- [x] ScannerPanel Smart Strike no-trade reason status now uses friendly operator copy instead of raw snake_case/code-like telemetry.
- [x] Added curated labels for common fail-closed reasons: order book empty, liquidity too thin, below minimum order size, measured edge unavailable, no qualifying setup yet, no enabled markets in universe.
- [x] Unknown future reason codes still render deterministically by trimming skipped_ and replacing underscores with spaces; no reason is hidden.
- [x] Frontend-only presentation polish: no RuntimeStatus schema/API contract change, no scan/risk/order logic change, no live-guard flip, no order/fund movement.
- [x] test_smart_strike_no_trade_reason.py 19 passed; frontend npm run build green; screenshot captured at /tmp/smart-strike-friendly-status.png.
- [ ] WARP🔹CMD review.

## #1804 -- live-smart-strike-no-trade-diagnostic

- [x] WARP•R00T diagnostic (R00T-assigned, MAJOR — NARROW INTEGRATION) on WARP/live-smart-strike-no-trade-diagnostic.
- [x] Root cause: no-trade is expected fail-closed, MASKED by an observability bug — /status panel reads scanned/published from the legacy edge-finder (jobs/market_signal_scanner _scanner_state), not the real Smart Strike candle scan (services/signal_scan/signal_scan_job) whose scan_runs skip/rejection/zero-reason telemetry was never surfaced.
- [x] Read-only fix: summarize_no_trade_reason() derives the dominant no-trade reason from persisted scan_runs telemetry.
- [x] RuntimeStatus schema + /status endpoint carry the Smart Strike funnel counts + dominant reason (non-fatal read).
- [x] ScannerPanel status line shows awaiting_signal · <reason> instead of bare awaiting_signal.
- [x] Counter semantics documented: legacy scanner_scanned/published retained (edge-finder approval/publish), Smart Strike funnel added alongside (no risky rename).
- [x] LIVE order-intent positive path + fail-closed negative paths unchanged (assert_live_guards/$5 gate/measured-edge/min-order/kill-switch) — covered by existing gate tests; no live-guard flip, no order/fund movement, no fabricated signal.
- [x] test_smart_strike_no_trade_reason.py (helper logic 16/16 proven on source + required pins: zeros-cannot-hide-skip-reasons, user-facing reason surfacing); ruff + py_compile clean; frontend tsc+vite build green.
- [ ] WARP🔹CMD first-pass PR check.
- [ ] WARP•R00T final-gate disposition (self-merge on CI green) OR route to WARP•SENTINEL.

## #1800 -- polygon-usdc-usdt-deposit-enablement

- [x] FORGE build on warp/polygon-usdc-usdt-deposit-enablement (MAJOR — NARROW INTEGRATION).
- [x] End-to-end safety audit: sweep is USDC.e-contract-bound, no USDC/USDT->USDC.e conversion path -> native USDC + USDT cannot be safely enabled.
- [x] Both tokens stay DISABLED with explicit documented blockers (no fake-enablement, per issue guardrail).
- [x] Explicit capability matrix on DepositAsset (detectable/creditable/sweepable/reconcilable/convertible/disabled_reason); enabled gate requires the full matrix.
- [x] CMD UI scope update: capability-card list removed from DepositModal; compact selected-token status + dropdowns + QR + raw-address copy + concise warnings; disabled token gates off QR/address/copy.
- [x] USDC.e + #1795/#1798 sweep behaviour + reorg-normalized-revert + wrong-token credit-neutral + $5 live gate + live guards preserved.
- [x] 16 new tests; full suite 3583 passed; frontend build green.
- [ ] WARP🔹CMD first-pass PR check.
- [ ] WARP•R00T finishing pass / final gate before merge.

## #1801 -- smart-strike-audit-gaps-closure

- [x] Per-user sizing isolation explicit tests: get_live_balance binds only the active user; live ledger bucket excludes paper/pending/pool; gate sizes per-user; Kelly 0.25 (no audit-prose-only).
- [x] Polymarket-API eligibility: late_entry_v3 rejects archived=true + enableOrderBook=false (fail-closed, behaviour-tested); existing active/closed/acceptingOrders/clobTokenIds/tick/neg_risk/empty-book preserved.
- [x] LIVE_MIN_ORDER_SHARES=5 — live order below CLOB minimum fails closed pre-submit (no broker round-trip).
- [x] Market-data freshness posture documented/tested: fresh REST get_book per candidate, empty/missing book = NO TRADE, missing metadata fails closed (no stale-WS leak path on this surface).
- [x] User-facing SOL-disabled: shared smart_strike_universe single-source-of-truth (scan gate delegates; /autotrade exposes enabled universe; AutoTradePage disables admin-off assets in picker; copy corrected on WebTrader + Telegram).
- [x] Observability: structured live_order_intent trace (token/side/price/spread/size/tick/min/user).
- [x] #1799 market-universe behaviour preserved (all universe + signal-scan tests green after delegation refactor).
- [x] 20 new tests; full suite 3567 passed; frontend build green; PR merged under WARP•R00T final gate.

## #1797 -- smart-strike-live-readiness-audit

- [x] WARP•R00T audit (R00T-assigned lane): execution routing NOT paper-only — real CLOB live path, fail-closed on every missing guard/credential.
- [x] Sizing/per-user isolation CLEAR PASS: active user's confirmed available live balance only; Kelly hard-capped 0.25; no pool/cross-user/paper leak.
- [x] Strategy rules verified against code truth (entry window/ask-diff/spread/price-band/precedence router); no material docs-code mismatch.
- [x] FIXED: SOL disabled by default (SMART_STRIKE_SOL_ENABLED=False, owner lock).
- [x] FIXED: 6 admin runtime market-universe controls (master/BTC/ETH/SOL/5m/15m) wired into both scan loops with explicit skip reasons; disabled bucket produces no candidates/order intent.
- [x] Admin enablement bypasses no user mode / Auto-Trade / $5 balance / measured-edge / kill-switch / live-guard gate (pinned).
- [x] 15 new tests; full suite 3547 passed; PR merged under WARP•R00T final gate.

## #1796 -- polygon-multi-token-deposit-activation

- [x] FORGE build complete on warp/activate-polygon-multi-token-deposit (MAJOR — NARROW INTEGRATION).
- [x] WebTrader DepositModal changed from static option cards to Polymarket-style token dropdown + Polygon-only chain dropdown; disabled tokens remain visible as unavailable but not selectable.
- [x] Polygon-only scope preserved: USDC.e on Polygon remains the only enabled end-to-end asset; native Polygon USDC and Polygon USDT remain disabled with explicit backend/custody blockers.
- [x] QR/address/copy remain gated to selected enabled assets; COPY still writes raw address only.
- [x] On-chain sweep SQL now filters to the primary enabled asset (network/chain/token, legacy NULL token rows allowed) before sweep user selection and swept/manual-review updates, preventing unsupported token rows from riding the USDC.e sweep path.
- [x] LIVE Auto-Trade $5 confirmed-balance guard and live guard flags unchanged.
- [x] Report filed: projects/polymarket/crusaderbot/reports/forge/polygon-multi-token-deposit-activation.md
- [x] WARP🔹CMD first-pass PR check — 5 blockers + 4 hardening items raised on PR #1798.
- [x] WARP•R00T finishing pass: behaviour-level sweep asset-filter tests (CMD blocker 5 — unsupported tokens never selected/swept/manual-reviewed); chain-local selected fallback; disabled-token non-selectability pinned; exact branch + PROJECT_STATE truth + PR body. PR #1798 MERGED under WARP•R00T final gate.

## #1793 -- multi-asset-deposit-selector

- [x] FORGE build complete on warp/add-multi-asset-deposit-selector (MAJOR — NARROW INTEGRATION).
- [x] wallet/deposit_assets.py allowlist: token+network separated; ONLY Polygon USDC.e enabled end-to-end; native USDC detect-only; USDT/Base/Arbitrum disabled with honest reasons.
- [x] Migration 099 preserves original token/network/contract/decimals + normalized credit amount on deposit rows (backfilled).
- [x] Watcher records original asset truth and credits from normalized amount; wrong-token path stays credit-neutral; mismatched-token insert raises.
- [x] Unsupported assets get no deposit address/QR/copy on UI or API.
- [x] WARP🔹CMD first-pass PR check — 6 blockers + 4 hardening items raised on PR #1795.
- [x] WARP•R00T finishing pass: merged main; migration renumbered 098->099 (collision with #1794); COPY writes raw address only; token_decimals propagated + explicit is-None fallbacks (zero-normalized credits 0, behaviour-tested); e2e tests upgraded to token-scoped scan branching; exact branch across artifacts. PR #1795 MERGED under WARP•R00T final gate.

## #1792 -- live-switch-notification-isolation-fix

- [x] FORGE build complete on warp/fix-live-switch-notification-isolation (MAJOR — NARROW INTEGRATION).
- [x] PAPER -> LIVE switch archives pre-switch per-user AlertCenter rows with dismissed=TRUE while preserving system_alerts audit records.
- [x] LIVE /alerts query keeps alerts_ack_at filtering and excludes user-scoped structured alerts whose metadata.mode does not match current trading_mode.
- [x] WebTrader settings SSE clears/refetches AlertCenter state so stale in-memory PAPER alerts/unread counters do not survive the switch.
- [x] Daily P&L web alerts are tagged mode=paper; trade event-bus web mirrors carry structured mode metadata.
- [x] Auto-Trade OFF, $5 confirmed live balance start guard, optional/recommended 2FA posture, and all live guard flags remain unchanged.
- [x] WARP🔹CMD first-pass PR check — 5 blockers (incl. scope expansion to full paper-session reset) + hardening raised on PR #1794.
- [x] WARP•R00T finishing pass: FULL paper-session reset (migration 098 ledger.archived; archive paper ledger + reset $1,000+live bankroll + seed fresh paper deposit on paper->live; /activity//orders//wallet feeds exclude archived/paper_archived); CI-red fixed; unmodeled-alert dismissal hardened; exact branch + PROJECT_STATE truth. Full suite 3508 passed. PR #1794 MERGED under WARP•R00T final gate.

## #1787 -- live-enable-tos-checkbox-flow

- [x] FORGE build complete on warp/implement-live-enable-tos-checkbox-flow (MAJOR — NARROW INTEGRATION).
- [x] WebTrader LIVE enable typed phrase replaced with ToS/risk checkbox consent.
- [x] Backend missing-consent path returns HTTP 400, accepted consent is audited with timestamp/version/user/surface/source, and $0 live balance succeeds as waiting-for-deposit.
- [x] 2FA remains optional/recommended for account and withdrawal protection; no 2FA setup/status/verify/disable surface removed.
- [x] Auto-Trade remains OFF after PAPER -> LIVE switch; shared LIVE Auto-Trade start guard still requires confirmed available live USDC.e >= $5.
- [x] WARP🔹CMD first-pass PR check — 6 blockers + consent-version hardening raised on PR #1791.
- [x] WARP•R00T finishing pass: switch no longer blocked on operator/checklist readiness in LiveActivationModal (warning/status only); STRICT consent_version (missing/stale → 400); 2FA card copy fixed to optional/recommended; merged main + exact branch across artifacts. PR #1791 MERGED under WARP•R00T final gate.

## #1782 -- self-serve-paper-to-live-switch

- [x] FORGE build complete on warp/implement-self-serve-paper-to-live-switch (MAJOR — NARROW INTEGRATION).
- [x] Self-serve typed-confirm PAPER -> LIVE switch implemented without mandatory 2FA/admin approval.
- [x] Switch forces Auto-Trade OFF and leaves LIVE Auto-Trade locked until confirmed available live USDC.e >= $5 plus required live checklist gates.
- [x] Paper simulation positions/orders archived out of user-facing live surfaces; pre-switch alerts acknowledged for clean live notification context.
- [x] WARP🔹CMD first-pass PR check — 5 blockers raised on PR #1784.
- [x] WARP•R00T finishing pass: shared evaluate_live_autotrade_start guard enforced on WebTrader /autotrade/toggle (CMD blocker 2) + Telegram + MVP; merged main onto #1783 state shape; stale test_live_mode_truth enable-pin relocated to the live_mode helper; exact branch across artifacts. Full suite 3487 passed. PR #1784 MERGED under WARP•R00T final gate.

## P0 -- Runtime Spine Validation (MANDATORY)

Prove the actual runtime spine is real end-to-end:


```text
/start
→ onboarding
↓ user state
↓ paper wallet
↓ default strategy
↓ active scanner
↓ analysis engine
↓ risk gate
↓ paper trade open
↓ position monitor
↓ paper trade close
↓ portfolio update
↓ Telegram receipt
```

Deliverables:
- [x] Runtime evidence matrix
- [x] Broken/fake/dead path map
- [x] Multi-user isolation verification
- [x] Proof PAPER ONLY posture unchanged
- [x] Pre-handoff CORE AUDIT — WARP/crusaderbot-system-audit 2026-05-23 (sentinel report; F-CRIT-1 boot-blocker found)
- [x] F-CRIT-1 boot fix — bot/ui/__init__.py stale BAR/BRANCH/LAST re-export removed; import clean + 1613 pytest pass (consolidated into PR #1294, per WARP🔹CMD; PR #1295 closed)
- [ ] F-HIGH-2 — 0 live trade data; PRIMARY cause fixed in WARP/lib-strategy-load-fix (lib/ strategies never loaded: outside Docker build context + relative-import loader bug; now vendored + importable, all 7 load). Pending SENTINEL + deploy to confirm trades flow. SECONDARY (open): Phase C evaluate_publications_for_user feed-eval path.

---

## P0 -- WebTrader Realtime Trust

Validate and fix realtime trust gaps:

- [x] Terminal updates without manual refresh
- [x] Scanner counts match backend jobs
- [x] Recent Activity synced to runtime truth
- [x] Portfolio / Wallet sync with ledger
- [x] Heartbeat / last_tick / last_scan timestamps
- [x] PAPER ONLY posture clear; LIVE not misleading

---

## P0 -- Production Integrity

Close production gaps before beta:

- [x] Apply migrations 027/029/030 — APPLIED 2026-05-21
- [x] Apply migration 031 — APPLIED 2026-05-21
- [x] Apply migration 044 (DROP access_tier) — CONFIRMED APPLIED (access_tier column gone from schema)
- [x] Fly.io deploy validation
- [x] Scheduler health / retry check
- [x] RLS lockout — Row Level Security ENABLED on ALL 43/43 public tables (migration 046 + later migs incl. 055 scan_runs; verified live 2026-05-27 via Supabase advisors + list_tables — 0 rls_disabled errors).
- [x] WARP-52 — portfolio_snapshots Python writer / cb_portfolio NOTIFY wiring (Issue #1245) [STANDARD] — DELIVERED WARP/portfolio-snapshots-writer 2026-05-21
- [x] Telegram notification reliability — WARP-53 DELIVERED 2026-05-21 (WARP/warp53-reliability-hardening)
- [x] Logging and operational sanity

---

## P1 -- Closed Beta Hardening

Observe the runtime under real usage:

- [x] No duplicate trades — WARP-54 DELIVERED 2026-05-21 (paper.execute ON CONFLICT pinned + regression test)

---

## P1 -- Telegram UX Final (After Runtime Proven)

- [x] No dead buttons
- [x] No fake placeholder routes
- [x] State-driven keyboard
- [x] Concierge onboarding polish
- [x] Portfolio / Settings clarity
- [x] No legacy tier / operator wording

---

## P2 -- Project Finish Criteria

CRUSADERBOT is considered **DONE** only when:

- [x] WebTrader running
- [x] Runtime spine proven end-to-end
- [x] WebTrader realtime trusted
- [x] Telegram stable
- [x] Paper trading stable
- [x] No user bleed
- [x] No dead routes
- [x] Closed beta clean
- [ ] Production checklist complete

---

## Active — In Progress

- [x] realtime-deposit-withdraw-engine / warp/implement-realtime-deposit-and-withdraw-engine — #1780 built (FORGE) + R00T-finished, PR #1781 (MAJOR, NARROW INTEGRATION; WARP•R00T final gate, self-merge on CI green). Near-realtime deposit confirmation triggers immediate per-user ON-CHAIN sweep only when guards armed; guard-off defers truthfully (swept stays FALSE, cron fallback + later on-chain retry preserved). Withdrawal lifecycle locks funds, submits under guards, records confirmation metadata, refunds preflight failures, marks ambiguous failures manual_review. Report: reports/forge/realtime-deposit-withdraw-engine.md.

- [x] WARP•R00T overnight full-surface live/paper readiness program (owner directive 2026-06-10) — Phase 0 matrix #1754 + Lane A live-notify-parity #1755 (SENTINEL APPROVED 98/100) + Lane B telegram-live-truth #1756 ALL MERGED; suite 3413/11. Matrix: reports/forge/readiness-matrix.md. Wake-up handoff: reports/forge/overnight-handoff.md. Remaining go-live items owner-gated ops only (POLYGON_RPC_URL, backfill, flag/guard flips, mainnet moves).

- Candle Oracle epic (Linear WARP-61, multi-asset BTC/ETH/SOL edge engine for late_entry_v3):
  - [x] WARP-62 Chunk 1/4 [STANDARD/FOUNDATION] MERGED #1601 (squash fbe2abd) — multi-asset oracle client via Polymarket RTDS WebSocket + price_to_beat capture (staleness-honest; default OFF). Report: reports/forge/oracle-chainlink-client.md.
  - [x] WARP-63 Chunk 2/4 [STANDARD/FOUNDATION] MERGED #1602 (squash 5f6bf72) — pure per-asset-sigma fair-value / edge calculator. Report: reports/forge/oracle-fairvalue-calc.md.
  - [x] WARP-64 Chunk 3/4 [MAJOR → SENTINEL] MERGED #1603 (a92fec2) — ADVISORY wiring of the oracle + fair-value edge into late_entry_v3 (BTC/ETH/SOL): per-candidate edge metadata computed/logged/stamped (never blocks this chunk), lazy RTDS-oracle singleton in signal_scan_job (start-once/reuse/warmup-tolerant/shutdown-stop), per-preset Distance/Min-Edge/Trend, two flags default OFF (ORACLE_EDGE_GATE_ENABLED + ORACLE_ENABLED). 11 new + 57 oracle + 110 candle/scan regression tests pass; ruff + py_compile clean. Risk gate/exits/capital path untouched. Report: reports/forge/oracle-strategy-wiring.md.
  - [x] WARP-65 Chunk 4/4 [MAJOR validation] — WARP•SENTINEL paper validation of Chunk 3 (advisory edge logs per candidate, singleton lifecycle, zero gate/exit impact). SENTINEL APPROVED 96/100 0 critical. Report: reports/sentinel/candle-oracle.md.
- [x] WARP/ROOT/candle-auto-router [MAJOR → SENTINEL] MERGED — candle_auto preset (🔥 Smart Strike): additive lifecycle-router over close_sweep/safe_close/flip_hunter on the same late_entry_v3 engine. Per-market stage routing (flip early underdog → safe mid → close final favorite), per-rule force-exit + TP/SL threaded via candidate metadata → strategy_metadata, dedup close>safe>flip. 3 single presets untouched; new RECOMMENDED preset. 8 new tests + 2286 suite pass; ruff clean. Pre-LIVE gap: live.py strategy_metadata not persisted (force-exit fallback PAPER-only; TP/SL works in LIVE). Report: projects/polymarket/crusaderbot/reports/forge/candle-auto-router.md.
- SMART STRIKE scoring orchestrator epic (Linear WARP-72, data-derived weights, shadow-validated vs precedence router):
  - [x] WARP-72 Phase 1 [STANDARD/NARROW] WARP/ROOT/smart-strike-factor-signals — built the missing factor signals + labeled dataset, SHADOW-only: rolling momentum/repricing (domain/signal/momentum.py) replacing instantaneous ask_diff; volatility sigma EXPOSED as a scorable input; liquidity/spread/orderbook-depth/TTL confirmed exposed on a unified factor_* surface; oracle kept advisory; full 7-factor vector + router-selected rule + realized open→close label emitted for EVERY evaluated candle (traded or not), decoupled from execution; FACTOR_VECTOR_SHADOW_ENABLED default ON. No selection/gate/sizing change. 16 tests. Report: projects/polymarket/crusaderbot/reports/forge/smart-strike-factor-signals.md.
  - [x] WARP-72 Phase 2 PREP [MAJOR/NARROW] WARP/ROOT/factor-dataset-persistence — durable labeled dataset: factor_vectors table (migration 081), one-row-per-candle UPSERT (GRAIN=condition_id, latest-wins, write-throttled) for EVERY evaluated candle + scheduled settlement backfill (run_factor_settlement_backfill) resolving realized open->close from the oracle ring (outcome_source provisional->open_to_close; aged-out->unresolved). router_selected_rule backfilled. FACTOR_DATASET_PERSIST_ENABLED default ON. Shadow-only. 9 tests. Operator: apply migration 081 + ORACLE_ENABLED in paper. Report: projects/polymarket/crusaderbot/reports/forge/factor-dataset-persistence.md.
  - [x] WARP-72 Phase 2 [STANDARD/NARROW] claude/jolly-brahmagupta-kb02j — scoring orchestrator (shadow): StrategyScorer (domain/strategy/scorer.py) ranks close_sweep/safe_close/flip_hunter by per-cell factor-weighted score from config/scorer_weights.json + ADDITIVE Oracle deny-gate (WARP-66 2.0/1.0/3.0% at 5m, score can't override deny); scorer_trainer.py derives BTC/5m+ETH/5m weights from settled open_to_close rows, SOL/5m skipped (no_data, explicit log); shadow wiring in signal_scan_job emits scorer_shadow log (scorer_selected_rule vs router_selected_rule) per candle, execution path unchanged; SCORER_SHADOW_ENABLED=True, SCORER_ACTIVE=False (router controls). scorer_selected_rule is log-only (no schema change). 18 tests; ruff clean. Operator: CMD-greenlit scorer_trainer.py --from-db to replace untrained stub. Report: projects/polymarket/crusaderbot/reports/forge/smart-strike-scorer.md.
  - [x] WARP-72 Phase 3 — shadow A/B: RUN ON LIVE DATA (CMD-approved). scorer_trainer derived BTC/5m=170 + ETH/5m=168 weights (SOL/5m skipped no_data); scorer_ab holdout: scorer beats router +0.315 win-rate overall (BTC +0.471, ETH +0.179, ≥20/cell) — numeric cutover gate MET. CAVEAT for Phase 4: edge is favorite/underdog asymmetry (favorite wins 92.9% at open→close; recorded router picks ~73% flip_hunter underdog), win-rate != EV; an EV/realized-PnL read is required before cutover. Report: projects/polymarket/crusaderbot/reports/forge/smart-strike-scorer-weights-ab.md.
  - [ ] WARP-72 Phase 4 — cutover (data-gated): switch selection to the scorer ONLY if it beats the router; keep router as flagged fallback. STATUS 2026-06-05 (PARKED): EV A/B run (CMD-directed) — scorer trained on EV label (is_win - entry_price), BTC/5m=173 + ETH/5m=171. Holdout avg EV/trade: scorer LOSES to router (ev_delta -0.065 overall; scorer net-negative EV) despite +0.219 win-rate edge. Cutover criterion avg_ev(scorer)>avg_ev(router) NOT met → DO NOT flip SCORER_ACTIVE. CMD DECISION: scorer PARKED in shadow indefinitely (SCORER_ACTIVE=False); re-eval at ~400-500 settled rows/cell, CMD-triggered only, NO auto-rerun. Report: projects/polymarket/crusaderbot/reports/forge/smart-strike-scorer-ev-ab.md.
- WARP-77 real-data cutover (Linear WARP-77):
  - [x] WARP-77 Phase 1.4 — factor_vectors data_source provenance MERGED #1655. Migration 083 enum + NOT NULL DEFAULT paper_synthetic + resolve_data_source. Report: reports/forge/warp77-factor-provenance.md.
  - [x] WARP-77 Phase 1.2 — real-CLOB-data feed heartbeat MERGED #1656. clob_heartbeat module, arms only when USE_PYSDK_CLOB=true. Report: reports/forge/warp77-realdata-cutover.md.
  - [x] WARP-77 CUTOVER LIVE — operator set USE_PYSDK_CLOB=true ~06:32 UTC 2026-06-06. Verified: migrations 083+084 applied; paper_real rows accruing; realized_vol computing; heartbeat armed+quiet. 24h obs + 7-day shadow started.
- WARP-78 SMART STRIKE refinement (Linear WARP-78, label-fix + vol factor + EV-comparator):
  - [x] WARP-78 Phase 0 — scorer EV-failure diagnosis (report-only) MERGED #1654. Root cause structural: degenerate rules + biased open→close label + dead Volatility/Momentum. Report: reports/forge/smart-strike-scorer-ev-failure.md.
  - [x] WARP-78 Phase 1a — realized-volatility factor MERGED #1657. compute_realized_vol per-√s + MomentumTracker.realized_vol + migration 084 + FactorVector.realized_vol. SHADOW-only. Report: reports/forge/warp78-realized-volatility.md.
  - [x] WARP-78 Phase 1b — safe_close-horizon realized label MERGED #1659. migration 085 realized_outcome_safe_close + settlement backfill at open→(close-30s). Report: reports/forge/realized-ev-label-safe-close.md.
  - [x] WARP-78 Phase 2 — EV label consumption + vol↔EV correlation + EV-comparator MERGED #1660. Per-rule horizon label routing (safe_close → sc column) in trainer/A/B; vol correlation validated (safe_close r=−0.29 BTC/5m); ev_comparator.py (ORCHESTRATOR_ACTIVE=False) shadow-wired into scan loop. Report: reports/forge/ev-phase2-label-consumption.md.
  - [x] WARP-78 Phase 3 — factor-weighted EV estimation BUILT (WARP/root-ev-phase3). ev_comparator.py schema v2 (estimated_ev = base_ev + Σ w[f]*z_f); per-cell norm + per-rule shrunk Pearson weights; late_entry_v3 shadow passes live factors; holdout A/B infra; momentum dominant (r=0.52-0.91). ORCHESTRATOR_ACTIVE=False. 24 tests. Report: reports/forge/ev-phase3-factor-weighted.md. Next: ~200 paper_real rows/cell → generate model → holdout A/B → WARP🔹CMD cutover decision.
- WARP-74 — live order reconciliation epic (broker<->DB truth + kill-switch broker cancel-all):
  - [x] WARP-74 Chunk A [MAJOR → SENTINEL] WARP/ROOT/reconcile-live-orders MERGED #1612 (4b742f2), SENTINEL APPROVED 95/100 — broker-truth reconcile sweep (domain/execution/reconcile.py LiveOrderReconciler): pulls ClobAdapter.get_open_orders and diffs vs the orders table → ORPHAN (resting at broker, not tracked as open — audit live_order_orphan_detected + throttled operator page) + db-only drift (counted; poll owns resolution). Detection/telemetry ONLY — no cancel/size/gate/mutate; no-op in paper/non-live; fail-soft. Scheduler live_order_reconcile job (RECONCILE_INTERVAL_SEC=120s, gated RECONCILE_LIVE_ORDERS_ENABLED) + config validator. 9 hermetic tests; ruff clean. Report: projects/polymarket/crusaderbot/reports/forge/reconcile-live-orders.md.
  - [x] WARP-74 Chunk B [MAJOR → SENTINEL] kill-switch broker cancel-all — wire ClobAdapter.cancel_all_orders into domain/risk/kill_switch_exec.execute_kill_switch (gated USE_REAL_CLOB+ENABLE_LIVE_TRADING, fail-soft, audited) so a kill cancels resting orders at the broker, not just DB-marks pending. MERGED as part of the consolidated live-reconciliation epic #1613 (c5f0ed1) — kill-switch broker cancel_all wired + mig 082 applied; SENTINEL APPROVED 97/100, 0 critical. Broker-side cancel-all proven on the real CLOB v2 broker by WARP-74 staging case3 (run #13/#16).
  - [x] WARP-74 Lane 2 [STANDARD/NARROW] WARP/live-staging-proof — live-broker staging proof harness BUILT: tests/staging/test_live_reconcile_staging.py covers all 5 acceptance cases (kill cancel-all GTC-gone / unknown-order adopt-page-halt / closing rollback-page-finalize* / drift broker+db-only no-mutation / infra-degraded paper fallback) against a REAL Polymarket CLOB broker on an isolated throwaway wallet, tiny orders; DB side is a recording fake (never writes a DB — cannot touch prod); STAGING_WALLET_KEY-guarded (pytest collects + 9 skipped/0-fail with no wallet, CI-safe); finalize-once additionally STAGING_ALLOW_FILLS-gated. Operator runbook docs/runbooks/warp74-staging-proof.md (prereqs, env matrix, per-case expected Telegram alert text, PASS/FAIL, 4-artifact evidence capture). Zero production code touched. PROOF EXECUTED + PASSED: all 5 acceptance cases GREEN on the CLOB v2 pysdk backend from Fly nrt (allow_fills=false, no real USDC) — all-broker TRUE 8/8 run #16 (27028306156, sha 75cb1f10); harness false-green meta-bug fixed (per-run PROOF_NONCE + scripts/proof_result.sh fail-closed); CLOB v2 proxy-read fixes (#1645/#1646/#1647) + case1 poll (#1650) landed en route; PRs #1645-#1651 merged. Only the owner-gated LIVE flip remains. Reports: projects/polymarket/crusaderbot/reports/forge/live-staging-proof.md + staging-harness-integrity.md + case1-test-poll.md.
- [ ] WARP•R00T full-system pre-public audit fix campaign — verdict CONDITIONAL (safety/money core APPROVED + fail-closed; user-facing correctness + API hardening + pre-LIVE money-path lanes opened). Lanes:
  - [x] Lane 1/5 WARP/ROOT/mode-status-display [STANDARD/NARROW] MERGED #1453 — Theme #1 phantom-key mode/status display. Report: reports/forge/mode-status-display.md.
  - [x] Lane 2/5 WARP/ROOT/silent-broken-features [MAJOR] MERGED #1454 + deployed — copy-trade monitor tz-aware ts, withdrawal-notify parse_mode, frontend error-vs-empty states. Report: reports/forge/silent-broken-features.md.
  - [x] Lane 3a/5 WARP/ROOT/api-hardening [MAJOR] MERGED #1455 + deployed — ops 503-when-unset (B1), drop ?token= mutators (B3), /autotrade/customize bounds (B4), /auth IP rate-limit (B5). Report: reports/forge/api-hardening.md.
  - [x] Lane 3b/5 WARP/ROOT/sse-token-exchange [MAJOR] PR open — B2: JWT out of SSE URL via 60s scope='sse' handshake token (POST /stream-token + stream validates scoped token + get_current_user rejects sse tokens + frontend sse.ts mints per reconnect). 7 tests; ruff + tsc + vite clean. Report: reports/forge/sse-token-exchange.md.
  - [x] Lane 4/5 WARP/ROOT/tg-callback-routing [STANDARD] PR open — dashboard:* + settings:* legacy sub-routes were swallowed by MVP handlers; now MVP keeps its own screens + delegates unknowns to legacy settings_callback / dashboard_nav_cb (TP/SL, wallet, health, admin, insights, portfolio restored). 6 routing tests + 61 regression pass. Report: reports/forge/tg-callback-routing.md.
  - [x] Lane 5/5 WARP/ROOT/live-path-hardening [MAJOR, pre-LIVE] PR open — master-EOA nonce lock + pending tag (all 4 on-chain sends), submit_live_redemption gas ceiling, signal_scan live_capital_cap_usdc SELECT, _passes_live_guards += USE_REAL_CLOB, gate Kelly bound 0.5→0.25. 6 tests + 89 money-path regression pass. ADVISORY: MAX_CONCURRENT_TRADES=5 vs per-profile cap left for WARP🔹CMD policy call. Report: reports/forge/live-path-hardening.md.
- [x] WARP•R00T admin-page [MAJOR/FULL RUNTIME] — WARP/ROOT/admin-page. WebTrader Ops console (/admin, role=admin): overview (master pool address+balance, guards, kill switch, counts, last scan), users roster, global strategy on/off (12 strategies, new `strategies` table mig 067 applied + RLS) wired fail-safe into scanner (_preset_allows cache + signal_following NOT EXISTS). Endpoints /api/web/admin/* gated by _require_admin; /me role+is_admin; Settings Ops-Console entry. 11 tests; suite 2018 pass; tsc + vite clean. Report: reports/forge/admin-page.md.
- [ ] WARP•R00T go-live-guards [MAJOR] — HELD (committed local, NOT pushed). Flips 5 guards + USE_REAL_CLOB in fly.toml. Waits on operator: fund master wallet (USDC+MATIC) + set POLYMARKET secrets, then push.
- [x] WARP•R00T account-link-telegram [MAJOR/FULL RUNTIME] — WARP/ROOT/account-link-telegram. Reverse Telegram-link: email-first WebTrader user unifies into ONE account across both surfaces (one user_id → LIVE/PAPER + wallet + trades in sync). Closes identity asymmetry (Telegram→email link_email existed; email-first→Telegram made a 2nd unsynced account). One-time code: WebTrader Settings → Link Telegram mints code (account_link_codes, mig 065) → bot /link <code>. account_link.py: no-dup → attach (OK_LINKED); fresh dup → tombstone (synthetic email + users.merged_into, NOT deleted; FK-safe) + reassign (OK_MERGED); dup with history/live → BLOCK → operator merge. Endpoints /account/link-telegram/{status,start}; bot /link; optional TELEGRAM_BOT_USERNAME deep link; Settings UI. 15 tests; suite 2005 pass; ruff + tsc + vite clean. NEEDS mig 065 applied to Supabase. Report: reports/forge/account-link-telegram.md.
- [x] WARP•R00T live-activation-ux [MAJOR/FULL RUNTIME] MERGED #1438 — WARP/ROOT/live-activation-ux. Completes the per-user LIVE opt-in UX on BOTH surfaces (WebTrader = full control, Telegram = simple control, in sync). Shared source of truth in domain/activation/live_opt_in_gate.py (LIVE_ENABLE_CONFIRM_PHRASE + LIVE_CAP_MIN/MAX_USDC + validate_live_capital_cap); WebTrader router imports phrase+bounds; api.ts mirrors them. Telegram CRITICAL fix: /enable_live cap-capture step now writes trading_mode='live' AND live_capital_cap_usdc together (was mode-only → live_not_opted_in at gate step 15); new /disable_live revert. WebTrader LiveActivationModal (preview → cap → typed confirm) + described "Live Trading" Settings section. No-silent-failure hardening: write_mode_change_event returns bool; dashboard.py logs instead of swallowing. Plain-language explanations every step. Full suite 1990 pass (+31 tests); ruff + py_compile + tsc + vite build clean. Report: reports/forge/live-activation-ux.md.
- [x] WARP•R00T notifications-overhaul [MINOR/NARROW] — WARP/ROOT/notifications-overhaul. WebTrader AlertCenter visual + interaction refresh to match the Kreo-style notifications mockup the owner shared: new "Mark all read" action in header (dismisses all visible + bumps lastSeen), always-visible dismiss × (was hover-only), `⚙ Preferences` shortcut in footer routing to /settings, body wraps instead of truncating, SIGNAL category icon (📡) covering both copy + signal severities. Frontend-only — backend / SSE / alert fetch path untouched. tsc + vite build clean. Report: reports/forge/notifications-overhaul.md.
- [x] WARP•R00T safe_close + flip_hunter Kreo-parity [MAJOR/NARROW] — WARP/ROOT/safe-close-flip-hunter-kreo-parity. Realigns the two candle presets to Kreo's reference behaviour (per Kreo Polymarket Telegram bot docs): safe_close min_ask_diff 0.08→0.01 + new force-exit at rem=30s (closes BEFORE the noisy final 30s where SL was firing at random); flip_hunter inverted from late-window underdog to early-window favored side (Kreo "With Trend") with per-timeframe windows (5m rem 160-300 / 15m rem 480-900) + force-exit at end of entry window. Adds Kreo-style fixed-time exit MECHANISM in late_entry_v3.evaluate_exit (checks force-exit before flip-stop), single-source-of-truth `force_exit_at_rem_sec_for(preset, tf)` helper consumed by both entry + exit paths, per-tf-aware `_resolve_preset_params(preset, tf)` resolver, OpenPositionForExit + exit_watcher enrichment to pass active_preset + selected_timeframe + seconds_to_close (from existing JOIN + resolution_at — no migration). close_sweep unchanged. 27 new hermetic tests; suite 1894 pass. Risk gate + activation guards untouched. Report: reports/forge/safe-close-flip-hunter-kreo-parity.md.
- [x] WARP•R00T late-entry fill-drift guard [STANDARD/NARROW] — WARP/ROOT/late-entry-fill-drift-guard. Closes a fill-time correctness gap in close_sweep / safe_close / flip_hunter: late_entry_v3 candidates passed scan-time gates with one set of orderbook prices, then `_process_candidate` fetched the live fill price via `get_live_market_price` and built the TradeSignal with no re-validation. Candle markets drift 0.10+ in seconds, so actual fills landed wherever — prod 24h showed only 5.5% of safe_close trades + 17% of close_sweep trades inside the strategy's intended band (avg entry 0.45, with fills as low as 0.04 and as high as 0.94). Fix: `late_entry_v3._evaluate_market` now emits `fav_price_min/max` in candidate metadata; new gate 3c in `_process_candidate` (between live-price fetch and signal build) requires `live_fill_price ∈ [fav_price_min, fav_price_max)` — skipped_fill_drifted otherwise. Metadata-driven and opt-in: signal_following / lib / confluence_scalper candidates carry no band keys → gate no-ops. Risk gate's 13 steps + activation guards untouched. 6 new hermetic tests (4 gate-3c + 2 strategy-metadata); full suite 1866 pass; ruff + py_compile clean. Report: reports/forge/late-entry-fill-drift-guard.md.
- [x] WARP•R00T LIVE+PAPER readiness pass — Lane 1 system-ready-audit [MINOR/FOUNDATION] MERGED #1409. Read-only audit. Verdict: 0 current risks. All 5 LIVE activation guards default false, assert_live_guards 8-condition chain, router GUARD_BYPASS_ATTEMPT logging + paper-fallback, LIVE-flip 8-gate checklist + typed CONFIRM, PAPER-default at schema layer across all three new-user paths verified. Surfaced 3 brittleness items for Lane 2. Report: reports/forge/system-ready-audit.md.
- [x] WARP•R00T LIVE+PAPER readiness pass — Lane 2 paper-default-hardening [STANDARD/NARROW] MERGED #1410. Belt-and-suspenders: explicit `trading_mode='paper'` in every user_settings INSERT (users.py upsert_user + lazy get_settings_for + new explicit INSERT in webtrader/backend/auth.py signup); silent `except Exception: pass` in webtrader signup replaced with logger.exception; new hermetic tests/test_paper_default_invariant.py (5 tests, INSERT-call-shape + source-regex layers). Full suite 1859 pass; ruff + py_compile clean. PAPER remains the only mode any user receives at creation regardless of ENABLE_LIVE_TRADING. Report: reports/forge/paper-default-hardening.md.
- [x] WARP•R00T LIVE+PAPER readiness pass — Lane 3 live-readiness-final [MINOR] MERGED #1411. State-doc sync only. Updates LIVE_READINESS.md, PRODUCTION_CHECKLIST.md, WORKTODO.md, PROJECT_STATE.md, CHANGELOG.md to reflect Lanes 1+2 closure; owner-only "Final go-live sequence" preserved verbatim. Report: reports/forge/live-readiness-final.md.
- [x] WARP•R00T README/WARP•R00T surface refresh [MINOR] MERGED #1412. Added `Engineering: Live Ready` badge + "Operating Posture" section (PAPER-only production / LIVE-ready engineering + 5 activation-guard names + link to LIVE_READINESS.md); WARP•R00T added to System Architecture diagram + Authority Chain table; Branch Naming section documents `WARP/{feature}` + `WARP/ROOT/{feature}` with explicit ban on auto-generated `claude/*` branches. Doc-only — README.md changes; no code touched.
- [x] WARP•R00T public-ready audit [MAJOR/FOUNDATION] — WARP/ROOT/public-ready-hardening. Paper-safe core verified; privacy-policy.md fixed. Report: reports/forge/public-ready-hardening.md.
- [x] H2 — inbound rate limiting / abuse control for public API + bot surfaces [STANDARD] — DELIVERED WARP/ROOT/api-rate-limit. RateLimitMiddleware (per-IP sliding window, 120rpm/60s, 429+Retry-After, health/webhook exempt); 6 tests; suite 1798 pass. Report: reports/forge/api-rate-limit.md.
- [x] H1 — ops auth hardening: token-out-of-URL via cookie session (api/ops.py) [MAJOR — SENTINEL] — DELIVERED WARP/ROOT/ops-auth-cookie. POST /ops/login → HttpOnly+Secure+SameSite=Lax cookie (HMAC of OPS_SECRET); GET gated to login form when unauthed; mutators accept cookie/header/legacy-token (no lockout); rotation via OPS_SECRET change. 48 ops tests pass; suite 1808. SENTINEL gate recommended before merge. (Per-operator named accounts not in scope — single shared secret retained.)
- [x] M1 — enable RLS on the last remaining public table [MAJOR-adjacent]. DONE — verified 2026-05-27: 43/43 public tables rls_enabled=true (Supabase list_tables); 0 rls_disabled_in_public advisor errors. Closed by migration 046 + later migs (incl. 055 scan_runs); no new migration needed.
- [x] M3 — check_alchemy_ws full WS handshake (monitoring/health.py) [STANDARD] — DONE WARP/ROOT/alchemy-ws-handshake. Real WS handshake + eth_blockNumber probe replaces TCP-only check; fails on broken WS. 4 hermetic tests; test_health.py 42 pass. Report: reports/forge/alchemy-ws-handshake.md.
- [x] C1 — wire on-chain capital movement (withdraw/redeem/sweep) [MAJOR]. CODE TRUTH (corrected 2026-06-01, WARP/ROOT/risk-path-hardening): on-chain transfer is IMPLEMENTED — wallet/withdrawals.py _attempt_onchain_transfer() gated behind EXECUTION_PATH_VALIDATED (returns None / defers when guard off); transfer_usdc + sweep_usdc_to_master + submit_live_redemption all wired + SENTINEL-approved (94/100, PRs #1402/#1403/#1408). Zero NotImplementedError in the trading/wallet/execution path. The earlier "wallet/withdrawals.py:158 raises NotImplementedError" note was STALE drift. Live activation of these paths remains an OWNER operational decision (fund master wallet + set guards), not a code gap.

## Active — Pre-Public LIVE-Readiness Campaign (owner authorised 2026-06-01)

> Scope = Candle + Weather + Copy Trade all LIVE. PAPER stays the new-user default. LIVE flip stays OWNER-ONLY.

- [ ] Lane 1 WARP/ROOT/risk-path-hardening [MAJOR → SENTINEL] PR open — C-1 crash-recovery resume_safety_check (gate steps 5/6/7/8/15; abandon-on-breach), C-2 weather routable at gate step 4, MED-2 boot registry↔availability guard. 11 new tests + 2206 suite pass. Report: reports/forge/risk-path-hardening.md.
- [ ] Lane 2 C-5/C-6 — reconcile daily-loss + exposure dual caps so per-profile LIVE limits aren't shadowed by the −$50 / 0.60 settings caps [STANDARD].
- [ ] Lane 3 C-3 — concurrency-cap policy: MAX_CONCURRENT_TRADES=5 is dead while profiles use 5/12/20 [STANDARD, WARP🔹CMD decision].
- [ ] Lane 4 C-4 — decompose signal_scan_job._process_candidate (~600 lines) into composable pipeline-step gates [STANDARD].
- [ ] Lane 5 LIVE live-fire validation — USE_REAL_CLOB=True end-to-end on a small cap, real CLOB order, then flip EXECUTION_PATH_VALIDATED [MAJOR, owner-gated + SENTINEL].

- [x] WARP-TDC — Trade diversity + concurrency [MAJOR] — MERGED (verified in main 2026-05-26: signal_evaluator._diversify_order present; PROFILES max_concurrent = 5/12/20, custom 12). Fixed beta #1 "same ~5 trades": (A) _diversify_order orders each user's candidates by sha1(user_id:market_id); (B) caps raised 3/5/5 -> 5/12/20, fixed fences (Kelly 0.25 / 10% pos / -$2k / 8% dd / 40% exposure) untouched. Lane 1 (categories) + Lane 3 (edge model) also in main.
- [x] LANE-1 — Category mapping fix [STANDARD] — integrations/polymarket.py: new get_events_with_markets() fetches Gamma /events endpoint + annotates each market dict with category from event tags (e.g. "crypto finance sports"); signal_scan_job._fetch_markets_for_lib_strategies() now calls get_events_with_markets() instead of get_markets(); _filter_markets_by_category() unchanged — now works correctly because category field is populated. 14 new hermetic tests in test_category_mapping.py. py_compile clean. Report: projects/polymarket/crusaderbot/reports/forge/category-mapping.md. STANDARD, WARP🔹CMD review.
- [x] LANE-3 — Edge-model momentum fix [STANDARD] — config.py SCANNER_EDGE_MIN_PRICE 0.05->0.15, SCANNER_EDGE_MAX_PRICE 0.95->0.85; market_signal_scanner.py edge formula replaced: abs(yes_p-0.5) -> max(|1d_change|,|1h_change|×1.5) (eliminates systematic longshot bias); side logic replaced: mean-reversion -> momentum-following (YES if recent_change≥0); 5 existing tests updated + 5 new tests (longshot rejection, near-fair momentum pass, 1h>1d preference). py_compile clean. Report: projects/polymarket/crusaderbot/reports/forge/edge-model-momentum.md. STANDARD, WARP🔹CMD review.
- [x] WARP-RMS — Real-market settlement fix [MAJOR] — MERGED PR #1314 + deployed; feed migration done (6 users Demo->Live). FIX1 polymarket.get_market() 422-on-hex-conditionId (path segment -> ?conditionId= query) that silently blocked ALL resolution/settlement -> slots never freed; FIX2 scanner edge-finder now publishes real markets to the LIVE feed with is_demo=FALSE by default (SCANNER_DEMO_FEED_ENABLED gate for tests/dev); FIX3 pending_settlement status (never flat-close on expiry, counted in exposure, settles on official close). 18+13+62 tests green. Optional owner action: manual void/clear of leftover demo positions.
- [x] WARP-61 — WebTrader confluence_scalper exposure (issue #1269) [STANDARD] — MERGED 7cbd8b814533
- [x] WARP-60 — ConfluenceScalperStrategy (issue #1267) [STANDARD] — MERGED b3ec4b7d4930
- [x] WARP-59 — Copy Wallet end-to-end bridge: copy_targets → copy_trade_tasks (Issue #1265) [STANDARD] — DELIVERED WARP/warp59-copy-wallet-e2e-bridge 2026-05-21 (MVP write path realigned to canonical execution table read by services/copy_trade/monitor.py).
- [x] WARP-58 — Fix domain/signal/copy_trade.py copy_targets schema mismatch (Issue #1263) [STANDARD] — DELIVERED WARP/warp58-copy-trade-schema-fix 2026-05-21 (closes WARP-57 SENTINEL Round-1 read-path drift).
- [x] WARP-57 — Telegram UX MVP v1 Rebuild (Issue #1260) [MAJOR] — MERGED c6ae44b18572. SENTINEL CONDITIONAL APPROVED 92/100.

---

## Deferred / NOT NOW

❌ live trading activation
❌ fancy analytics expansion
❌ dashboard redesign
❌ monetization / premium expansion
❌ new feature creep until PAPER runtime is trusted
- [x] WARP-46 — Runtime Spine Validation (Issue #1243)
- [x] WARP-62 — P0: remove threading.Lock from registry.py → eager module-level init (issue #1273) [STANDARD] — DELIVERED WARP/warp62-63-fix 2026-05-22
- [x] WARP-63 — P1: migrate CopyTradeStrategy.scan() from copy_targets → copy_trade_tasks (issue #1274) [STANDARD] — DELIVERED WARP/warp62-63-fix 2026-05-22
- [x] WARP-64 — P0: fix CI pytest failures in test_warp59_copy_wallet_bridge.py (issue #1277) [STANDARD] — DELIVERED WARP/warp64-ci-fix 2026-05-22
- [x] WARP-65 — P1: fix Telegram UX persistent keyboard + bot status + strategy label (issue #1278) [STANDARD] — DELIVERED WARP/warp65-telegram-ux-fix 2026-05-22
- [x] WARP-66 — Telegram UX polish (issue #1282) [STANDARD] — MERGED ab6f397f2741
- [x] SENTINEL re-audit post WARP-62+63 (issue #1276) — APPROVED 96/100 — MERGED d42b7e915356
- [x] WARP-67 — Telegram UX final clean (issue #1284) [STANDARD] — MERGED 2989b7c6e788
- [x] WARP-68 — Structured card format + positions pagination (issue #1286) [STANDARD] — MERGED b7355541d496
- [x] WARP-69 — Full structured card format all 66 render functions (issue #1288) [STANDARD] — MERGED b50ef1a2ce86
- [x] WARP-70 — Dynamic Auto Trade capital = balance × risk fraction (issue #1290) [MINOR] — DELIVERED WARP/warp70-dynamic-capital 2026-05-22
- [x] WARP-71 — Premium terminal UI HTML parse mode [STANDARD] — MERGED e443c212c1e7
- [x] WARP-72 — Fix phantom dot + do_start capital from _read_state [MINOR] — 93d5709c0c5c
- [x] WARP-73 — Phantom dot fix + clean Telegram HTML format [MINOR hotfix] — 5364eb97 + 7bb7a69a + c8de0a5e
- [x] SENTINEL system audit pre-handoff — F-CRIT-1 RESOLVED, bot/ui/__init__.py fix — MERGED fa1bd2537650
- [x] WARP-1296 — RLS enable 42 tables anon-key lockout [MAJOR] SENTINEL 98/100 — MERGED 82f08af2a27b
- [x] F-HIGH-2 — vendor lib/ into crusaderbot package, fix prod strategy load [MAJOR] SENTINEL 99/100 — MERGED e235fa294823

---

## PLAYBOOK — Sports Strategy Router (epic, additive)

Sports equivalent of SMART STRIKE. Autonomous router → highest-EV sports module.
Blueprint: docs/blueprint/playbook.md. Linear: WARP-53.

- [x] Phase 1 FOUNDATION (WARP/ROOT/playbook-sports-engine) — domain/playbook/ package (market quality + native signals + precedence router + Closing Edge module + stubs), PlaybookStrategy wired through registry + STRATEGY_AVAILABILITY + presets + backend + Telegram + WebTrader card; paper-only, deny-by-default dispatch; 24 tests + full suite 2371 pass. MAJOR → SENTINEL.
- [ ] WARP•SENTINEL MAJOR validation of Phase 1
- [x] Phase 2a — live scan-loop dispatch (WARP/ROOT/playbook-live-dispatch) — _PRESET_ALLOWED + _DOMAIN_STRATEGY_NAMES + Phase-B4 dispatch gated by PLAYBOOK_STRATEGY_ENABLED, sports-market snapshot fetch (Gamma sports markets ≤2h + CLOB books), Gamma-consensus fair_price, preset re-enabled. PAPER; full suite 2410 pass. MAJOR → SENTINEL.
- [x] Phase 2b — Sharp Money native source (WARP/ROOT/playbook-sharp-money) — MERGED #1577 (squash 183ff6c), WARP•SENTINEL APPROVED 98/100. domain/playbook/sharp_flow.py fetch_sharp_flows (batched DB read: leaderboard_stats top-tier wallets ⨝ heisenberg_realtime_trades 24h → signed/total via outcome×action), SharpMoneyModule.evaluate live (TTL>24h ∧ flow>=$500 ∧ conf>=0.20), flow-gated far band, applied_tp_pct/sl_pct stamping. 4 bot findings fixed in-lane. PAPER; risk/execution/Kelly/live-guard untouched.
- [ ] Phase 2c — backtest framework (walk-forward + leakage/overfit detection; shared blocker)
  - [x] 2c-1 Monte Carlo robustness (WARP/ROOT/playbook-robustness-mc) — domain/research/{monte_carlo,robustness}.py bootstrap simulator + ROBUST/FRAGILE/UNTRADEABLE/INSUFFICIENT_DATA classifier + live_eligible gate (UNTRADEABLE-only block) + migration 079 module_robustness. Pure analytics, live path untouched. 19 tests pass. MAJOR/FOUNDATION. Operator: apply migration 079.
  - [ ] 2c-2 per-scan book/price snapshot persistence (walk-forward substrate)
  - [ ] 2c-1b wire live_eligible into gate behind ROBUSTNESS_GATE_ENABLED + scheduled classify_modules refresh
  - [ ] 2c-3 walk-forward replay engine (consumes 2c-2 data; §12.1 metrics + bias detection)
- [x] Phase 2d — Injury Alpha module + injury/news feed adapter (WARP/ROOT/playbook-feed-adapters) — InjuryAlphaModule full claim logic (injury_present ∧ TTL>1h ∧ repriced<50% ∧ conf≥0.20 → side from signed news_injury_reading; TP0.30/SL0.15) + EspnInjuryFeed (free public endpoint, no key) behind the SportsFeed Protocol; PLAYBOOK_INJURY_FEED_ENABLED (default OFF). Paper-only; MAJOR → SENTINEL.
- [x] Phase 2e — Public Fade module + public-flow feed adapter (WARP/ROOT/playbook-feed-adapters) — PublicFadeModule full claim logic (public_pct≥0.65 ∧ overreaction≥0.10 vs market-implied ∧ TTL>30min → fade to opposite side) + public_flow_reading + OddsApiFeed soft-vs-sharp public-lean proxy + no-vig consensus model prob (free tier, ODDS_API_KEY env-only); PLAYBOOK_PUBLIC_FEED_ENABLED (default OFF). build_sports_feed → NullFeed until a market→FeedTarget resolver is supplied. Paper-only; MAJOR → SENTINEL.
- [ ] Phase 3 — Line Momentum + Liquidity Hunt + CLOB WebSocket + Monte-Carlo robustness classifier
