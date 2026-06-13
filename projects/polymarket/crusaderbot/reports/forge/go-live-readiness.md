# WARP•R00T — CrusaderBot Polymarket Go-Live Readiness Audit + Operator Runbook

Role: WARP•R00T (owner-assigned)
Branch: warp/root-go-live-readiness
Date: 2026-06-13 Asia/Jakarta
Validation Tier: MINOR (audit + documentation + state sync — zero runtime code change)
Claim Level: FOUNDATION (read-only audit against code truth; no execution/integration code added)
Validation Target: live-trade execution path, risk gate, strategy engine, deposit enablement, activation surface — code-truth verification only
Not in Scope: flipping any activation guard, moving any real funds, placing any real CLOB order, enabling native USDC/USDT crediting, building the Bridge→pUSD→USDC.e settlement path, strategy-edge calibration
Suggested Next Step: owner executes the operator runbook (Section: GO-LIVE RUNBOOK) in production — guard sequence + sidecar wiring + funded micro-trade verification

---

## 1. What was built

Nothing in the runtime was changed. This lane is a code-truth readiness audit plus the
authoritative operator go-live runbook. The owner routed this WARP•R00T lane after a `/goal`
to "make CrusaderBot ready for live trade, audit + fix strategy, test live trade, ready
USDC.e/USDC/USDT deposits." The audit found the live-trade code is already production-grade
and conservatively gated; what remains between paper and live is owner-operational, upstream,
or a deliberate safety-deferred build — not a code bug fixable from a CI sandbox. The owner
confirmed the scope: deliver this audit + runbook, keep USDC.e-only deposits, treat the Rust
sidecar as the authoritative live order path, defer native USDC/USDT.

## 2. Current system architecture (verified against code truth)

Pipeline (locked): DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING.

Execution gating (fail-closed, paper by default):
- `domain/execution/router.py` — checks the GLOBAL live toggle (`is_global_live_enabled`,
  `domain/ops/global_live_gate.py`, fail-safe to paper) AND the per-call guard assertion
  BEFORE any live engine call. Any `LivePreSubmitError` → audited fallback to paper.
  `LivePostSubmitError` (order already on-chain) → does NOT paper-duplicate; re-raises and
  flips the user to paper for the next signal. Infra-degraded pre-submit failures page the
  operator distinctly from deliberate guard-off fallbacks.
- `domain/execution/live.py:assert_live_guards` — raises unless ALL of: `ENABLE_LIVE_TRADING`,
  `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED`,
  `SECURITY_HARDENING_VALIDATED`, `USE_REAL_CLOB`, plus `role=='admin'` and `trading_mode=='live'`.
  (Six env guards — one MORE than the legacy "5 guards" docs claim.)
- `live.execute()` — idempotent INSERT-before-submit (`orders.idempotency_key` ON CONFLICT),
  5% `SLIPPAGE_GUARD_PCT` pre-submission fence, `LIVE_MIN_ORDER_SHARES=5` fail-closed floor,
  CLOB tick_size/neg_risk fetched fresh (fail pre-submit on absence), pre/post-submit error
  classification, per-user CLOB wallet isolation, ambiguous-submit → operator page + manual
  reconcile. Dry-run intercept when `USE_REAL_CLOB=True` but `ENABLE_LIVE_TRADING=False`
  (logs intent, no DB write, no broker call) — the credential-test path.

