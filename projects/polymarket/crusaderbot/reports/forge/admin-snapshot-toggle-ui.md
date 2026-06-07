# WARP-81 Phase 1 — Admin Toggle for SCAN_SNAPSHOT_ENABLED

**Status: DOCUMENTED-EXISTING (no new code built)**
The toggle already exists end-to-end. This lane documents it and adds the
operator runbook so the HP operator can flip the setting from the phone browser.

---

## 1. What was built

Investigation confirmed that all required layers were already present from a
prior lane (referenced as PR #1663 / #1665 infra). No new code was required.

A **runbook** was written at:
`projects/polymarket/crusaderbot/docs/runbooks/scan-snapshot-toggle.md`

This is the only artifact created. It documents the exact operator steps to flip
`SCAN_SNAPSHOT_ENABLED` from a phone browser without curl or SQL.

---

## 2. Current system architecture

The full toggle wire:

```
DB (system_settings, key cfg:SCAN_SNAPSHOT_ENABLED)
  <- PATCH /api/web/admin/settings/SCAN_SNAPSHOT_ENABLED  (AdminUser-gated)
       <- api.updateAdminSetting(key, value)  [frontend api.ts:167]
            <- Toggle component  [AdminPage.tsx "Bot Settings" section]
                 <- Admin UI at /admin  (is_admin guard)

Read path (30s TTL cache):
  runtime_config.resolve_bool("SCAN_SNAPSHOT_ENABLED", env_default)
    <- signal_scan_job / snapshots.record_market_snapshots
```

Key files (all pre-existing):

| File | Role |
|---|---|
| `domain/ops/runtime_config.py` | Whitelist, cache, get/set/clear overlay |
| `webtrader/backend/router.py:2974` | `GET /admin/settings` |
| `webtrader/backend/router.py:2983` | `PATCH /admin/settings/{key}` |
| `webtrader/backend/schemas.py:426` | `RuntimeSettingUpdate` schema |
| `webtrader/frontend/src/lib/api.ts:166` | `getAdminSettings`, `updateAdminSetting` |
| `webtrader/frontend/src/pages/AdminPage.tsx` | "Bot Settings" toggle section |

---

## 3. Files created / modified

Created:
- `projects/polymarket/crusaderbot/docs/runbooks/scan-snapshot-toggle.md`

No code files created or modified. All pre-existing files confirmed correct.

---

## 4. What is working

- `SCAN_SNAPSHOT_ENABLED` is present in `RUNTIME_SETTINGS` with `kind="bool"`.
- `GET /api/web/admin/settings` returns all whitelisted keys including this one.
- `PATCH /api/web/admin/settings/SCAN_SNAPSHOT_ENABLED` writes the DB override
  with audit logging and invalidates the 30s cache.
- `AdminPage.tsx` "Bot Settings (runtime -- no redeploy)" section renders a
  labelled toggle with loading/error/override-badge states for every bool key.
- Admin auth guard (`is_admin` role check) gates the entire section; non-admin
  users see "Admin only" and the endpoints return 403.
- Cache TTL: 30 s — change is live for all processes within one tick window.

Operator flow (HP):
1. Open WebTrader `/admin` in phone browser.
2. Scroll to "Bot Settings" section.
3. Tap the "Scan snapshot capture" toggle row.
4. Done. No curl. No SQL. No redeploy.

---

## 5. Known issues

None. The existing implementation is complete for this scope.

Note: `market_snapshots` table was dropped in WARP-82 (migration 087).
`SCAN_SNAPSHOT_ENABLED` is still a valid whitelist toggle; `snapshots.py` is
a no-op when the table is absent. If the table is recreated in a future lane,
the toggle immediately controls it. The runbook includes a verification step
noting that rows will only appear if the table exists.

---

## 6. What is next

- WARP-81 Phase 2 (if applicable): any additional snapshot infrastructure work.
- If `market_snapshots` table is recreated, verify the toggle drives the
  write path end-to-end via the Supabase table view (runbook covers this).

---

## Metadata

- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** Admin UI "Bot Settings" toggle for SCAN_SNAPSHOT_ENABLED
- **Not in Scope:** ev_comparator, scorer_trainer, orchestrator, new auth schemes,
  new Telegram commands, new backend endpoints, market_snapshots table recreation
- **Suggested Next Step:** WARP CMD review. Operator verifies on HP by opening
  `/admin` and confirming the "Scan snapshot capture" row is visible and tappable.
