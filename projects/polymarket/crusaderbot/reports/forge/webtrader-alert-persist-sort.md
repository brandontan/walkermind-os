# WARP•FORGE Report — webtrader-alert-persist-sort

Branch: WARP/webtrader-alert-persist-sort
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader alert read-state persistence + closed-trade sort order
Not in Scope: strategy entry behaviour (safe_close kept conservative by owner decision), timezone formatting (owner chose device-local — already current behaviour)

---

## 1. What was built

Two owner-reported WebTrader fixes from live-app feedback:

- **Read alerts no longer reappear after reload.** Dismissed alert IDs were tracked only in memory, so tapping × dismissed an alert for the session but it returned on the next page load. Dismissed IDs are now persisted to `localStorage` (`alertCenter_dismissed`, capped at 500 most-recent ids to bound storage). Restored on mount via `loadDismissed()`.

- **Closed trades sort newest-first by close time.** The `/positions` query ordered by `opened_at DESC`, so a trade that opened earlier but closed most recently sank down the list. Now orders by `COALESCE(closed_at, opened_at) DESC` — closed positions sort by when they closed, open positions still fall back to open time. The Portfolio "All" tab client-side sort was aligned to the same recency rule.

Two other feedback items required no code change:
- **safe_close opening few positions** — confirmed by-design (late_entry_v3 with strict 30–60s-before-close window + favorite ≥60%); owner chose to keep it conservative.
- **Timezone** — owner chose device-local, which is already the existing behaviour (all `toLocale*` calls use the browser zone).

---

## 2. Current system architecture

```
AlertCenter (bell)
  ├─ alerts: system alerts + closed-trade alerts (SSE-refreshed)
  ├─ dismissed: Set<string> ← localStorage "alertCenter_dismissed" (NEW: persisted, cap 500)
  ├─ visibleAlerts = alerts − dismissed
  ├─ unreadCount   = visibleAlerts newer than lastSeen (unchanged)
  └─ dismissAlert(id) → add id + persist to localStorage (NEW)

GET /positions (open | closed | all)
  └─ ORDER BY COALESCE(closed_at, opened_at) DESC   (was: opened_at DESC)

PortfolioPage "All" tab
  └─ client sort by closed_at ?? opened_at DESC      (was: opened_at DESC)
```

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx` — `loadDismissed()` + `DISMISSED_KEY`/`DISMISSED_CAP`; `dismissed` initialised from localStorage; `dismissAlert` persists with cap.
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `/positions` ORDER BY → `COALESCE(p.closed_at, p.opened_at) DESC`.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx` — `allPositions` recency sort uses `closed_at ?? opened_at`.

Created:
- `projects/polymarket/crusaderbot/reports/forge/webtrader-alert-persist-sort.md` (this file)

---

## 4. What is working

- `npm run build` (`tsc && vite build`) → exit 0, clean
- `py_compile webtrader/backend/router.py` → OK
- Dismissed alerts persist across reloads (localStorage), bounded at 500 ids
- Closed-trade list and All tab order most-recently-closed on top; open positions unaffected (fall back to opened_at)

---

## 5. Known issues

- Dismissed-id store is per-browser (localStorage), not synced server-side — clearing browser data resets dismissals. Acceptable for the notification tray UX.
- F-HIGH-2 secondary path (Phase C `evaluate_publications_for_user` yielding 0 candidates) remains a separate open follow-up, unrelated to this lane.

---

## 6. What is next

- WARP🔹CMD: review + merge + fly deploy (STANDARD, paper-safe — no trading-logic change).
- Optional future: server-side read-state if cross-device alert sync is desired.

Suggested Next Step: WARP🔹CMD review + merge. STANDARD tier.
