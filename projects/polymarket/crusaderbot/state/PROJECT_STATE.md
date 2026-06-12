Last Updated : 2026-06-12 20:31
Status       : realtime-deposit-withdraw-engine R00T-FINISHED MERGED #1781; all live-path code merged + per-user execution proven on real CLOB; owner-ops only remain for go-live (deposit USDC.e → gas POL → guards); WARP-92/91/86-0b BUILT + HELD for SENTINEL.

[COMPLETED]
- realtime-deposit-withdraw-engine MERGED #1781 — FORGE build + WARP•R00T finishing pass: migration 095, deposit lifecycle_state truth, deferred sweep when guards off, withdrawal lock/submit/confirm/refund/manual_review lifecycle; report: reports/forge/realtime-deposit-withdraw-engine.md
- builder-key-preference / WARP/root-builder-key-preference MERGED #1778 + Fly deployed: sdk_api_key() prefers BuilderApiKey > RelayerApiKey (relayer key address-bound — proved in prod); owner re-tapped backfill → 6/6 deposit wallets filled; per-user funder column COMPLETE
- admin-live-truth / WARP/root-admin-live-truth MERGED #1771 + deployed: admin users roster mode-scoped per row, backfill button reports Safes summary, RELAYER_API_KEY wired into all 4 AsyncSecureClient builds; owner armed custody 6/6 safe_address
- correlated-majors-db-cap / WARP/root-correlated-majors-db-cap MERGED: DB-count correlated guard survives restarts; CORRELATED_MAJORS_SAME_DIR_LIMIT 2→1 (owner directive); 29 tests; report: reports/forge/correlated-majors-db-cap.md
- sidecar-clob-url / WARP/root-sidecar-clob-url PROOF_RESULT=PASS run #7 27290744773-1: Rust sidecar DEFAULT_CLOB_URL fix; live order placed from Fly nrt (sig_type=3, allow_fills=false, cancel confirmed); report: reports/forge/sidecar-clob-url.md
- WARP•R00T overnight full-surface readiness Phase 0 matrix #1754 + Lane A live-notify-parity #1755 (SENTINEL 98/100) + Lane B telegram-live-truth #1756 ALL MERGED; report: reports/forge/overnight-handoff.md
- per-user-execution-wiring / WARP/root-per-user-execution-wiring MERGED: WalletIdentityMismatch on wallet drift; resolved_wallet == wallets.polymarket_deposit_wallet asserted before every broker call; USE_PER_USER_EXECUTION flag (default False); 11 tests; report: reports/forge/per-user-execution-wiring.md
- self-serve-2fa / WARP/root-self-serve-2fa MERGED: RFC 6238 TOTP via pyotp, Fernet-encrypted at rest, gate 7 (two_factor_setup_complete) wired end-to-end, 4 endpoints /api/web/2fa/*, TwoFactorSetupCard.tsx; 13 tests; report: reports/forge/self-serve-2fa.md
- live-trade-readiness-audit / WARP/root-live-trade-readiness-audit MERGED #1734 (f4942eeb): BuilderRelayerUnavailable→PreflightError refund fix + per-user CLOB zero-address fail-fast; 478 wallet+clob regression pass; report: reports/forge/live-trade-readiness-audit.md
- WARP-74 staging proof ALL 5 CASES GREEN run #16 (sha 75cb1f10, PROOF_NONCE=27028306156-1, allow_fills=false, Fly nrt) — CLOB v2 pysdk proven at broker boundary; reports: reports/forge/case1-test-poll.md + staging-harness-integrity.md

[IN PROGRESS]
- WARP-72 shadow observation: factor_vector dataset accruing in paper (settled rows growing); need ~50-100 settled per asset/TF before Phase 2 weight derivation
- WARP-86 Phase 0b (AUTO risk profile), WARP-91 (stale-queue-resume-routing), WARP-92 (live-trade-activation) — BUILT + HELD on their branches pending WARP•SENTINEL MAJOR validation
- sigma calibration shadow: adaptive-vs-static NLL accruing on each deploy; converge + beat static → gated live swap lane (SCORER_ACTIVE=False, ORCHESTRATOR_ACTIVE=False throughout)

[NOT STARTED]
- Wire share_trade_kb into trade close call sites when PNL > 0 — surface ready, wiring deferred
- Referral payout activation — separate lane, WARP🔹CMD decision required
- Fee collection activation — separate lane, WARP🔹CMD decision required
- @require_access_tier('PREMIUM') on trading command handlers — separate lane, deferred

[NEXT PRIORITY]
- OWNER-OPS go-live sequence (no code blocker): (1) deposit USDC.e to your deposit wallet (WebTrader → Wallet), (2) send ~2-5 POL to master pool address (Admin → pool balance) for sweep + withdrawal gas, (3) re-arm Auto-Trade; also rotate the pre-redaction Alchemy key in historical Fly logs
- WARP•SENTINEL validation required: WARP-92 (live-trade-activation, MAJOR — global live gate), WARP-91 (stale-queue-resume-routing, MAJOR), WARP-86 Phase 0b (AUTO risk profile, MAJOR) — all BUILT + HELD
- WARP-97 CLOB v2 cutover: operator registers staging wallet at Polymarket → re-dispatch case3+2+4 with use_clob_v2=1; on GREEN set USE_CLOB_V2=1 in prod + retirement lane (delete sdk_client.py/adapter.py v1 + drop old libs)

[KNOWN ISSUES]
- EIP-7702 deposit wallet L1 auth wall: py-clob-client-v2 cannot place orders for migrated Magic/email accounts (upstream #70 OPEN; no public working impl); OWNER PATHS: (1) POLY_PROXY sig-1 wallet, (2) Rust-SDK sidecar lane, (3) wait for upstream fix
- WARP-97 v2 staging proof operator-blocked: staging wallet needs Polymarket registration before case3/2/4 can pass with USE_CLOB_V2=1
- Deposit watcher: Alchemy key in historical Fly logs pre-redaction — OWNER should rotate; catch-up to head ~4-5h at Free-tier CU budget after key rotation
- Smart Strike LIVE slippage-of-edge tier OFF by default (cap-only, SMART_STRIKE_REQUIRE_MEASURED_EDGE=False); real-edge path built on WARP/smart-strike-real-edge (HELD, PR open)
- late_entry_v3 OOS edge UNPROVEN: SCAN_SNAPSHOT_ENABLED OFF; no-redeploy runtime toggle built (WARP/scan-snapshot-runtime-config) — awaits WARP🔹CMD greenlight to flip ON in PAPER
- 15m LIVE per-cell caps are provisional mirrors of 5m (btc $500 / eth $100 / sol $100) — pending CMD confirm + live-fill re-tune before any 15m LIVE trade
- Weather + Playbook zero-opens: opportunistic edge starvation (not a gate/bug); strategy_scan_observations accruing (mig 086); playbook feed modules dark on NullFeed default
- Cross-surface display-parity divergence: equity/P&L/unrealized-mark computed differently on WebTrader vs Telegram — shared computation lane deferred
- crusaderbot-logo.png not in repo — WebTrader logo renders broken until PNG committed to webtrader/frontend/public/
- WARP-57 MEDIUM-4 deferred: production scanner (services/copy_trade/monitor.py) reads copy_trade_tasks but MVP writes copy_targets — end-to-end mirror inactive until swap lane
