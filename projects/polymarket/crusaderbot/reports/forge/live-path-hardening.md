# WARP•R00T FORGE REPORT — live-path-hardening

Branch: WARP/ROOT/live-path-hardening
Date: 2026-05-30 01:30 Asia/Jakarta
Lane: 5/5 (final) of the WARP•R00T full-system pre-public-ready audit fix campaign

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : on-chain sends are nonce-safe + gas-capped; the auto-scan live path sees the real per-user cap; live-guard + Kelly bounds are internally consistent
Not in Scope      : arming live (operator decision, still gated OFF); MAX_CONCURRENT_TRADES policy (advisory — see Known issues)
Suggested Next    : WARP•SENTINEL (money path), then WARP🔹CMD go-live sequence

## 1. What was built
Pre-LIVE money-path hardening. Every item is LIVE-gated (EXECUTION_PATH_VALIDATED
off in prod), so PAPER is untouched — these are blockers to fix BEFORE the live
capital path is armed.

- **L1 — nonce race on the master/user EOA.** All four on-chain send paths read
  `get_transaction_count` independently with no lock and the default `latest`
  tag, so two concurrent capital ops (withdraw + sweep + redeem) could read the
  same nonce → one tx dropped/replaced. New shared per-address `nonce_lock`
  (`integrations/polygon.py`); the nonce-read → sign → broadcast block in
  `polygon_usdc.transfer_usdc` / `_send_native_matic` / `sweep_usdc_to_master`
  and `polymarket.submit_live_redemption` now runs under `async with
  nonce_lock(addr)` and reads with the `"pending"` block tag (counts in-mempool
  txs). Receipt wait stays outside the lock so it releases right after broadcast.
- **L2 — redemption had no gas ceiling.** `submit_live_redemption` now applies
  the same `INSTANT_REDEEM_GAS_GWEI_MAX` pre-flight as transfer/sweep — a fee
  spike can no longer drain the hot pool on redemption gas.
- **L3 — auto-scan live cap was always 0.** `_load_enrolled_users` did not SELECT
  `live_capital_cap_usdc`, but `_build_trade_signal` reads it → always None → 0.0
  → gate step 15 rejected EVERY live trade from the signal-scan path. Added
  `COALESCE(s.live_capital_cap_usdc, 0) AS live_capital_cap_usdc` to the SELECT.
- **L4a — guard consistency.** `_passes_live_guards` now also requires
  `USE_REAL_CLOB` (mirrors `assert_live_guards`), so the gate can't label a trade
  `chosen_mode='live'` that the router would bounce to paper.
- **L4b — Kelly bound.** Gate's Kelly range check was `(0, 0.5]`; tightened to
  `(0, 0.25]` to match `constants.KELLY_FRACTION=0.25`, `hardening.audit_risk_constants`,
  and the CLAUDE.md hard rule.

## 2. Current system architecture (relevant slice)
`integrations/polygon.nonce_lock(address)` is the single serialization point for
all master/user-wallet sends (process-local; one Fly primary). Combined with the
`pending` tag, back-to-back capital ops can no longer collide on a nonce. The
risk gate's live decision (`_passes_live_guards`) and per-trade cap (step 15) now
both reflect the real operator flags and per-user cap.

## 3. Files created / modified (full repo-root paths)
Modified:
- projects/polymarket/crusaderbot/integrations/polygon.py (nonce_lock helper + asyncio import)
- projects/polymarket/crusaderbot/integrations/polygon_usdc.py (lock + pending tag on transfer/topup/sweep)
- projects/polymarket/crusaderbot/integrations/polymarket.py (lock + pending tag + gas ceiling on submit_live_redemption)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py (SELECT live_capital_cap_usdc)
- projects/polymarket/crusaderbot/domain/risk/gate.py (_passes_live_guards += USE_REAL_CLOB; Kelly bound 0.5→0.25)
Created:
- projects/polymarket/crusaderbot/tests/test_live_path_hardening.py (6 tests)

## 4. What is working
- py_compile + ruff clean on all 5 touched modules.
- 6/6 new tests pass; 89 existing withdrawal/sweep/custody/live-gate/live-activation/redeem tests pass (no regression).

## 5. Known issues
- **MAX_CONCURRENT_TRADES (advisory, NOT changed):** `constants.MAX_CONCURRENT_TRADES
  = 5` is dead — the gate enforces per-profile `max_concurrent` (up to 20). The
  AGENTS RISK CONSTANTS list says 5. Forcing 5 would reduce concurrency for ALL
  users in PAPER today (gate step 7 is not live-gated) — a behavior change that
  contradicts the profile design. Left as-is pending an explicit WARP🔹CMD
  decision: enforce `min(profile, 5)` hard cap, or update the spec to per-profile.
- Nonce lock is process-local (single Fly primary) — consistent with the
  existing in-process limiter design.

## 6. What is next
- WARP•SENTINEL (money path) — MAJOR.
- WARP🔹CMD owner go-live sequence (fund master, apply prod migrations, flip the
  activation guards) per state/LIVE_READINESS.md. This lane removes the engineering
  blockers; arming live remains an operator decision.

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
