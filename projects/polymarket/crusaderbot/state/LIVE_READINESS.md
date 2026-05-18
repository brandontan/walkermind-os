# Live Readiness Report — Track D Live Gate Hardening

Generated: 2026-05-18
Branch: WARP/CRUSADERBOT-FAST-LIVE-GATE-HARDENING
Tier: MAJOR
SENTINEL: Required before merge

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
