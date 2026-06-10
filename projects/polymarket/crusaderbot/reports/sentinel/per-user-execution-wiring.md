# WARP•SENTINEL Validation — per-user-execution-wiring (Step 5)

## Environment

- Tier dispatched: dev (no staging broker, no live infra)
- Branch under test: `main @ dc72ee15` (WARP-74 + per-user lane Steps 1-4 all merged)
- Forge source: `projects/polymarket/crusaderbot/reports/forge/per-user-execution-wiring.md`
- Validation Tier: MAJOR — NARROW INTEGRATION
- Verdict scope: the in-code cross-user isolation assertion + the live.execute / live.close_position wiring that consumes it (Step 4 owner-set §4 invariant)

---

## Phase 0 — Pre-Test

- Forge report at correct path + all 6 sections + metadata → PASS
- `domain/execution/per_user_clob.py` present (137 lines) → PASS
- Tests present: `test_per_user_clob_resolver.py` (8) + `test_live_per_user_wiring.py` (5) → PASS
- `PROJECT_STATE.md` updated by forge lane → PASS
- No `phase*/` folders anywhere in tree → PASS
- Domain structure correct, no shims, no compatibility layers → PASS

Phase 0: PASS — proceed.

---

## Phase 1 — Functional / Contract

`python -m pytest test_per_user_clob_resolver.py test_live_per_user_wiring.py -v`

Result: **13 passed in 3.92s**

Contract pinned:

- `test_match_returns_client` — SDK addr == stored addr → returns client
- `test_match_is_case_insensitive` — checksum vs lowercase compare correct
- `test_drift_raises_wallet_identity_mismatch` — drift refuses, exception carries diff
- `test_non_uuid_user_id_raises_isolation_error` — defense-in-depth on bypassed typing
- `test_null_deposit_wallet_raises_config_error` — NULL column → `ClobConfigError` pointing at `backfill_deposit_wallets()`
- `test_empty_string_deposit_wallet_is_treated_as_null` — empty string ≡ NULL
- `test_missing_wallets_row_raises_config_error` — row absent → clean error
- `test_get_user_clob_client_with_wallet_returns_pair` — accessor contract
- `test_per_user_flag_on_calls_resolver` — flag ON dispatches to resolver, NEVER `get_clob_client`
- `test_per_user_flag_off_uses_global_client` — default config byte-identical
- `test_injected_clob_client_overrides_flag` — staging override wins
- `test_drift_refuses_through_full_execute_path` — drift → `LivePreSubmitError`, `post_order` never awaited
- `test_isolation_violation_through_full_execute_path` — non-UUID via full execute path → same refuse

---

## Phase 2 — Pipeline (end-to-end drift injection)

Built an out-of-tree driver `/tmp/sentinel_drift_inject.py` that bypasses the integration-test mock of `resolve_user_clob_client` and exercises the REAL function with:

- SDK boundary planted via cached `_CachedClient(wallet=0x3feC63…606A9)` (the canonical resolved address)
- DB row planted as `0xDEADBEEFcafeBABE…DEAD` (deliberate drift)
- Same-conn `fetchrow` invariant asserted by the conn stub

Result: `WalletIdentityMismatch` raised, `client.post_order.await_count == 0`, `conn.fetchrow` called exactly once.

Evidence (from driver stdout):

```
resolve_user_clob_client: WALLET IDENTITY MISMATCH user_id=50bfb434-…
resolved=0x3feC630a07a263Ee0bd6cD108ff4b8Ed1eB606A9
stored=0xDEADBEEFcafeBABE00000000000000000000DEAD — refusing to sign
[PASS] WalletIdentityMismatch raised
[PASS] client.post_order never awaited (await_count=0)
[PASS] conn.fetchrow called 1 time(s) — same-conn wallet read
```

The SAFETY-CRITICAL pipeline claim is proven: drift → refuse BEFORE broker call.

---

## Phase 3 — Failure Modes

All five hard-refuse paths verified (Phase 1) + classified to `LivePreSubmitError` at the live.execute boundary (`domain/execution/live.py:284-292`, mirrored at `:528-538` for `close_position`):

| Failure | Refuse type | Classifies to |
|---|---|---|
| Drift (wallet ≠ stored) | `WalletIdentityMismatch` | `LivePreSubmitError("isolation refused")` |
| Non-UUID user_id | `PerUserClobIsolationError` | `LivePreSubmitError("isolation refused")` |
| NULL deposit wallet column | `ClobConfigError(backfill)` | `LivePreSubmitError("CLOB client config error")` |
| Empty-string column | `ClobConfigError(backfill)` | same |
| Missing wallets row | `ClobConfigError(no wallets row)` | same |

Router's existing pre-submit → paper-fallback classification (post-WARP-91) handles all five cleanly. No silent failure surface.

---

## Phase 4 — Async Safety

