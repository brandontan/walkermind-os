# Operator Runbook: Toggling SCAN_SNAPSHOT_ENABLED

WARP-81 | Last Updated: 2026-06-07

## What this does

`SCAN_SNAPSHOT_ENABLED` controls whether each scan tick persists the raw
full-universe market state to `market_snapshots`.  It is append-only telemetry
(walk-forward replay substrate); it has **no effect on trading**.

The toggle lives in the Admin UI — no curl, no SQL, no redeploy required.

---

## Steps (mobile-friendly, ~30 seconds)

1. Open WebTrader in your phone browser.
2. Tap the bottom-nav item **Admin** (or navigate to `/admin`).
   - If you see "Admin only" — your session token has the wrong role; re-login.
3. Scroll to the **"Bot Settings (runtime — no redeploy)"** section.
4. Find the row labelled **"Scan snapshot capture"**.
5. Tap the toggle to flip ON or OFF.
   - The row shows the current state: `ON` (green) / `OFF` (grey).
   - A small **"● override"** badge appears when the DB value differs from the
     Fly/env default — that means your tap is active.
6. The change takes effect within **~30 seconds** (cache TTL) — no redeploy.

---

## Verification

After toggling, wait one scan tick (~30-60 s) and check:

- Telegram `/health` or the Admin console still shows the bot running.
- If you turned it ON: `market_snapshots` rows appear in Supabase table
  view after the next tick — **only if the `market_snapshots` table exists**.
  The table was dropped in WARP-82 (migration 087), so until it is recreated
  this capture is a no-op and no rows will appear (the toggle flips cleanly,
  but there is nowhere to write).
- If you turned it OFF: no new rows are appended (existing rows stay).

---

## Reset to default

Tap the toggle back to the other state, **or** run via Supabase SQL if the UI
is unavailable:

```sql
DELETE FROM system_settings WHERE key = 'cfg:SCAN_SNAPSHOT_ENABLED';
```

This removes the DB override; the bot falls back to the Fly/env default within
30 s.

---

## Technical reference

| Layer | Location |
|---|---|
| Whitelist + validation | `domain/ops/runtime_config.py` -- `RUNTIME_SETTINGS["SCAN_SNAPSHOT_ENABLED"]` |
| Backend endpoints | `GET /api/web/admin/settings`, `PATCH /api/web/admin/settings/SCAN_SNAPSHOT_ENABLED` |
| Frontend toggle | `webtrader/frontend/src/pages/AdminPage.tsx` -- "Bot Settings" section |
| DB persistence | `system_settings` table, key `cfg:SCAN_SNAPSHOT_ENABLED` |
| Cache TTL | 30 s (applies across all Fly instances on next read) |
