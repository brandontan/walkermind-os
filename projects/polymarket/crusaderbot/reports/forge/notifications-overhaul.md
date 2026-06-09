# WARP•R00T REPORT — notifications-overhaul

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader AlertCenter visual + interaction refresh to match the Kreo-style notifications mockup the owner supplied (mark-all-read action, always-visible dismiss, Preferences shortcut, body-wrap, semantic SIGNAL category).
Not in Scope: Telegram alert UI, backend alert API, alert event wiring (SSE / publication path is unchanged), notification preferences storage (links to existing /settings page).
Suggested Next Step: WARP🔹CMD review. Tier: MINOR (frontend-only, no API or schema changes).

---

## 1. What was built

`components/AlertCenter.tsx` was redesigned to match the screenshot mockup:

| Surface           | Before                                           | After                                                                 |
|-------------------|--------------------------------------------------|----------------------------------------------------------------------|
| Header actions    | NEW badge + close X                              | NEW badge + **"Mark all read"** button + close X                     |
| Dismiss X         | hover-only (`opacity-0 group-hover:opacity-100`) | **always visible** — discoverable on tap devices                     |
| Body text         | `truncate` (one-line cut)                        | wraps (`whitespace-pre-line break-words`) — long titles stay readable |
| Footer            | "X shown · tap × to dismiss"                     | "X shown · click × to dismiss" + **⚙ PREFERENCES** link to /settings |
| Category icons    | TRADE / RISK / COPY / SYSTEM (4)                 | TRADE / **SIGNAL** / RISK / SYSTEM (4) — COPY merged into SIGNAL semantically; matches the screenshot's 📡 "New Signal Detected" card |
| Layout           | slide-in (380px right panel)                     | slide-in unchanged — only the contents redesigned                    |
| Mark-all-read     | implicit (lastSeen bumped on panel open)         | explicit button — dismisses ALL visible alerts + bumps lastSeen      |

### Wiring

- `App.tsx:AlertCenterCtx` gains `markAllRead: () => void`.
- New `markAllRead` implementation: appends every visible alert ID to the dismissed set (persisted to localStorage, capped at `DISMISSED_CAP`), then bumps `lastSeen` so `unreadCount` drops to 0 immediately. Idempotent and resilient to localStorage quota errors.
- The default context (used outside the provider) gets a no-op `markAllRead` so consumers never crash.
- Preferences link uses existing `react-router-dom` `useNavigate` to route to `/settings` (already in `App.tsx` routes at line 275). Panel closes when navigating so the user sees the destination, not a stale overlay.

Backend untouched. Existing alert fetch path (`api.getAlerts` + SSE `system`/`alert` event listeners in `App.tsx`) unchanged. The "Position Opened / New Signal Detected / Bot Status" examples in the mockup are the existing alert types — they already flow through `AlertItem.title` / `severity`, and `deriveCategory` maps them to the right icon via title keywords.

---

## 2. Current system architecture

```
SSE event (alert | system) ─┐
                            ├─ App.tsx fetchAlerts()
api.getAlerts() ────────────┘     ↓
                              setAlerts(...)
                                    ↓
                              visibleAlerts (filtered by dismissed set)
                                    ↓
                              AlertCenterContext.alerts
                                    ↓
                              <AlertCenter ... />
                                    ↓
   ┌──────────────────────────┬─────────────────────┐
   │ Header                   │ Card list           │ Footer
   │  • Notifications         │  • icon-by-category │  • {N} shown
   │  • {N} NEW badge         │  • title + body     │  • Preferences →
   │  • Mark all read ← NEW   │  • dismiss × ← always visible
   │  • close ×               │  • timestamp
   └──────────────────────────┴─────────────────────┘
```

No other component imports `AlertCenter` directly — it's wired into `App.tsx:269-272` as the slide-in. The change is contained to those two files.

---

## 3. Files created / modified

| Action   | Path |
|----------|------|
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx` (added `markAllRead` to context type, default, hook, provider) |
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AlertCenter.tsx` (header actions, always-visible dismiss, footer with Preferences link, body wrap, SIGNAL category rename) |
| Created  | `projects/polymarket/crusaderbot/reports/forge/notifications-overhaul.md` |

No backend / API / schema / migration changes.

---

## 4. What is working

- `tsc --noEmit` clean.
- `vite build` clean (4.33s, no warnings; bundle sizes unchanged within rounding).
- Markup follows existing Tailwind tokens (`var(--gold)`, `var(--cyan-10)`, etc.) — no new design tokens introduced.
- Backward compat: any test / consumer that imported `AlertCenterContext` continues to compile; new `markAllRead` has a no-op default.
- Empty-state copy unchanged ("No notifications yet" / "Trade closures and system events will appear here").
- Load-more pagination unchanged.

---

## 5. Known issues

- **No backend "mark all read" persistence**: `markAllRead` only touches client state (`dismissed` set in localStorage + `lastSeen`). Server-side does not track read state. A user who clears localStorage will see previously-dismissed alerts again. Out of scope for this lane — matches the existing single-user-device design.
- **Preferences link routes to /settings, not /settings#notifications**: there's no dedicated notifications section in SettingsPage today. A future lane could add an alert-preferences card there (mute by category, snooze duration, etc.). For now the link gets the user to the right page.
- **Mockup's collapsible `▲` indicator** on the header (visible in the screenshot above "NOTIFICATIONS") was intentionally NOT replicated — the slide-in panel is full-height by default; a collapse-to-pinned-card behavior would be a separate UX lane.
- **SIGNAL category rename** widens the previous COPY-only mapping to also include "signal" severity / titles. Any test that relied on `deriveCategory()` returning `"COPY"` will need to be re-aligned — none exists today (no AlertCenter tests in the suite).

---

## 6. What is next

- WARP🔹CMD review + Fly redeploy (frontend is shipped as part of the bot deploy via the WebTrader build pipeline).
- Owner-side smoke test: open the bell icon on Dashboard → verify Mark-all-read clears + Preferences opens Settings.
- Optional follow-up: add a `/api/web/alerts/mark-read` endpoint + server-side `alerts.read_at` column so dismissals survive a localStorage wipe / different browser.

---

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
