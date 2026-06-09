# Live Readiness Report — Track D Live Gate Hardening

Generated: 2026-05-18
Branch: WARP/CRUSADERBOT-FAST-LIVE-GATE-HARDENING
Tier: MAJOR
SENTINEL: Required before merge

---

## 2026-05-28 UPDATE — WARP•R00T LIVE+PAPER readiness pass (3 lanes)

WARP•R00T verified the system is engineering-ready for concurrent LIVE +
PAPER operation, with PAPER as the only mode any user receives at
creation regardless of `ENABLE_LIVE_TRADING`. Three lanes shipped:

- **Lane 1 — `WARP/ROOT/system-ready-audit`** (MERGED #1409, MINOR/FOUNDATION).
  Read-only audit. Verdict: 0 current risks. Confirmed all 5 LIVE activation
  guards default `false`, `assert_live_guards` (`domain/execution/live.py:50-80`)
  checks 8 conditions including `USE_REAL_CLOB`, `role=='admin'`,
  `trading_mode=='live'`; router (`domain/execution/router.py`) audit-logs
  `GUARD_BYPASS_ATTEMPT` at CRITICAL and paper-falls-back on any guard
  failure; LIVE-flip is hard-gated by `live_checklist.evaluate()`
  (8 gates) + typed CONFIRM + defense-in-depth re-check; PAPER-default
  for new users is schema-enforced (`migrations/001_init.sql:73`) and
  protected across all three creation paths (Telegram `upsert_user`,
  WebTrader `auth.signup_email`, lazy `get_settings_for`); on-chain
  capital paths #1402/#1403/#1408 all triple-gated OFF. Surfaced 3
  brittleness items for Lane 2.

- **Lane 2 — `WARP/ROOT/paper-default-hardening`** (MERGED #1410, STANDARD/NARROW).
  Belt-and-suspenders enforcement: every `INSERT INTO user_settings` in
  production now writes `trading_mode='paper'` explicitly (no longer
  schema-default reliant). Three write sites hardened (`users.py`
  Telegram new-user, `users.py` lazy `get_settings_for`, new explicit
  INSERT in `webtrader/backend/auth.py:signup_email`). Silent
  `except Exception: pass` in webtrader signup replaced with
  `logger.exception(...)` per the no-silent-failures HARD RULE. New
  hermetic `tests/test_paper_default_invariant.py` (5 tests) pins the
  invariant at INSERT-call-shape + source-regex layers — fail-closed if
  any future edit drops the literal `'paper'`. Full suite 1859 passed.
  The LIVE-flip path is unchanged.

- **Lane 3 — `WARP/ROOT/live-readiness-final`** (this update, MINOR — state
  sync only, no code). Documentation sync: `state/LIVE_READINESS.md` (this
  file), `state/PRODUCTION_CHECKLIST.md`, `state/WORKTODO.md`,
  `state/PROJECT_STATE.md`, `state/CHANGELOG.md`.

**No code-side LIVE blockers remain.** The Final go-live sequence below
is preserved verbatim — every remaining step is owner-operational.

---

## 2026-05-28 UPDATE — Capital paths COMPLETE; engineering LIVE-ready

The two on-chain capital paths that were the last code-side LIVE blockers are
now wired, SENTINEL-approved, and merged — all behind activation guards that
remain OFF (paper is unaffected):

- **Withdrawal exit** (PR #1402, SENTINEL 94/100): `integrations/polygon_usdc.py:transfer_usdc()`
  signs USDC out of the master hot-pool; `wallet/withdrawals.py` drives the
  processing→completed/failed lifecycle with refund-on-preflight. Gated by
  `EXECUTION_PATH_VALIDATED`.
- **Deposit sweep / pool funding** (PR #1403, SENTINEL 94/100):
  `integrations/polygon_usdc.py:sweep_usdc_to_master()` + `scheduler._sweep_deposits_onchain()`
  consolidate per-user EOA deposit wallets into the master pool using a
  master-funded MATIC gas top-up. Double-gated by `EXECUTION_PATH_VALIDATED`
  AND `SWEEP_ONCHAIN_ENABLED` (both default OFF).

There are NO remaining `NotImplementedError`/stub gaps in the trading, risk,
execution, redeem, withdraw, or sweep paths. (The only TODO outside this scope
is `lib/strategies/weather_arb.py` — an experimental, non-core strategy.)

### Final go-live sequence (owner / WARP🔹CMD only — guards stay OFF until then)

1. Fund the master wallet: USDC (withdrawals + trading) and MATIC (gas + sweep top-ups).
2. Apply any pending migrations to production (incl. 060_withdrawals_onchain).
3. Set `RISK_CONTROLS_VALIDATED=true` after `audit_risk_constants()` passes clean in prod.
4. Set `EXECUTION_PATH_VALIDATED=true`, then `CAPITAL_MODE_CONFIRMED=true`, then `ENABLE_LIVE_TRADING=true` (in that order).
5. Enable `SWEEP_ONCHAIN_ENABLED=true` for a SMALL cohort first; watch the
   `deposit_sweep_onchain` audit trail + on-chain confirmations before broadening.
6. Keep `withdrawal_approval_mode='manual'` for the first live cohort.
7. Staged rollout + observation at each step; kill switch (`/emergency`) is the immediate halt.

Native gasless sweeps (Polymarket Builder relayer + Gnosis-Safe proxy custody)
are the documented FUTURE optimization — not required for go-live.

---

## Execution Path: VALIDATED

All code paths between signal → risk gate → order → position have been audited
and hardened in this PR.

- `domain/execution/router.py`: `assert_live_guards()` called BEFORE any live engine
  call. Guard bypass logged at CRITICAL (not WARNING). Paper path and live path are
  mutually exclusive branches — no shared mutation.
- `domain/execution/live.py`: Defense-in-depth guard check at execution entry.
  If `ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`,
  or `USE_REAL_CLOB` are false when `live.execute()` is called, a CRITICAL log is
  emitted before the regular `assert_live_guards()` raises `LivePreSubmitError`.
- `USE_REAL_CLOB=False` or `ENABLE_LIVE_TRADING=False`: order routes to paper fill
  via router fallback — never reaches CLOB.
- Slippage guard (`SLIPPAGE_GUARD_PCT`) acts as an additional pre-submission fence.

## Slippage Guard: IMPLEMENTED

- Constant: `SLIPPAGE_GUARD_PCT = 0.05` (5%)
- Location: `projects/polymarket/crusaderbot/domain/risk/constants.py:26`
- Enforcement: `domain/execution/live.py` — before any CLOB submission,
  `abs(limit_price - signal_price) / signal_price > SLIPPAGE_GUARD_PCT` causes
  immediate `LivePreSubmitError` logged at CRITICAL as `SLIPPAGE_REJECTED`.
- Paper mode: not enforced (paper orders do not call the CLOB).
- SENTINEL must verify no bypass exists in the live submission path.

## Capital Checks: ALL 4 ASSERTIONS PRESENT

Location: `projects/polymarket/crusaderbot/domain/risk/gate.py` — `validate_risk_caps()`

| Check | Condition | Action on Fail |
|---|---|---|
| available_balance > 0 | `balance <= 0` | reject + log |
| order_size_usdc <= balance × 10% | `proposed_size > max_single` | reject + log |
| total_exposure_usdc <= balance × 80% | `open_exp + proposed_size > max_exp` | reject + log |
| daily_loss >= -50.0 (paper default) | `today_pnl <= MAX_DAILY_LOSS_USD` | reject + log |

All assertions fail-safe: return `GateResult(approved=False, ...)`, never crash.
Caps are configured in `config.py`: `MAX_SINGLE_POSITION_PCT=0.10`,
`MAX_TOTAL_EXPOSURE_PCT=0.80`, `MAX_DAILY_LOSS_USD=-50.0`, `MAX_OPEN_POSITIONS=20`.

## Kill Switch: ALL 3 PATHS VERIFIED

| Path | Mechanism | Convergence Point |
|---|---|---|
| Path 1: Telegram /emergency | Bot handler → `execute_kill_switch(triggered_by="telegram_operator")` | `domain/risk/kill_switch_exec.py:execute_kill_switch()` |
| Path 2: DB flag direct set | `system_settings.kill_switch_active=true` → `ops_ks.is_active()=True` → gate step 1 rejects | `domain/ops/kill_switch.py:is_active()` |
| Path 3: Env var KILL_SWITCH=true | `main.py` startup check → `execute_kill_switch(triggered_by="env_KILL_SWITCH")` | `domain/risk/kill_switch_exec.py:execute_kill_switch()` |

All 3 paths:
- (a) halt new order creation — gate step 1 blocks or orders cancelled
- (b) log activation with timestamp + actor — audit_log INSERT written
- (c) do NOT close existing positions automatically — no UPDATE positions SQL

Unit tests: `projects/polymarket/crusaderbot/tests/test_kill_switch_paths.py`
- `test_kill_switch_telegram` — PASS
- `test_kill_switch_db` — PASS
- `test_kill_switch_env` — PASS

## Guard Status: ALL 4 GUARDS OFF (paper-only posture)

| Guard | Current Value | Set By |
|---|---|---|
| `ENABLE_LIVE_TRADING` | `false` | `config.py` default + fly.toml |
| `EXECUTION_PATH_VALIDATED` | `false` | `config.py` default |
| `CAPITAL_MODE_CONFIRMED` | `false` | `config.py` default |
| `RISK_CONTROLS_VALIDATED` | `false` | `config.py` default |

No guard was changed to `true` in this PR. Bot remains paper-only.

## SENTINEL Requirement: MANDATORY

This PR is Tier: MAJOR. WARP•SENTINEL validation is required before merge.

SENTINEL must verify:
1. `SLIPPAGE_GUARD_PCT` fence cannot be bypassed on the live path
2. `validate_risk_caps()` is called before every order — no path skips it
3. All 3 kill switch paths produce identical halt behavior
4. No guard is set to `true` anywhere in the diff
5. `dry_run_execute()` does not submit any order or mutate DB state

## Recommendation: What Must Happen Before Guards Can Be Set True

Before any guard can be set to `true`, the following must be completed:

1. **WARP•SENTINEL audit** of this PR (MAJOR tier — mandatory).
2. **End-to-end live path test** in a staging environment with `USE_REAL_CLOB=True`
   and real Polymarket credentials (testnet only).
3. **Capital mode confirmation** — operator must confirm exact USDC amount
   to be deployed and set `CAPITAL_MODE_CONFIRMED=true` explicitly.
4. **Execution path validation** — `EXECUTION_PATH_VALIDATED=true` set only
   after SENTINEL confirms the live path is clean.
5. **`RISK_CONTROLS_VALIDATED=true`** set only after `audit_risk_constants()`
   passes with zero violations in the target environment.
6. **Migration 032+** applied to production (system_flags, audit_log tables).
7. **WARP🔹CMD explicit owner decision** — no guard changes without owner sign-off.

Current posture: PAPER ONLY. No real capital at risk.
