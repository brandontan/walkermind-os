# admin-user-detail-500-fix

**Role:** WARP•R00T
**Validation Tier:** STANDARD (runtime behaviour fix — admin Ops Console read path)
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `admin_user_detail` route (`webtrader/backend/router.py:2585`) recent-trades SELECT + row mapping
**Not in Scope:** other admin endpoints; settings PATCH path; AdminUserDrawer frontend

---

## 1. What was built

Hotfix for owner-reported 500 on the WebTrader admin User Detail drawer. The `admin_user_detail` handler's `recent_trades` SELECT referenced `p.created_at` on the `positions` table, but `positions` only has `opened_at` + `closed_at` (no `created_at` column). Every drawer open raised `UndefinedColumnError` → FastAPI converted to HTTP 500 → drawer body rendered "Internal Server Error".

Bug introduced by `WARP/R00T/admin-drawer-complete` (commit 29aaa88, 2026-05-30). Shipped because the existing tests mocked `trade_rows` as `[]`, so the SELECT was prepared but the row-mapping path was never exercised — the column-name mismatch only surfaces when PostgreSQL actually executes the prepared statement against a real `positions` row.

**Fix (3 lines in `webtrader/backend/router.py`):**

1. Line 2630: `p.created_at` → `p.opened_at` in SELECT column list
2. Line 2635: `COALESCE(p.closed_at, p.created_at)` → `COALESCE(p.closed_at, p.opened_at)` in ORDER BY
3. Line 2661: `r["closed_at"] or r["created_at"]` → `r["closed_at"] or r["opened_at"]` in `AdminRecentTrade` ts mapping

All 4 other position-read SELECTs in the same file already use `p.opened_at` correctly (lines 239, 244, 454, 462, 1785) — this was an isolated regression.

**Test pin:** added `test_admin_user_detail_recent_trades_uses_opened_at` to `test_admin_console.py` — populates `trade_rows` with one fully-formed row (key `opened_at` present, not `created_at`), asserts the returned `AdminRecentTrade.ts` matches the row's `opened_at`, and asserts the issued SQL string contains `p.opened_at` and does NOT contain `p.created_at`. The string-check is the regression guard so a future copy-paste edit cannot silently reintroduce the bug.

---

## 2. Current system architecture

```text
WebTrader admin drawer → GET /api/web/admin/users/{user_id}
  ↓
admin_user_detail()
  ├─ users SELECT (u_row)
  ├─ user_settings SELECT (s_row)
  ├─ wallets SELECT (w_row)
  ├─ positions COUNT (open_count)
  ├─ positions SELECT recent_trades (5 rows)        ← FIX HERE: opened_at not created_at
  └─ audit.log SELECT recent_audit (3 rows)
  ↓
AdminUserDetail response model
  ├─ recent_trades: list[AdminRecentTrade]          ← FIX HERE: row["opened_at"] not row["created_at"]
  └─ recent_audit:  list[AdminRecentAudit]
```

---

## 3. Files created/modified

```text
projects/polymarket/crusaderbot/webtrader/backend/router.py                            (MODIFIED — 3 lines, lines 2630/2635/2661)
projects/polymarket/crusaderbot/tests/test_admin_console.py                            (MODIFIED — 1 new regression test, ~38 lines)
projects/polymarket/crusaderbot/reports/forge/admin-user-detail-500-fix.md             (NEW)
projects/polymarket/crusaderbot/state/PROJECT_STATE.md                                 (sections updated)
projects/polymarket/crusaderbot/state/CHANGELOG.md                                     (one-line append)
```

---

## 4. What is working

| Check | Result |
|---|---|
| Empty trade_rows → returns view (existing) | PASS |
| Populated trade_rows → ts == opened_at, SQL contains `p.opened_at` and not `p.created_at` (new) | PASS — `test_admin_user_detail_recent_trades_uses_opened_at` |
| 404 when user missing (existing) | PASS |
| 400 when user_id not a UUID (existing) | PASS |
| `@telegram.local` email stripped (existing) | PASS |
| Missing user_settings → paper/balanced defaults (existing) | PASS |
| Full `test_admin_console.py` suite | PASS — 51/51 |
| `ruff check` | PASS |
| `py_compile` | PASS |

---

## 5. Known issues

None introduced. The 4 other position-read sites in the same file were verified to use `p.opened_at` correctly — no copy-paste contamination beyond the admin_user_detail handler.

---

## 6. What is next

**Immediate:** merge + redeploy. Owner can re-open the User Detail drawer in WebTrader admin once Fly CD ships.

**No further follow-up required.** The new regression test pins the column name in the issued SQL so future edits cannot silently regress.

**Suggested Next Step:** WARP🔹CMD review + merge. Tier: STANDARD — no WARP•SENTINEL run required.

---

**WARP•R00T self-validated.** 51/51 tests pass. `ruff` + `py_compile` clean.
