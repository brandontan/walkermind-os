# WARP•SENTINEL Validation — admin-live-truth rerun

## Verdict

**CHANGES_REQUIRED**

Rerun timestamp: `2026-06-12 14:11` Asia/Jakarta.

PR #1771 / lane branch `WARP/root-admin-live-truth` remains blocked at the mandatory WARP🔹CMD pre-check. The `/admin/users` endpoint still duplicates the live-ledger predicate instead of deriving it from the canonical wallet ledger helper, so full MAJOR validation did **not** proceed.

## Scope Validated

Mandatory pre-check only:

1. `projects/polymarket/crusaderbot/webtrader/backend/router.py` must avoid duplicating the live ledger predicate when `live_ledger_filter_sql("l")` is available and is the canonical wallet ledger source.
2. `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` must use the full repo-root forge report path `projects/polymarket/crusaderbot/reports/forge/admin-live-truth.md` for this lane.

Result:

- Item 1: **FAIL** — duplicated live ledger predicate remains in `/admin/users`.
- Item 2: **NOT THE CURRENT BLOCKER** — the current state artifact records this Sentinel status and the required full repo-root path; full validation still stops because Item 1 failed.

## Evidence

### Mandatory pre-check item 1 — live ledger filtering is still duplicated

`projects/polymarket/crusaderbot/webtrader/backend/router.py` imports `live_ledger_filter_sql`, and the same file already uses it in wallet ledger endpoints, but `/admin/users` still hand-copies the live-money bucket predicate.

Evidence from `admin_users`:

```text
projects/polymarket/crusaderbot/webtrader/backend/router.py:3134-3148
-- live-mode-truth (admin surface): the user's REAL money
-- bucket, same definition as wallet.ledger live filter.
COALESCE((SELECT SUM(l.amount_usdc) FROM ledger l
          WHERE l.user_id = u.id
            AND ( (l.type = 'deposit' AND l.ref_id IS NOT NULL
                   AND EXISTS (SELECT 1 FROM deposits dd
                               WHERE dd.id = l.ref_id))
                  OR l.type = 'withdraw'
                  OR (l.type = 'adjustment' AND EXISTS (
                        SELECT 1 FROM withdrawals wd
                        WHERE wd.id = l.ref_id))
                  OR EXISTS (SELECT 1 FROM positions lp
                             WHERE lp.id = l.ref_id
                               AND lp.mode = 'live') )), 0)
    AS live_balance_usdc,
```

Canonical helper presence and current router usage:

```text
projects/polymarket/crusaderbot/wallet/ledger.py:116:def live_ledger_filter_sql(alias: str = "l") -> str:
projects/polymarket/crusaderbot/webtrader/backend/router.py:1597:        _flt = live_ledger_filter_sql("l")
projects/polymarket/crusaderbot/webtrader/backend/router.py:1653:        _flt = live_ledger_filter_sql("l")
```

**Required fix before Sentinel can continue:** build the `/admin/users` live balance expression from `live_ledger_filter_sql("l")` or another single canonical helper approved by WARP🔹CMD. The admin roster must not maintain a hand-copied predicate for custody/live-money truth.

### Mandatory pre-check item 2 — state path check

The current project state records this Sentinel result and uses full repo-root paths for the lane's report references. This item is not the current stop reason on rerun. The remaining hard stop is the duplicated SQL predicate above.

## Required Evidence Not Reached

Because mandatory pre-check item 1 failed, WARP•SENTINEL did **not** continue into approval-oriented validation. The following checks remain unvalidated by this report:

- `AsyncSecureClient.create(...)` call-site audit for `environment=production_environment()` and `api_key=...`.
- `RELAYER_API_KEY` + `RELAYER_API_KEY_ADDRESS` mapping to `RelayerApiKey` and precedence over builder credentials.
- `/admin/users` semantic mode-scoping beyond the pre-check evidence.
- Admin Backfill UI deposit-wallet and safes summary rendering behavior.
- Targeted pytest/backend/admin/frontend validation commands.
- Live-trading guard, risk constant, Kelly sizing, bankroll, and order-placement guard audit.

No approval is implied for any unreached item.

## Commands Run

| Command | Result |
|---|---|
| `pwd && sed -n '1,220p' AGENTS.md && sed -n '1,220p' PROJECT_REGISTRY.md` | PASS — confirmed repo root, governing instructions, and active CrusaderBot project. |
| `git status --short && git log --oneline -5 && sed -n '1,8p' projects/polymarket/crusaderbot/state/PROJECT_STATE.md && sed -n '1,220p' projects/polymarket/crusaderbot/reports/forge/admin-live-truth.md` | PASS — loaded current state and forge context. |
| `nl -ba projects/polymarket/crusaderbot/webtrader/backend/router.py \| sed -n '3118,3168p' && rg -n "live_ledger_filter_sql\(" projects/polymarket/crusaderbot/webtrader/backend/router.py projects/polymarket/crusaderbot/wallet/ledger.py` | FAIL for validation gate — confirmed duplicated `/admin/users` live ledger predicate remains while the canonical helper exists. |
| `python3 - <<'PY' ... state path reference scan ... PY` | PASS — inspected current state path text; state path is not the active rerun blocker. |

Not run due mandatory stop gate:

- `python -m pytest projects/polymarket/crusaderbot/tests/test_gasless_custody.py projects/polymarket/crusaderbot/tests/test_sdk_rpc_pin.py`
- Targeted backend/admin tests.
- Frontend type/build validation for `projects/polymarket/crusaderbot/webtrader/frontend`.

## Files Inspected

- `AGENTS.md`
- `PROJECT_REGISTRY.md`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/reports/forge/admin-live-truth.md`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
- `projects/polymarket/crusaderbot/wallet/ledger.py`

## Critical Issues

1. **Duplicated live ledger predicate in `/admin/users`.** The endpoint still hand-copies the live-money bucket predicate even though `live_ledger_filter_sql("l")` is available and already used elsewhere in `router.py`.

## Non-Blocking Issues

None assessed. Broader validation did not proceed after the mandatory pre-check failure.

## Merge Recommendation for WARP🔹CMD

**Do not merge PR #1771 yet.** Return to WARP•FORGE/WARP•R00T for the remaining mandatory batch-fix item, then re-run WARP•SENTINEL validation from the beginning.

Required next fix:

1. Centralize `/admin/users` live ledger filtering through `live_ledger_filter_sql("l")` or an equivalent single source of truth.

State: `CHANGES_REQUIRED` — mandatory pre-check rerun failed at 2026-06-12 14:11 Asia/Jakarta.
