# CrusaderBot — Full-Surface Live/Paper Readiness Matrix

Role: WARP•R00T (owner-assigned overnight readiness program)
Branch: WARP/root-readiness-matrix
Generated: 2026-06-11 05:10 Asia/Jakarta
Verification environment: fresh container, full dependency install, repo at origin/main c33a17f (#1753)

Code wins over reports. Every row below was re-verified against code in this session
(4 parallel code audits + direct cross-checks), not copied from prior state.

Session-verified evidence baseline:

- Full test suite: **3402 passed / 11 skipped** (56s, this container) — exact match to the documented #1753 baseline
- Strategy-path subset (candle_auto / late_entry / fast_track_a / signal_scan): **271 passed**
- Frontend: `tsc --noEmit` clean + `vite build` clean (dist built, this container)
- SDK currency (PyPI/crates.io, checked 2026-06-11): `py-clob-client-v2` 1.0.1 = latest; rust `polymarket_client_sdk_v2` 0.6.0-canary.1 = latest; legacy `py-clob-client` 0.34.6 = latest; `polymarket-client` pinned 0.1.0b4 vs latest 0.1.0b7 (deliberate validated pin — see Cross-cutting)

---

## Matrix — surface × {paper, live}

| # | Surface × Mode | Status | Evidence (file:line / proof) | Blocker | Tier | Proposed lane |
|---|---|---|---|---|---|---|
| 1 | Backend/integration × PAPER | READY | Full suite 3402/11 green this container; factory precedence sidecar>v2>pysdk>legacy `integrations/clob/__init__.py:405-553`; paper isolation via MockClobClient (USE_REAL_CLOB=False never opens sockets, `integrations/clob/ws.py` guard); breaker+limiter on all backends | none | — | none |
| 2 | Backend/integration × LIVE | READY (code) / PARKED (ops) | Rust sidecar Poly1271 broker proof PASS (staging run #7, PROJECT_STATE #1749); per-user execution wiring SENTINEL APPROVED 98/100 (#1751); L1 EIP-712 + L2 HMAC + builder headers `integrations/clob/auth.py:71-269`; per-user wallet-identity assertion `domain/execution/per_user_clob.py:70-136`; boot validation `main.py:53-123` | Owner ops only: POLYGON_RPC_URL Fly secret fix, `backfill_deposit_wallets()` run, sidecar+per-user flag flips, guard flips | — | PARKED for Boss (stop condition 1 — no unattended activation) |
| 3 | Strategy execution × PAPER | READY | candle_auto preset `domain/preset/presets.py:108-119` → late_entry_v3 `domain/strategy/strategies/late_entry_v3.py:595-817` → scan loop `services/signal_scan/signal_scan_job.py:160-167,2669+` → gate → paper engine → exit watcher; 271 targeted tests green; gate hot-path ZERO per-candidate DB reads (WARP-89) `domain/risk/gate.py:91-102` + preload `signal_scan_job.py:805,812`; signals not DB-persisted (stdout/Sentry; deliberate factor_vectors shadow UPSERT only, fail-soft `late_entry_v3.py:323-362`) | none | — | none |
| 4 | Strategy execution × LIVE | READY | strategy_metadata persisted in BOTH engines (`domain/execution/live.py:392-400` = `domain/execution/paper.py:62-71`) so force-exit metadata survives LIVE; exits strategy/preset-owned not free-form (`late_entry_v3.py:606-607` default_tp_sl, force_exit_at_rem_sec `:776-794`); LIVE-only slippage-of-edge tier step 14b `gate.py:714-791`; per-user live cap step 15 `gate.py:793-819`; risk constants intact (Kelly 0.25 clamp `gate.py:654-663`, caps `domain/risk/constants.py:4-8`) | none (code) | — | none |
| 5 | Frontend web terminal × PAPER | READY | tsc+vite build clean this container; mode pill TopBar.tsx:138-149; positions/controls DashboardPage + PortfolioPage with loading/error/empty states; SSE handshake token `sse.ts:46` ↔ `router.py:2156-2171`; full api.ts ↔ `webtrader/backend/router.py` contract verified endpoint-by-endpoint (audit table, 24 routes matched) | none | — | none |
| 6 | Frontend web terminal × LIVE | READY | LiveActivationModal GATE_LABELS = backend GATE_ORDER 8/8 exact (`LiveActivationModal.tsx:23-32` ↔ `domain/activation/live_checklist.py:39-48`); 2FA TwoFactorSetupCard 3-state ↔ `/api/web/2fa/*` `router.py:2723-2810`; live enable/disable `router.py:2578,2662`; force-redeem error surfacing DashboardPage:352-384; live cap + open-live-exposure display | none | — | none |
| 7 | Telegram bot × PAPER | READY | Command surface + state-aware keyboard `bot/dispatcher.py:214-301`, `bot/keyboards/main_menu.py:20-58`; /enable_live 3-step gate `bot/handlers/live_gate.py:78-334`; emergency 6-action menu `bot/handlers/emergency.py:43-200`; paper entry notifications `domain/execution/paper.py:13-16,89` | none | — | none |
| 8 | Telegram bot × LIVE | GAP | (a) LIVE entry user-visibility missing: `live.py` has NO TradeNotifier.notify_entry and NO portfolio_snapshots write (paper has both `paper.py:89,147`; live only operator-notify on ambiguous submit `live.py:353`); close path is mode-agnostic (`domain/execution/exit_watcher.py:689` emits position.closed → SSE + notifier) so the gap is entry-side; (b) stale 2FA truth: `live_checklist.py:166` docstring claims "Self-serve 2FA infrastructure does not yet exist" — false since #1737 (web TwoFactorSetupCard + `/api/web/2fa/*`); gate-7 fix hint does not point users at the shipped web flow; (c) `/wallet` command unregistered (deposit screen reachable via menu route only) | none — both closable in-repo | (a) MAJOR; (b)+(c) STANDARD | (a) WARP/root-live-notify-parity; (b)+(c) WARP/root-telegram-live-truth |
| 9 | Deposit/withdrawal (non-custodial) × PAPER | READY | Deposit = ledger credit on watched-address transfer (watcher `scheduler.py:216-323`, 3-address model EOA+Safe+polymarket_deposit_wallet `_build_watched_addresses`); withdrawal request → admin-reviewed manual approval (intentional) `bot/handlers/wallet.py:179-330`, refund-on-failure proven (#1734 BuilderRelayerUnavailable extends PreflightError) | none | — | none |
| 10 | Deposit/withdrawal (non-custodial) × LIVE | READY (code) / PARKED (mainnet) | NON-CUSTODIAL BOUNDARY COMPLIANT: zero private-key display, zero seed-phrase input, zero raw signing in any user surface (vault encrypts at generation `wallet/vault.py:28-55`; decrypt scoped to execution layer `:69-78`; frontend grep: zero key/seed/mnemonic surfaces); deposit-wallet persistence + identity assertion (#1736/#1751); watcher rescue (failure escalation + 50k-block lookback) #1753; on-chain transfer/sweep/redeem wired + SENTINEL 94/100 (#1402/#1403/#1408), gated by EXECUTION_PATH_VALIDATED; live redeem path EXISTS (`services/redeem/redeem_router.py` submit_live_redemption — earlier "dormant" audit note was wrong, re-verified) | Mainnet execution = real fund movement | — | PARKED for Boss (HARD STOP — build+dry-run only) |

---

## Cross-cutting findings

### Polymarket client/SDK currency (directive item)

| Component | Pinned | Latest | Verdict |
|---|---|---|---|
| py-clob-client-v2 (active v2 path) | >=1.0.1 (1.0.1 installed) | 1.0.1 | CURRENT |
| Rust polymarket_client_sdk_v2 (sidecar — the only Poly1271 client) | =0.6.0-canary.1 | 0.6.0-canary.1 | CURRENT (exact latest) |
| py-clob-client (legacy fallback) | unpinned (0.34.6) | 0.34.6 | CURRENT |
| polymarket-client (AsyncSecureClient cred derivation) | ==0.1.0b4 | 0.1.0b7 | DELIBERATE PIN — pyproject comment: "bump only with a fresh staging proof". Upgrade requires real-creds staging run (secrets live in Fly, not this environment) → documented, NOT a lane this run |

### Order lifecycle coverage (directive item)

GTC + FOK + FAK supported on sidecar/v2/pysdk backends (`rust_sidecar.py:43`, `v2_client.py:65`); GTD refused pre-spawn by the sidecar (pinned by test) and unsupported on v2; post-only and batch order placement are NOT used by any strategy path (late_entry_v3 enters GTC; complete-set arb enters paired FOK). Verdict: full coverage of every order type the system actually places; GTD/post-only/batch documented as not-required capability, not a gap.

### WebSocket / market data (directive item)

User-channel WS with reconnect/backoff/heartbeat `integrations/clob/ws.py:75-392` (hard-gated USE_REAL_CLOB); RTDS oracle WS for candle fair-value; REST orderbook/midpoint/price via MarketDataClient `integrations/clob/market_data.py:53-182` with breaker+limiter+heartbeat (`monitoring/clob_heartbeat.py`); Gamma events+markets `integrations/polymarket.py`. READY.

### CTF operations (directive item)

Redeem: wired end-to-end (redeem queue → `services/redeem/redeem_router.py` → submit_live_redemption with gas ceiling), auto-redeem instant/hourly workers, guarded by EXECUTION_PATH_VALIDATED. Neg-risk: read + threaded into order placement (`complete_set_exec.py:622-810`). Split/merge: not wired as standalone ops — complete-set entry/exit uses paired FOK orders + settlement redeem instead; no strategy requires raw split/merge. Verdict: READY for the capability set the system uses.

### Paper ↔ live parity (directive acceptance item)

- Router: single gate chain; live requires 8 conditions (`domain/execution/live.py:57-88` re-checked in-engine; router fallback semantics: pre-submit error → paper fallback, post-submit → refuse fallback + operator page `router.py:53-150`).
- Two-layer live gate intact: global ENABLE_LIVE_TRADING/operator toggle + per-user opt-in (trading_mode='live' + funded cap) `domain/execution/live_activation.py:46-84`. Users all paper-default (3-path INSERT invariant, tests/test_paper_default_invariant.py).
- Gate parity validator exists: `domain/execution/parity.py:53-180` (verdict must match between modes).
- Position lifecycle parity: strategy_metadata + tp/sl snapshots identical in both engines; close/exit events mode-agnostic.
- KNOWN ASYMMETRY (the one real parity gap): entry-side user visibility — paper notifies user + writes portfolio snapshot, live does neither → LANE WARP/root-live-notify-parity.

### Live arming posture

fly.toml [env] pins all 5 guards false (deploy-safe); runtime arming is owner-controlled via Fly secrets. Per-user live remains opt-in behind the 8-gate checklist; no user is live by default. UNCHANGED by this program.

---

## Lane plan (only from matrix gaps)

| Lane | Branch | Tier | Scope | Gate |
|---|---|---|---|---|
| A | WARP/root-live-notify-parity | MAJOR | live.execute(): fire-and-forget TradeNotifier.notify_entry + portfolio snapshot after successful submit (parity with paper.py:89,147); close_position snapshot parity; fail-soft, zero new awaits on the order-critical path before broker submit | inline WARP•SENTINEL → merge on PASS + CI green |
| B | WARP/root-telegram-live-truth | STANDARD | live_checklist.py gate-7 docstring + fix-hint truth sync (2FA shipped #1737, point users at WebTrader Settings); register /wallet command (deposit discoverability) | CI green + review |

Parked (Boss-gated, NOT lanes): POLYGON_RPC_URL secret fix; backfill_deposit_wallets(); sidecar+per-user+guard flips; any mainnet fund movement; polymarket-client b4→b7 bump (needs staging proof with Fly creds).
