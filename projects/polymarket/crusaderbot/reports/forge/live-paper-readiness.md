# live-paper-readiness — WARP•R00T system audit + hardening lane

Branch: WARP/root-live-paper-readiness
Role: WARP•R00T (owner-assigned)
Date: 2026-06-11 02:46 Asia/Jakarta

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : boot-time live-execution readiness validation in main.py lifespan; fly.toml machine-size sync; LiveActivationModal gate-label contract; dashboard force-redeem error surfacing
Not in Scope      : execution/risk/strategy logic, ENABLE_LIVE_TRADING + 5 activation guards, USE_* flag defaults, kill switch, migrations, sidecar crate, per-user resolver semantics, Telegram bot
Suggested Next    : owner activation sequence (already documented in NEXT PRIORITY) — backfill_deposit_wallets(), sidecar + per-user flags, 5-guard flip

## 1. What was built

Owner directive: "make crusaderbot backend, frontend UI/UX ready 100% for polymarket trade live and paper" (WARP•R00T, full merge authority). Full-surface audit dispatched (backend execution spine + live gates + wallet; frontend live/paper UX + API contracts), every agent finding re-verified against code truth, and the four REAL defects fixed:

1. **Boot-time live-execution readiness validation** (`main._validate_live_execution_readiness`, wired into lifespan after CLOB credential derivation). Three checks, all loud-but-non-fatal (same posture as the existing creds check — paper boots must never be blocked):
   - `USE_RUST_SIDECAR=true` but binary missing/non-executable at `RUST_SIDECAR_PATH` → ERROR at boot (was: detected only when the first live order spawns the subprocess, after the order claim, worst case 45s timeout inside exit_watcher).
   - `USE_PER_USER_EXECUTION=true` with `wallets.polymarket_deposit_wallet IS NULL` rows → ERROR naming `backfill_deposit_wallets()` + row count (was: N per-order refusals; a missed backfill is the most likely operator error in the activation sequence).
   - `ENABLE_LIVE_TRADING=true` + `AUTO_REDEEM_ENABLED=true` → WARNING (blueprint §12 default-OFF reminder; env var remains the explicit operator enable — deliberately NOT a hard fail).
