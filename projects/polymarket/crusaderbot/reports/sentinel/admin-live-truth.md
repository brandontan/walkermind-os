# WARP•SENTINEL Validation — admin-live-truth

## Verdict

**CHANGES_REQUIRED**

PR #1771 (`WARP/root-admin-live-truth` @ `26b548d14ff65332b8c08d925cf160750091c6f5`) did **not** pass the mandatory WARP🔹CMD batch-fix pre-check. Per task instruction, validation stopped before optimistic approval or broader runtime validation.

## Scope Validated

Mandatory pre-check only:

1. `projects/polymarket/crusaderbot/webtrader/backend/router.py` must avoid duplicating the live ledger predicate when `live_ledger_filter_sql("l")` is available and is the canonical wallet ledger source.
2. `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` must reference the forge report with the full repo-root path `projects/polymarket/crusaderbot/reports/forge/admin-live-truth.md`.

Full MAJOR validation of `/admin/users`, Admin Backfill rendering, SDK gasless `api_key` wiring, and live-trading guard invariants was **not reached** because both mandatory pre-check items remain unresolved.

## Evidence

### Mandatory pre-check item 1 — live ledger filtering is duplicated

**Status: FAIL**

`projects/polymarket/crusaderbot/webtrader/backend/router.py` imports the canonical helper:

```python
from ...wallet.ledger import get_live_balance, live_ledger_filter_sql
```

But `/admin/users` still embeds a hand-copied live-money SQL predicate instead of reusing `live_ledger_filter_sql("l")`. Evidence from `admin_users`:

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

This is the exact drift WARP🔹CMD flagged: admin live balance truth depends on a duplicated predicate even though the wallet ledger helper is present and already imported.

**Required fix:** build the `/admin/users` live balance expression from `live_ledger_filter_sql("l")` (or another single canonical helper if WARP🔹CMD chooses one) so wallet and admin live-money truth cannot silently diverge.

### Mandatory pre-check item 2 — PROJECT_STATE report reference is short-form

**Status: FAIL**

`projects/polymarket/crusaderbot/state/PROJECT_STATE.md` contained this short-form report reference at mandatory pre-check time:

```text
Report: reports/forge/admin-live-truth.md.
```

The required full repo-root path is:

```text
Report: projects/polymarket/crusaderbot/reports/forge/admin-live-truth.md.
```

This violates the task's explicit mandatory pre-check and the repo path-format rule for actual state artifacts.

## Required Evidence Not Reached

Because the mandatory pre-check failed, WARP•SENTINEL did **not** continue into approval-oriented validation; only the report/state/changelog artifacts were updated afterward to record this verdict. The following required checks remain unvalidated by this report:

- `AsyncSecureClient.create(...)` call-site audit for `environment=production_environment()` and `api_key=...`.
- `RELAYER_API_KEY` + `RELAYER_API_KEY_ADDRESS` mapping to `RelayerApiKey` and precedence over builder credentials.
- `/admin/users` semantic mode-scoping beyond the pre-check evidence.
- Admin Backfill UI deposit-wallet + safes rendering behavior.
- Targeted pytest/backend/admin/frontend validation commands.
- Live-trading guard/risk/Kelly/order-placement invariant audit.

No approval is implied for any unreached item.

## Commands Run

| Command | Result |
|---|---|
| `pwd && sed -n '1,220p' AGENTS.md && sed -n '1,220p' PROJECT_REGISTRY.md` | PASS — confirmed repo root, governing instructions, and active CrusaderBot project. |
| `sed -n '1,260p' projects/polymarket/crusaderbot/state/PROJECT_STATE.md && sed -n '1,220p' projects/polymarket/crusaderbot/state/ROADMAP.md && sed -n '1,220p' projects/polymarket/crusaderbot/state/WORKTODO.md && sed -n '1,260p' projects/polymarket/crusaderbot/state/CHANGELOG.md` | PASS — state context loaded; output was truncated by terminal due file size, but top state line and relevant current status were visible. |
| `git status --short && git branch --show-current && git rev-parse HEAD && rg -n "live_ledger_filter_sql|ledger|admin/users|live_balance|trading_mode" projects/polymarket/crusaderbot/webtrader/backend/router.py && rg -n "admin-live-truth|reports/forge/admin-live-truth|projects/polymarket/crusaderbot/reports/forge/admin-live-truth" projects/polymarket/crusaderbot/state/PROJECT_STATE.md` | FAIL for validation gate — found duplicated `/admin/users` live ledger predicate and short-form PROJECT_STATE report reference. |
| `sed -n '3110,3190p' projects/polymarket/crusaderbot/webtrader/backend/router.py` | PASS command, FAIL evidence — confirmed duplicated SQL predicate at `/admin/users`. |
| `python3 - <<'PY' ... find report references ... PY` | PASS command, FAIL evidence — confirmed required full repo-root forge report path absent and short-form path present. |
| `nl -ba projects/polymarket/crusaderbot/webtrader/backend/router.py | sed -n '3128,3157p' && nl -ba projects/polymarket/crusaderbot/state/PROJECT_STATE.md | sed -n '1,8p'` | PASS command, FAIL evidence — captured exact line evidence for both blockers. |

Not run due mandatory stop gate:

- `python -m pytest projects/polymarket/crusaderbot/tests/test_gasless_custody.py projects/polymarket/crusaderbot/tests/test_sdk_rpc_pin.py`
- Targeted backend/admin tests.
- Frontend type/build validation for `projects/polymarket/crusaderbot/webtrader/frontend`.

## Files Inspected

- `AGENTS.md`
- `PROJECT_REGISTRY.md`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/ROADMAP.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`

## Critical Issues

1. **Duplicated live ledger predicate in `/admin/users`.** The endpoint still hand-copies the live-money bucket predicate instead of using the canonical wallet ledger helper already imported in the same file.
2. **State artifact path-format drift.** `PROJECT_STATE.md` uses `reports/forge/admin-live-truth.md` instead of the required full repo-root path.

## Non-Blocking Issues

None assessed. Broader validation did not proceed after mandatory pre-check failure.

## Merge Recommendation for WARP🔹CMD

**Do not merge PR #1771 yet.** Return to WARP•FORGE/WARP•R00T for the two mandatory batch-fix items, then re-run WARP•SENTINEL validation from the beginning:

1. Centralize `/admin/users` live ledger filtering through `live_ledger_filter_sql("l")` or an equivalent single source of truth.
2. Replace the `PROJECT_STATE.md` report reference with `projects/polymarket/crusaderbot/reports/forge/admin-live-truth.md`.

State: `CHANGES_REQUIRED` — mandatory pre-check failed at 2026-06-12 12:23 Asia/Jakarta.
