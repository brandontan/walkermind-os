# WARP-76 H4 — Multi-user isolation audit

Branch: WARP/isolation-audit
Role: WARP•R00T (executing as audit/fix)
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: every SELECT/UPDATE/INSERT/DELETE on positions / orders / wallets / user_settings / signal_publications / ledger in user-facing handlers + scan paths is per-user scoped (or operator-only by design).
Not in Scope: ENABLE_LIVE_TRADING / USE_REAL_CLOB / live exec path / risk gate.py / DB schema / migrations.
Suggested Next Step: WARP🔹CMD review + merge. With H1–H4 landed, WARP-76 (M1 PAPER-public gate) is complete.

## 1. What was built

A full static + runtime audit of per-user isolation across the 6 sensitive
tables in every user-facing handler and scan path, following the WARP-69
file:fn:line PASS/FAIL pattern. **One** cross-user leak was found and **fixed in
this PR**, plus a hermetic cross-user leakage test suite.

### Audit summary

| Status | Count | Meaning |
|---|---:|---|
| ✅ PASS | 140 | per-user scoped (`WHERE user_id=$N` / INSERT sets caller's user_id / id derived from the caller's own scope) |
| ❌ FAIL | 1 | cross-user leak — **FIXED in this PR** |
| N/A-OPERATOR | 20 | legitimately cross-user but reachable ONLY from admin/operator/scheduler paths (gated by `_is_admin_user`) |
| **Total** | **161** | all query sites on the 6 tables in scope |

### Per-table

| Table | PASS | FAIL | N/A-OP |
|---|---:|---:|---:|
| positions | 52 | 0 | 20 |
| orders | 38 | 0 | 0 |
| wallets | 12 | 0 | 0 |
| user_settings | 22 | 0 | 0 |
| signal_publications | 2 | 1 (fixed) | 0 |
| ledger | 14 | 0 | 0 |

## 2. The one FAIL — fixed

### `GET /api/web/signals/recent` — signal_publications cross-cohort leak

File: `projects/polymarket/crusaderbot/webtrader/backend/router.py` :
`get_recent_signals` : (was) lines 199–217.

Before — no per-user predicate; returned EVERY feed's signals to EVERY user:

```sql
FROM signal_publications sp
LEFT JOIN markets m ON m.id = sp.market_id
WHERE sp.exit_signal = FALSE
  AND sp.published_at >= NOW() - INTERVAL '4 hours'
ORDER BY sp.published_at DESC LIMIT $1
```

`signal_publications` is keyed by `feed_id`; users subscribe via
`user_signal_subscriptions` (migration 010). A user therefore saw entry signals
from feeds they never subscribed to — an information leak across subscriber
cohorts (MEDIUM: disclosure, not capital).

After — scoped to the caller's ACTIVE subscriptions, mirroring the strategy-plane
read contract (`services/signal_feed/signal_evaluator._load_active_subscriptions`
+ `_load_active_publications`): active subscription, active feed, entry signals
published AFTER the user subscribed, not expired:

```sql
FROM signal_publications sp
JOIN user_signal_subscriptions s
  ON s.feed_id = sp.feed_id AND s.user_id = $1::uuid AND s.unsubscribed_at IS NULL
JOIN signal_feeds f ON f.id = sp.feed_id AND f.status = 'active'
LEFT JOIN markets m ON m.id = sp.market_id
WHERE sp.exit_signal = FALSE
  AND sp.published_at >= NOW() - INTERVAL '4 hours'
  AND sp.published_at > s.subscribed_at
  AND (sp.expires_at IS NULL OR sp.expires_at > NOW())
ORDER BY sp.published_at DESC LIMIT $2
```

The authenticated `user["user_id"]` is now the first bound parameter.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/tests/test_warp76_isolation.py`
- `projects/polymarket/crusaderbot/reports/forge/isolation-audit.md`

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (`/signals/recent` scoped to subscriptions)

## 4. What is working

- `tests/test_warp76_isolation.py` (2 passed):
  - SQL-contract: the executed query joins `user_signal_subscriptions` on
    `s.user_id = $1::uuid AND s.unsubscribed_at IS NULL`, and the caller's id is
    the first bound parameter.
  - Cross-user leakage: with a fake conn honouring the `user_id` parameter,
    user A receives only their subscribed feed's signals and user B only theirs
    — markets are disjoint, no leak.
- Regression: `test_isolation_audit.py` (WARP-69, RecordingConn runtime checks)
  + `test_webtrader_positions.py` → 29 passed; router edit non-regressing.
- `ruff check` (project config) on changed files: clean.

### Exemplar PASS queries (verified)

- positions — `webtrader/backend/router.py:get_activity` `WHERE p.user_id = $1::uuid`; `bot/handlers/positions.py` `WHERE p.user_id = $1`; `domain/execution/live.close_position` `WHERE id=$1 AND user_id=$2 AND status='open'`.
- orders — `domain/execution/paper.execute` / `live.execute` INSERT set `user_id`.
- wallets / ledger — `wallet/ledger.py` INSERT ledger sets `user_id`; UPDATE wallets `WHERE user_id=$2`.
- user_settings — `webtrader/backend/router.py` UPDATE `WHERE user_id=$N::uuid`; `bot/handlers/strategy.py` `WHERE user_id=$2`.

### N/A-OPERATOR (safe cross-user)

20 aggregate/system reads in `bot/handlers/admin.py` + `webtrader/backend/router.py` admin endpoints (e.g. `COUNT(*) FROM positions WHERE status='open'`), each gated by `_is_admin_user()` (telegram_user_id == OPERATOR_CHAT_ID or tier == ADMIN); plus the operator daily-summary aggregate (WARP-76 H2) and the scan/reconcile sweeps that iterate all enrolled users via `_load_enrolled_users()`. None are reachable by a non-admin user.

## 5. Known issues

- None introduced. The audit found a single user-facing leak, now fixed; all
  other user-facing queries are per-user scoped.
- Defense-in-depth follow-ups (out of scope, optional): DB-level user-scoped
  VIEWs and an access audit-trail for signal reads — recommended, not required
  for M1.

## 6. What is next

- WARP🔹CMD review + merge of WARP/isolation-audit.
- WARP-76 (M1 PAPER-public hardening) complete across H1–H4 once all four merge.