2. **fly.toml `[[vm]]` sync to `shared-cpu-4x` / 2GB** — the running machines were scaled via the Fly dashboard 2026-06-10; bot PR #1744 recorded this but its generated TOML is INVALID (duplicate `http_service.concurrency` inline key vs existing section table — `tomllib` refuses to parse) and would have broken/abandoned the next deploy, while leaving main as-is would silently DOWNSIZE the trading machines to 1GB on the next merge. Fixed by updating the existing `[[vm]]` block in place; #1744 superseded + closed.
3. **LiveActivationModal gate labels rewired to the real backend contract** — all seven `GATE_LABELS` keys (`funded`, `wallet`, `preset`, `tos`, `no_kill`, `guards`, `risk_profile`) matched NOTHING the backend sends; `failed_gates` carries `live_checklist.GATE_ORDER` names (`active_subaccount_with_deposit`, `strategy_configured`, `risk_profile_configured`, `two_factor_setup_complete`, `operator_allowlist_approved` + 3 operator guards). Users blocked from going live saw raw snake_case keys for the most safety-critical flow in the product. All 8 real gates now have actionable labels.
4. **Dashboard force-redeem failures surfaced** — `onForceRedeem` swallowed every error (`catch { /* surfaced via refresh */ }` — it wasn't); a failed redeem (409 not-won-yet / 500 decrypt) left the user staring at an unchanged card. Now renders an inline alert banner with the backend reason, cleared on retry.
5. **Latent test defect fixed** (found by this lane's new tests, root-caused, not masked): `test_correlated_majors_limit.py::test_gate_effective_count_is_max_of_sources` passed a stdlib `logging.getLogger` into `_gate_correlated_majors`, whose block path logs structlog-style kwargs (production passes `logger.bind(...)` — structlog — so PRODUCTION IS CORRECT). The stdlib logger only "worked" while the global level suppressed INFO; any test importing `main` (which configures logging) detonated it with `TypeError: Logger._log() got an unexpected keyword argument`. Test now uses `structlog.get_logger`, matching the gate's de facto contract.

## 2. Current system architecture (relevant slice)

- Lifespan boot order: sentry → env validation → pool/migrations/cache → strategies (fail-fast) → CLOB creds (loud, non-fatal) → **NEW: live-execution readiness validation (loud, non-fatal)** → SSE listener → Telegram → scheduler → guards audit.
- Live order path unchanged: router → risk gate → live.execute → (USE_PER_USER_EXECUTION ? resolve_user_clob_client w/ wallet-identity assert : get_clob_client) → (USE_RUST_SIDECAR ? RustSidecarClient : v2/pysdk/legacy). The new boot check only OBSERVES this config; it gates nothing.
- WebTrader live activation: GET /api/web/live/status → {operator_guards_open, checklist_passed, failed_gates[]} → LiveActivationModal (preview → cap → typed-confirm) → POST /live/enable. Gate-name contract now pinned by comment to domain/activation/live_checklist.py GATE_ORDER.

## 3. Files created / modified

- projects/polymarket/crusaderbot/main.py — `_validate_live_execution_readiness()` + lifespan call
- projects/polymarket/crusaderbot/fly.toml — `[[vm]]` shared-cpu-2x/1GB → shared-cpu-4x/2GB (dashboard-scale sync, supersedes #1744)
- projects/polymarket/crusaderbot/webtrader/frontend/src/components/LiveActivationModal.tsx — GATE_LABELS rewritten to real gate names
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx — redeemError state + alert banner in Awaiting Redeem strip
- projects/polymarket/crusaderbot/tests/test_startup_live_readiness.py — 9 hermetic tests (NEW)
- projects/polymarket/crusaderbot/tests/test_correlated_majors_limit.py — latent stdlib-logger defect fixed (structlog, matches production)
- projects/polymarket/crusaderbot/reports/forge/live-paper-readiness.md — this report (NEW)
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md, state/CHANGELOG.md — state sync

## 4. What is working

- Full suite GREEN before changes (3386 passed / 10 skipped) and after changes (3394 passed / 11 skipped — +8 new passing, +1 env-conditional skip documented in-test).
- ruff clean on touched Python; frontend `tsc --noEmit` clean; `vite build` clean (6.06s).
- fly.toml parses (`tomllib` round-trip asserted) — #1744's version provably does not.
- Audit verdict re-verified against code truth: PAPER path fully working end-to-end; LIVE code-side complete (per-user lane SENTINEL-approved 98/100 #1751, sidecar broker proof PASS run #7) — remaining go-live items are the owner activation sequence, not code.

## 5. Known issues

- Audit findings VERIFIED-AS-DESIGNED (no action): paper-mode withdrawals are an intentional admin-reviewed flow (real deposited USDC must stay withdrawable while trading_mode=paper); ledger pagination offset advances by server count deliberately (comment in code); SettingsPage already self-retries via 30s poll; HeroCard pnl flash is self-clearing; 2FA card optimistic state matches its type.
- Deferred (LOW, not lane-worthy): LiveActivationModal does not live-poll operator-guard state while open (re-open refreshes); `estimated_fill` on close preview uses position.current_price which can be a tick stale (actual fill correct).
- Owner activation sequence unchanged and still owner-gated (see NEXT PRIORITY in PROJECT_STATE.md).

## 6. What is next

- Owner runs the documented activation sequence: (a) `backfill_deposit_wallets()` on prod, (b) `USE_RUST_SIDECAR=true` + `POLYMARKET_SIGNATURE_TYPE=3`, (c) `USE_PER_USER_EXECUTION=true`, (d) 5-guard flip ending in `ENABLE_LIVE_TRADING`. The new boot validation will confirm (a)–(c) loudly on the deploy that flips them.
- No SENTINEL required: WARP•R00T full-bypass merge (owner directive 2026-06-05); invariants untouched (risk constants / Kelly 0.25 / live guard / asyncio / no secrets).
