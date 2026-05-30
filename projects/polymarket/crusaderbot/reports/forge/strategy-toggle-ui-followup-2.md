# WARP•R00T FORGE REPORT — strategy-toggle-ui-followup-2

Branch: `WARP/ROOT/strategy-toggle-ui-followup-2`
Role: WARP•R00T (owner-reported gaps after #1466 deploy)
Validation Tier: MAJOR (dashboard chrome + persistence path)
Claim Level: NARROW INTEGRATION

## 1. What was built

Closes 3 owner-reported gaps remaining after the previous followup PR (#1466,
`WARP/R00T/strategy-toggle-ui-followup`) shipped:

1. **Hero pause visualisation** — the AutoTradePage hero's green pulse dot and
   red "🛑 STOP AUTO TRADE" CTA were hardcoded. When an operator admin-paused
   the user's active preset's backing strategy, the only paused-state signal
   was the gold "PAUSED (ADMIN)" text below; the hero still pulsed green +
   offered a misleading red Stop CTA whose click was a flag-flip no-op while
   the scanner was disabled. `HeroCard` now accepts a
   `statusTone="active"|"paused"|"idle"` prop that drives dot colour
   (`bg-grn` / `bg-ink-3` / `bg-ink-4`), pulse animation, and label colour
   (`text-gold` / `text-ink-3` / `text-ink-4`) together. `AutoTradePage`
   passes `tone="paused"` whenever `state.active_preset_globally_enabled ===
   false`, drops the CTA branch entirely, and renders a passive 🔒 info
   banner ("The {preset} strategy is currently paused by the operator…")
   below the hero.

2. **DesktopSidebar SCANNER status** — the System Status block at the
   bottom of the sidebar reported `RUNNING` based on `auto_trade_on` alone.
   During an admin pause it kept saying RUNNING even though the scanner
   emitted no candidates. `DashboardSummary` now exposes
   `active_preset_globally_enabled` (same `_PRESET_TO_STRATEGY` lookup as
   `get_autotrade`); the sidebar fetches it from `/dashboard` and reports
   "PAUSED (ADMIN)" with warn tone, "IDLE" when the user has auto-trade
   off, "RUNNING" otherwise.

3. **AlertCenter "Mark all read" persistence** — the watermark added by
   #1466 was `localStorage`-only. A fresh device, a private window, an iOS
   quota eviction, or a browser-update storage reset all resurfaced every
   previously-acknowledged closed-position alert on next /positions fetch
   ("I mark all read but they come back after refresh"). Server-side now
   owns the canonical watermark:

   - Migration `069_user_alerts_ack_at.sql` adds
     `user_settings.alerts_ack_at TIMESTAMPTZ NULL`.
   - `POST /alerts/ack-all` upserts `NOW()` and returns the ISO-8601
     timestamp so the client can update its local filter immediately.
   - `GET /alerts` filters `created_at > alerts_ack_at` server-side (joined
     onto `user_settings`).
   - `DashboardSummary.alerts_ack_at` surfaces the value so the
     closed-position alert stream (fetched via `/positions`, not `/alerts`)
     can be filtered client-side by the same cut-off in
     `AppShell.visibleAlerts`.
   - `AppShell.markAllRead` writes optimistically to `localStorage` and
     then calls `api.ackAllAlerts()`; on success the canonical server
     timestamp ALWAYS replaces the optimistic one (no `serverMs > now`
     guard — a fast client clock would otherwise pin a future watermark
     that hides legitimate post-click alerts).

## 2. Current system architecture

```text
[admin Ops-Console] → strategies.enabled
        │
        ├─► signal_scan_job._GLOBALLY_DISABLED_STRATEGIES  (existing)
        │     scanner emits no candidates for the paused strategy
        │
        ├─► GET /autotrade.active_preset_globally_enabled  (existing)
        │     AutoTradePage hero tone + preset card badge + info banner
        │
        └─► GET /dashboard.active_preset_globally_enabled  (NEW)
              DesktopSidebar SCANNER row tone

[user_settings.alerts_ack_at]  (NEW migration 069)
        │
        ├─► GET /alerts          filters created_at > alerts_ack_at
        ├─► GET /dashboard       surfaces alerts_ack_at to client
        └─► POST /alerts/ack-all upsert NOW() + return ISO ts

[AlertCenter "Mark all read" click]
        │
        ├─► optimistic localStorage write (instant panel collapse)
        └─► api.ackAllAlerts() → server NOW() → adopt as canonical watermark
```

No trading-logic change. No new background jobs. Pure dashboard + persistence.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/migrations/069_user_alerts_ack_at.sql` (NEW)
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py`
  (`DashboardSummary.active_preset_globally_enabled`, `.alerts_ack_at`)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  (`get_dashboard` strategy-pause lookup + `alerts_ack_at` plumb; `get_alerts`
   joins `user_settings` + filters by `alerts_ack_at`; new `ack_all_alerts`
   endpoint with explicit `trading_mode='paper'` / `risk_profile='balanced'`
   per paper-default invariant)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/HeroCard.tsx`
  (`statusTone` prop driving dot/label colour + pulse)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`
  (paused-tone hero, CTA suppression, 🔒 info banner)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/DesktopSidebar.tsx`
  (`adminPaused` state, SCANNER row tone)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts`
  (`ackAllAlerts` endpoint + `DashboardSummary.active_preset_globally_enabled`,
   `.alerts_ack_at` typed)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx`
  (fold server watermark into `markAllReadAt`, POST `/alerts/ack-all` on
   click, drop the `serverMs > now` clock-skew guard)
- `projects/polymarket/crusaderbot/tests/test_admin_console.py`
  (+7: dashboard surface flag in 4 shapes, ack-all upsert + null guard,
   sanity)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (lane entry)

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/` → 1807 passed, 6 skipped,
  0 failed (35 of those touch the changed surface incl. all 7 new tests +
  the paper-default invariant for the new INSERT).
- `npx tsc --noEmit` clean.
- `npm run build` (vite) clean.
- `python -m py_compile` clean on every modified `.py`.
- 4 review findings from gemini-code-assist addressed in the same lane
  (P1 INSERT defaults, P2 type definition, P2 cast removal, P2 clock-skew
  guard removal).

## 5. Known issues

- Migration 069 MUST be applied to Supabase before the frontend deploy —
  the backend gracefully falls back to "no filter" when the column is
  missing (asyncpg raises `UndefinedColumnError`, caught upstream by
  `try/except` in `fetchAlerts`'s allSettled), but `/alerts/ack-all`
  will 500 until the column exists. Migration is idempotent (`IF NOT
  EXISTS`).
- The hero's HeroCard `idle` tone path is wired but not currently reached
  in production AutoTradePage states (user-paused with admin-enabled
  routes to `active` toggled off, which is already coded via the
  ctaPrimary "Start Auto Trade" path). Left in place because Settings /
  Portfolio pages also consume HeroCard and may legitimately need the
  idle tone in a future lane.

## 6. What is next

- WARP🔹CMD review the PR (#1467) and apply migration 069 to Supabase.
- Operator visual check after redeploy:
  - Admin-pause `late_entry_v3` → hero collapses to muted "PAUSED
    (ADMIN)" + 🔒 banner, sidebar SCANNER warn-toned, no Stop CTA.
  - Click "Mark all read" in AlertCenter → refresh page → bell stays
    at 0 (verifies server-side watermark).
  - Same check in a private window logged into the same account →
    bell stays at 0 (cross-device parity).
  - Admin-toggle `copy_trade` OFF → Copy Trade tab still hidden in
    PageTabs + DesktopSidebar + TopBar (regression check for #1466).
- Validation Tier: **MAJOR** — WARP•SENTINEL validation required before
  merge per CLAUDE.md. WARP🔹CMD decides merge after SENTINEL verdict.
- Claim Level: **NARROW INTEGRATION**
- Validation Target: AutoTradePage hero rendering paths, DesktopSidebar
  SCANNER row, AlertCenter mark-all-read persistence + filter
- Not in Scope: trading logic, signal generation, exit watcher, risk
  gate, CLOB orders, Telegram bot, wallet flows
- Suggested Next Step: WARP🔹CMD apply migration 069 to Supabase, then
  run WARP•SENTINEL, then merge after APPROVED verdict + Fly.io redeploy.