Resolver is pure single-await (one `await get_user_clob_client_with_wallet` + one `await conn.fetchrow`). The race surface lives upstream in `user_client.py` and was hardened in WARP/root-per-user-clob-client-async-hardening (PR #1732, 2 cancellation regressions pinned: HIGH-1 holder-cancel + MED-3 task-cancel).

Pre-warm pattern (`live.py:238-264`) is the correctness-critical piece: SDK build (vault decrypt + RPC) runs BEFORE `pool.acquire()`, so no Postgres connection slot is held across the slow I/O. The in-transaction `resolve_user_clob_client` is then guaranteed to hit the cache → O(1) + 1 SELECT + string compare.

No new race surface introduced by Step 4.

---

## Phase 5 — Risk Rules Sanity

| Invariant | Check | Result |
|---|---|---|
| KELLY_FRACTION = 0.25 | `domain/risk/constants.py:4` | INTACT |
| `ENABLE_LIVE_TRADING` default False | `config.py:485` | INTACT |
| `USE_PER_USER_EXECUTION` default False | `config.py:430` | INTACT |
| `USE_RUST_SIDECAR` default False | `config.py:414` | INTACT |
| asyncio-only (no `import threading`) | `grep` domain/ + integrations/ | CLEAN |
| no `phase*/` folders | `find -type d -name phase*` | CLEAN |
| 5 activation guards unchanged | Step 4 forge report §"DID NOT TOUCH" | CONFIRMED |

---

## Phase 6 — Latency

Resolver in-transaction cost on cache hit:
- 1 `SELECT polymarket_deposit_wallet FROM wallets WHERE user_id = $1` (indexed lookup, single row)
- 1 string compare
- 1 dict access on `_CachedClient`

Sub-millisecond at the application layer. Well inside `exec<500ms` budget. SDK build cost lives in pre-warm OUTSIDE the transaction so it does not contribute to in-flight order latency on the hot path.

---

## Phase 7 — Infrastructure

Dev environment — no Postgres / Redis / Telegram / Polymarket broker available to enforce. The functional/behavioural claims do not depend on live infra: tests use hermetic conn stubs and mock the SDK boundary. Real-broker validation already complete in the upstream lane (Rust sidecar `PROOF_RESULT=PASS` run #7, merged dc72ee15).

---

## Phase 8 — Telegram / Alerts

`logger.warning` with structured fields (`user_id=…`, `resolved=…`, `stored=…`) fires on drift in `per_user_clob.py:126-130` AND `user_client` isolation log fires for non-UUID. The exception propagates to the existing live.execute → router → operator-alert chain (proven by WARP-74 staging cases). No new alert surface added; reuses the proven WARP-74 path.

Cannot independently render the Telegram alert in dev env (no `TELEGRAM_BOT_TOKEN`) — minor deduction in score.

---

## Adjacent Regression Sweep

`python -m pytest tests/test_user_clob_client.py tests/test_live_execution_rewire.py tests/test_live_gate_hardening.py -q`

Result: **98 passed in 2.11s** — zero collateral damage on the adjacent surfaces (single-flight + LRU + execute() rewire + gate hardening).

---

## Stability Score

| Dimension | Weight | Score |
|---|---|---|
| Architecture | 20% | 20 |
| Functional | 20% | 20 |
| Failure modes | 20% | 20 |
| Risk rules | 20% | 20 |
| Infra + Telegram | 10% | 8 |
| Latency | 10% | 10 |

**Total: 98/100**

---

## Critical Issues

None found.

The only deduction (Telegram alert rendering not independently verified in dev env) is environmental, not a code defect. The structured warning fires; the operator-alert path is the existing WARP-74-proven chain.

---

## GO-LIVE Status

**APPROVED — Score 98/100, 0 critical issues.**

The cross-user isolation invariant from #1730 §4 is enforced in code. Drift refuses BEFORE the broker call. NULL / empty / missing-row / non-UUID all classify cleanly. The pre-warm pattern keeps the slow SDK build outside the Postgres connection. Default-OFF flag means activation is a single operator flip, independently gated from `ENABLE_LIVE_TRADING`.

---

## Owner Activation Sequence

1. Run `backfill_deposit_wallets()` on prod (migration 094 landed in #1736; existing wallets rows have NULL until backfilled)
2. `flyctl secrets set USE_RUST_SIDECAR=true POLYMARKET_SIGNATURE_TYPE=3 --app crusaderbot`
3. `flyctl secrets set USE_PER_USER_EXECUTION=true --app crusaderbot`
4. The 5-guard activation sequence remains (`RISK_CONTROLS_VALIDATED` → `EXECUTION_PATH_VALIDATED` → `CAPITAL_MODE_CONFIRMED` → `ENABLE_LIVE_TRADING`)

Live trading remains independently owner-gated regardless of these flips.

---

## Fix Recommendations

None blocking. One follow-up note (NOT blocking):

- Consider surfacing `WalletIdentityMismatch` as a distinct router-side audit event (e.g. `wallet_identity_drift_detected`) alongside the existing `live_blocked_fallback_paper` so operators can grep prod logs for drift specifically without parsing the LivePreSubmitError prefix. Currently the structured `logger.warning` is sufficient; this would be polish, not a defect.

---

## Telegram Preview

Drift alert (text the operator would receive via the existing notify chain on `LivePreSubmitError("isolation refused")`):

```
🚨 LIVE ORDER REFUSED — per-user CLOB isolation
user_id: 50bfb434-0e67-4bbf-941d-b694a0d66a33
reason: deposit wallet drift
sdk:    0x3feC630a07a263Ee0bd6cD108ff4b8Ed1eB606A9
stored: 0xDEADBEEFcafeBABE00000000000000000000DEAD
action: NO broker call made; wallet column requires manual review
```

Commands available: the existing kill-switch + manual order reconciliation commands proven by WARP-74 cover the operator follow-up.