Order backend selection (`integrations/clob/__init__.py:get_clob_client`, when `USE_REAL_CLOB=True`):
1. `USE_RUST_SIDECAR` → `RustSidecarClient` — **highest precedence; the ONLY backend that signs
   POLY_1271 deposit-wallet orders** (wrapped EIP-1271; py-clob-client-v2 cannot — upstream #70).
2. `USE_CLOB_V2` → `ClobV2Client`
3. `USE_PYSDK_CLOB` → `PolymarketSdkClient`
4. else → `ClobAdapter` (direct REST, requires L2 creds)
All default OFF; `USE_REAL_CLOB=False` → `MockClobClient` (no network, paper-safe).

Rust sidecar (`integrations/clob/rust_sidecar.py` + `sidecar/` crate): one stateless subprocess
per call; secrets via child ENV (never argv); structural error classification (network →
retryable `ClobNetworkError`; api/action → `ClobAPIError`); breaker + limiter wrapped; 45s
timeout with zombie reaping; decimal-string price/size (no binary-float dust). The deposit
wallet (funder) is resolved by `ensure_clob_credentials()` at startup via the official
`AsyncSecureClient` (or `POLYMARKET_FUNDER_ADDRESS`); a `None` funder fails fast.

Risk constants (`domain/risk/constants.py`, hard-wired, not env-overridable): Kelly 0.25,
max position 10%, daily loss −$2,000, drawdown 8%, min liquidity $10k, slippage guard 5%,
min order 5 shares; concurrency is per-user (5/12/20 or override, no global ceiling).
Risk gate `domain/risk/gate.py` step 15: a live trade's exposure can never exceed the user's
REAL deposited balance (`get_live_balance`, `wallet/ledger.py` — counts only ledger rows whose
deposit `ref_id` joins the `deposits` table, separating real money from paper top-ups); zero
real funds ⇒ no live trade, by construction. Live Auto-Trade start gate:
`MIN_LIVE_AUTOTRADE_BALANCE_USDC=5` (`domain/activation/live_mode.py`).

Strategy (`domain/strategy/strategies/late_entry_v3.py`): final-seconds crypto-candle momentum
entry; emits a sizing SUGGESTION only (risk gate applies Kelly + caps); flip-stop + fixed-time
exits; advisory oracle edge + factor-vector shadow telemetry, both fully fail-soft and
non-blocking. Never places orders, never touches the gate, never bypasses guards.

Deposits (`wallet/deposit_assets.py`): only `polygon-usdc-e` (USDC.e) is enabled end-to-end
(detectable + creditable + sweepable + reconcilable). Native Polygon USDC and USDT are
hard-disabled: Bridge settles them to pUSD, but the live order path debits the USDC.e ledger
and pUSD is documentation-only in runtime — crediting them would manufacture fake spendable
live balance (`is_fully_enabled` blocks any address/QR for them).

## 3. Files created / modified (full repo-root paths)

- projects/polymarket/crusaderbot/reports/forge/go-live-readiness.md (this report — created)
- projects/polymarket/crusaderbot/state/LIVE_READINESS.md (appended current-truth runbook section)
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md (7-section surgical update)
- projects/polymarket/crusaderbot/state/CHANGELOG.md (append-only lane entry)

WORKTODO.md left untouched: no tracked checklist item maps to this audit/doc lane,
and new items require WARP🔹CMD direction.

No runtime / strategy / risk / execution / config / migration file was touched.

## 4. What is working (evidence)

- Full test suite GREEN: `3654 passed, 10 skipped, 0 failed, 0 errors` (53.5s) — run from repo
  root via pytest.ini after installing pyproject `[project.dependencies]`.
- All six activation guards + global toggle + admin role + per-user live mode verified
  fail-closed; default OFF in `config.py`.
- Strategy/risk/execution/deposit invariants verified against code truth (Section 2). No bug,
  no silent failure, no guard bypass, no fake-enablement found.

## 5. Known issues / honest blockers (none are code bugs)

- LIVE activation is owner-operational, in production (Fly secrets / DB) — not settable from a
  CI clone, and must not be flipped blindly. See the runbook below.
- A real fund-moving live trade cannot run from this sandbox (no prod secrets, no funded wallet,
  no Polymarket-prod network; AGENTS.md/MEMORY.md forbid real external CLOB/Bridge/Relayer
  calls in CI). The only honest in-sandbox "no-error" proof is the green suite + dry-run path.
- EIP-7702 deposit-wallet L1 auth wall: py-clob-client-v2 cannot place orders for migrated
  Magic/email deposit wallets (upstream #52/#53/#64/#70/#71 OPEN). The Rust sidecar is the
  resolution (owner-selected) and already proved a live order from Fly nrt
  (`sidecar-clob-url` PROOF=PASS, sig_type=3, allow_fills=false, cancel confirmed).
- Native USDC/USDT deposits remain honestly disabled (owner directive: keep USDC.e-only). Real
  enablement needs the Bridge→pUSD→USDC.e settlement + settled-balance accounting lane (#1805,
  deferred). Crediting without it = forbidden fake-enablement.
- `late_entry_v3` out-of-sample edge UNPROVEN (`SMART_STRIKE_REQUIRE_MEASURED_EDGE=False`,
  cap-only). This is a research/calibration question, not an engineering defect.

## 6. What is next

Owner executes the GO-LIVE RUNBOOK below in production. Optional future lanes (owner-gated):
real USDC/USDT settlement path; late_entry_v3 edge calibration; staged-cohort live rollout.

---

## GO-LIVE RUNBOOK (operator / owner only — production)

Pre-conditions: migrations applied (incl. `091_live_trade_activation`); Rust sidecar binary
built and present at `RUST_SIDECAR_PATH` (`cd sidecar && cargo build --release`, deploy the
binary, default path `/usr/local/bin/order-sidecar`); deposit-wallet signer key available as
a Fly secret. Keep `withdrawal_approval_mode='manual'` for the first live cohort.

Step 0 — Order path (sidecar) credential wiring (Fly secrets):
- `POLYMARKET_PRIVATE_KEY` = deposit-wallet signer key (secret)
- `POLYMARKET_SIGNATURE_TYPE=3` (POLY_1271 deposit wallet)
- `USE_RUST_SIDECAR=true`, `RUST_SIDECAR_PATH=/usr/local/bin/order-sidecar`
- funder: leave `POLYMARKET_FUNDER_ADDRESS` unset to let `ensure_clob_credentials()`
  auto-derive the deposit wallet via AsyncSecureClient at startup, or set it explicitly.

Step 1 — Credential / dry-run proof BEFORE any guard flip:
- Set `USE_REAL_CLOB=true` while keeping `ENABLE_LIVE_TRADING=false`. The live engine's
  dry-run intercept logs `live.execute dry_run` order intent with NO DB write and NO broker
  call. Confirm `clob: POLY_1271 deposit wallet resolved=…, creds derived` at boot and a clean
  dry-run line for a candidate. This validates signing/credentials with zero capital risk.

Step 2 — Risk + security validation flags (set only after each is actually validated):
- `RISK_CONTROLS_VALIDATED=true` after `audit_risk_constants()` passes clean in prod.
- `SECURITY_HARDENING_VALIDATED=true` after the security posture is confirmed.

Step 3 — Execution + capital confirmation, in this order:
- `EXECUTION_PATH_VALIDATED=true` → `CAPITAL_MODE_CONFIRMED=true` → `ENABLE_LIVE_TRADING=true`.
- Flip the GLOBAL toggle: set `system_settings.global_live_trading_enabled='true'`
  (via the admin endpoint / `set_global_live`) — it is a hard AND with every guard.

Step 4 — Per-user opt-in + funding:
- Owner account: role `admin`, `trading_mode='live'` (typed-CONFIRM self-serve enable flow;
  Auto-Trade is forced OFF on the switch).
- Deposit USDC.e to the deposit wallet (WebTrader → Wallet). Only USDC.e credits live balance;
  native USDC/USDT are detect-only and will NOT credit. Send ~2–5 POL to the master pool for
  sweep + withdrawal gas.
- `/live_checklist` must pass (5 required gates); re-arm Auto-Trade — it will not start until
  confirmed available live USDC.e ≥ $5 (`MIN_LIVE_AUTOTRADE_BALANCE_USDC`).

Step 5 — Funded micro-trade verification (real, smallest size):
- With a small USDC.e balance, let one late_entry_v3 candidate route live. Confirm: order
  `submitted` with a real `polymarket_order_id`, `positions` row mode='live', ledger debit,
  entry notification, and a clean close (SELL) with ledger credit. Verify on the Polymarket
  dashboard. `live_order_intent` + `live_open`/`live_close` audit rows are the trace.

Step 6 — Halt / rollback (immediate):
- Kill switch (`/emergency`, DB `kill_switch_active`, or env `KILL_SWITCH=true`) halts new
  orders instantly (does not auto-close positions).
- Set `global_live_trading_enabled='false'` OR any guard back to false → all new trades route
  to paper. Existing live positions stay unwindable (close path skips open-time guards).

Step 7 — Staged rollout:
- Keep the first cohort tiny; watch the `live_order_intent`, `live_open`, `live_close`, and
  `live_blocked_fallback_paper` audit trails + on-chain confirmations before broadening.

INVARIANTS (never bypass, even here): Kelly 0.25; never full Kelly; secrets in Fly/.env only
(never argv/repo/logs); asyncio only; the six guards are AND-ed; no `phase*/` folders; no
native USDC/USDT crediting without real pUSD settlement; no force-push.
