# WARP•R00T Report — live-trade-readiness-audit

- Validation Tier: MAJOR (wallet refund path + per-user CLOB build path; both touch real-money / live-trade surfaces)
- Claim Level: NARROW INTEGRATION (two targeted fixes on existing wired paths — no new runtime authority claimed; the deposit-wallet SDK blocker is honestly documented, not fixed)
- Validation Target: `wallet/withdrawals._settle_withdrawal` refund branch when Safe-custody relayer is unavailable; `integrations/clob/user_client._build_for_user` fail-fast on builder misconfig; honest status of the deposit-wallet-1271 L1 auth wall.
- Not in Scope: the upstream py-clob-client-v2 L1 auth encoding (no public byte-level spec exists), `ENABLE_LIVE_TRADING` and the 5 activation guards (owner-only), risk constants, Kelly `a=0.25`, the SDK byte-level deposit-wallet auth fix (closed-source server verification, not solvable this session), per-user execution Steps 2–4 (Step 1 foundation already merged in #1731 + #1732).
- Suggested Next Step: WARP🔹CMD operational decision on the deposit-wallet path — (1) trade on a non-migrated POLY_PROXY account today, (2) authorize a Rust-SDK order-backend lane, or (3) wait for the upstream Python fix. Code-side: no further audit lanes required to "go live"; remaining steps are operator-only.

---

## Live-trade readiness — honest one-line verdict

**Code is live-ready. The blocker is the deposit-wallet L1 auth SDK wall (owner pick required) plus the operator activation sequence (owner-only).** No NEW code lanes can be opened to remove the SDK wall without an owner decision.

## 1. What was built

A WARP•R00T full-system audit of the live-trade surface — strategy, wallet (deposit + withdraw + sweep), and trade execution — under the directive *"make the bot ready for live trade."* Three parallel audits dispatched against the actual code (not against reports):

* **Strategy audit** — `domain/strategy/late_entry_v3.py`, `domain/orchestrator/signal_scan_job.py`, `domain/risk/gate.py`, `domain/strategy/registry.py`, `domain/strategy/scorer.py`. Verdict: **CLEAN.** All 13 gate steps wired, Kelly clamped at `0.25` (`domain/risk/gate.py:654, 663`), position cap `0.10` (`domain/risk/constants.py:5`), dedup at 300s (`domain/risk/constants.py:20`), correlation guard 2-cap BTC/ETH/SOL same-side (`signal_scan_job:2564-2616`), fill-drift guard 10% band (`signal_scan_job:2494-2515`), oracle edge hard-rejects fail-OPEN (`late_entry_v3:1144-1155`), `ENABLE_LIVE_TRADING` 6-condition `_passes_live_guards` (`gate.py:328-340`), no silent `except: pass`, no per-candidate DB read on the hot path (WARP-89 capital_alloc_pct preload preserved at `late_entry_v3:2199-2202`). 0 actionable findings.
* **Wallet audit** — `wallet/withdrawals.py`, `wallet/custody.py`, `wallet/safe.py`, `wallet/vault.py`, `scheduler._sweep_deposits_onchain`, `integrations/polygon_usdc.py`, `integrations/builder_relayer.py`. Verdict: **1 CRITICAL + 1 HIGH, same root cause.** Reorg handling at `DEPOSIT_CONFIRMATION_DEPTH=32` (`scheduler.py:221`), idempotency on `(tx_hash, log_index)` + `status='pending'` guard (`scheduler.py:362`), wrong-token (native USDC) alerts only (`scheduler.py:242-256`, mig 093), nonce serialization on every master-wallet send (`polygon_usdc.py:125, 176, 239`), encrypted-key not exposed in logs / repr, RLS on `wrong_token_deposits` (mig 093:24), custody-mode dispatcher correct (`custody.py:71-89`). The CRITICAL + HIGH share the BuilderRelayerUnavailable inheritance gap — fixed in this lane.
* **Execution audit** — `domain/execution/router.py`, `paper.py`, `live.py`, `engine.py`, `reconcile.py`, `live_activation.py`, `domain/risk/kill_switch_exec.py`, `domain/ops/global_live_gate.py`, `integrations/clob/__init__.py`, `integrations/clob/user_client.py`, `integrations/clob/v2_client.py`. Verdict: **1 HIGH.** Router global gate at `router.py:68`, guard assertion at `router.py:82`, paper fallback gated, live path idempotency via `ON CONFLICT (idempotency_key) DO NOTHING` (`live.py:245`, `paper.py:46`), capital cap enforced at `live_activation.py:84` and `gate.py:809`, reconciler is detection-only (`reconcile.py:242-282`), kill switch broker `cancel_all_orders` wired (`kill_switch_exec.py:135`), cross-user CLOB isolation enforced via UUID type check + hard-fail on missing user_id (`user_client.py:263-274`), `assert_live_guards` called before CLOB access (`live.py:151`), `ENABLE_LIVE_TRADING` and `USE_REAL_CLOB` re-checked (`live.py:123-138`). The 1 HIGH is the per-user CLOB build path missing the builder-attribution fail-fast that the global factory has — fixed in this lane.

Two fixes shipped together because they touch the live-trade-readiness surface and share the WARP•R00T scope-discipline rule of batching related findings into one lane.

### Fix A — `BuilderRelayerUnavailable` is now a `PreflightError`

Root cause: `BuilderRelayerUnavailable` (`integrations/builder_relayer.py:39`) was a bare `RuntimeError`. When `CUSTODY_MODE='safe'` and Builder credentials are not set (operator misconfig), `SafeCustody.transfer_usdc` raises it at `wallet/custody.py:130` **before** the on-chain leg. Semantically this is identical to a `PreflightError` (no capital moved) — but the type mismatch meant `_settle_withdrawal`'s `except PreflightError` branch did not catch it. The generic `except Exception` branch then marked the row `failed` and **did not refund** the ledger debit at `wallet/withdrawals.py:100`. **User funds stranded on Safe-custody misconfig.**

Sweep path (`scheduler.py:1055-1060`) had the same shape: `BuilderRelayerUnavailable` fell through to `sweep_failed` instead of the intended `sweep_skip`, leaving deposits `swept=FALSE` indefinitely.

Fix: make `BuilderRelayerUnavailable` a subclass of `PreflightError`. Both branches now do the right thing automatically (refund withdrawal; treat sweep as skip + retry next tick). Any code already catching `BuilderRelayerUnavailable` directly still works — subclassing only *widens* what `except PreflightError` catches, never narrows it.

Regression test `test_builder_relayer_unavailable_refunds_ledger` drives `_settle_withdrawal` against a transfer that raises `BuilderRelayerUnavailable` and asserts (a) the inheritance invariant `issubclass(BuilderRelayerUnavailable, PreflightError)`, (b) `credit_in_conn` was awaited (ledger refunded), (c) the `failed` UPDATE ran. Pre-fix: the test exercises the bug shape; the assertion `mock_credit.assert_awaited_once()` would fail because the code went down the generic `except Exception` branch. Post-fix: passes.

### Fix B — `user_client._build_for_user` fail-fast on builder misconfig

Root cause: `integrations/clob/user_client.py:_build_for_user` constructed `ClobV2Client` with `POLYMARKET_BUILDER_CODE` + `POLYMARKET_BUILDER_ADDRESS` but did not validate the half-configured shape (code set, address blank → invalid zero-address attribution). The global `get_clob_client` factory has this fail-fast at `clob/__init__.py:436-444`; the per-user path that just merged in #1731 + #1732 didn't.

Without this check every per-user resolve paid the vault decrypt + on-chain deposit-wallet derive cost before the SDK construction surface raised, and the broker would only reject at order-placement time. With it, the error surfaces at the `_build_for_user` entry — same posture as the global path.

Regression tests `test_builder_code_without_address_hard_fails` (code set, address blank → `ClobConfigError`) and `test_zero_builder_code_does_not_require_address` (all-zeros sentinel = "unset", no address required) pin both branches.

## 2. Current system architecture (relevant slice)

```
withdrawal request → ledger debit (immediate, idempotent)
                    → status=pending
                    → admin approve → _settle_withdrawal
                                       → _attempt_onchain_transfer
                                          → EOA path (polygon_usdc)
                                          | Safe path (SafeCustody → relayer)
                                       ↓
                                       PreflightError? → status=failed + REFUND ledger
                                       ↑ (BuilderRelayerUnavailable is now a PreflightError — refund triggers)
                                       Other Exception? → status=failed, NO refund (op reconcile)

deposit sweep → for each user with confirmed deposit:
                  sweep_usdc_to_master
                  PreflightError? → sweep_skip (warning, retry next tick)
                                    ↑ (BuilderRelayerUnavailable now lands here)
                  Other Exception? → sweep_failed (error, retry next tick)

per-user CLOB build → _build_for_user(user_id, settings)
                      → vault.get_decrypted_pk(user_id)            (PerUserClobError if no key)
                      → resolve_deposit_wallet_creds(pk)            (AsyncSecureClient derive)
                      → fail-fast on POLYMARKET_BUILDER_CODE w/o ADDRESS  ← NEW
                      → ClobV2Client(...)                           (signature_type=POLY_1271)
                      → cache (LRU 256, single-flight, isolation by user_id)
```

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/reports/forge/live-trade-readiness-audit.md` (this file)

Modified:
- `projects/polymarket/crusaderbot/integrations/builder_relayer.py` — `BuilderRelayerUnavailable` now extends `PreflightError` (+ import); docstring updated to spell out the semantic alignment.
- `projects/polymarket/crusaderbot/integrations/clob/user_client.py` — fail-fast on `POLYMARKET_BUILDER_CODE` without `POLYMARKET_BUILDER_ADDRESS` (mirrors the single-wallet factory).
- `projects/polymarket/crusaderbot/tests/test_wallet_withdraw_flow.py` — `test_builder_relayer_unavailable_refunds_ledger` regression test.
- `projects/polymarket/crusaderbot/tests/test_user_clob_client.py` — `test_builder_code_without_address_hard_fails` + `test_zero_builder_code_does_not_require_address`.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — sections synced.
- `projects/polymarket/crusaderbot/state/WORKTODO.md` — item marked.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry appended.

## 4. What is working

* Wallet refund correctness on Safe-custody misconfig — `BuilderRelayerUnavailable` lands in the `PreflightError` branch and triggers `credit_in_conn` refund. Inheritance invariant pinned in the regression test.
* Sweep retry semantics under Safe-custody misconfig — `BuilderRelayerUnavailable` logs `sweep_skip` (intended), not `sweep_failed`; the deposit row stays unswept and is naturally retried on the next tick.
* Per-user CLOB build fail-fast at the entry — same posture as the global `get_clob_client` factory; the zero-sentinel branch confirms no false positive on the unset case.
* 478 wallet + clob regression tests pass; 0 failures, 4 skipped (pre-existing, optional polymarket SDK), 12 warnings (pre-existing async-decorator warnings).
* Ruff clean on all touched files.

## 5. Known issues (DOCUMENTED, not fixed this lane)

* **THE live-trade blocker — deposit-wallet L1 auth (`reports/forge/deposit-wallet-1271-auth.md`).** Polymarket migrated every Magic/email account (incl. the owner's) to an EIP-7702 deposit wallet after 2026-04-28. `py-clob-client-v2`'s L1 auth binds the API key to the EOA, not the deposit wallet (upstream issues #52/#53/#64/#70/#71 — all OPEN, all unfixed). Validated on the real broker over 3 iterations: sig-3 + deposit-wallet maker cleared the `400 maker address not allowed` blocker (deposit wallet IS accepted as maker) but hit `401 Invalid L1 Request headers` — Polymarket's server-side ERC-7739 verification uses an undocumented byte encoding. No public working implementation exists. Blind iteration was stopped (low-EV). **Owner picks the path:**
  1. **Trade now on a non-migrated POLY_PROXY (sig-1) account** — the bot's existing, WARP-74-broker-proven path works immediately. The owner's current account is migrated; this needs a different/legacy wallet.
  2. **Authorize a Rust-SDK order-backend lane** — `polymarket-client-sdk-v2` (Rust) is the only client the ecosystem reports trading deposit wallets. Sidecar invoked from the Python bot. Scoped lane, owner-gated.
  3. **Wait for the upstream Python fix** — the moment Polymarket publishes/fixes the L1 deposit-wallet encoding, PR #1727 completes (wrapper + wiring + proof scaffolding already in place, gated to sig-3 only).
* **Owner-only operator sequence to flip live.** No code-side blocker remains for the activation guards beyond the SDK wall above. The owner-only sequence (preserved verbatim from `state/LIVE_READINESS.md`): (1) fund the master wallet (USDC + MATIC); (2) apply pending migrations to prod; (3) set `RISK_CONTROLS_VALIDATED=true` after `audit_risk_constants()` passes clean; (4) set `EXECUTION_PATH_VALIDATED=true`, then `CAPITAL_MODE_CONFIRMED=true`, then `ENABLE_LIVE_TRADING=true` (in that order); (5) `SWEEP_ONCHAIN_ENABLED=true` for a small cohort first; (6) `withdrawal_approval_mode='manual'` for the first live cohort; (7) staged rollout — kill switch is the immediate halt.
* **`POLYMARKET_BUILDER_*` validation surfaces only at `_build_for_user` time** — not at process boot. A misconfigured deploy lands fine; the first per-user resolve raises. The global factory has the same posture. An eager startup check is a follow-up MINOR if/when the per-user path becomes the default execution surface.
* Smart Strike LIVE slippage-of-edge tier remains cap-only by default (`SMART_STRIKE_REQUIRE_MEASURED_EDGE=False`) — documented in PROJECT_STATE KNOWN ISSUES, deliberate posture, not in scope here.
* 15m per-cell LIVE caps are conservative mirrors of 5m (btc $500 / eth $100 / sol $100) — operator confirm pending, documented in PROJECT_STATE KNOWN ISSUES.

## 6. What is next

* Suggested next: WARP🔹CMD picks the deposit-wallet path (path 1 / 2 / 3 above). Until then, no code-side action removes the wall. Code-side, the bot is live-ready under path 1.
* Optional follow-up MINOR — eager boot-time validation of `POLYMARKET_BUILDER_CODE`/`POLYMARKET_BUILDER_ADDRESS` if the per-user CLOB build becomes the default execution surface (Step 4 of the per-user epic).
* No follow-up on the strategy or execution surfaces — both audits returned clean.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: wallet refund path + per-user CLOB builder fail-fast + honest live-trade-readiness status
Not in Scope: upstream SDK byte encoding / live activation guards / risk constants / per-user execution Steps 2–4
Suggested Next: WARP🔹CMD operational decision on the deposit-wallet path; no further code-side lane needed for live readiness
