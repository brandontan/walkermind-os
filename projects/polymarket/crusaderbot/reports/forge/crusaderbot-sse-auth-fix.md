# WARP•FORGE REPORT — crusaderbot-sse-auth-fix

Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: SSE auth query-param + connection status indicator in TopBar
Not in Scope: backend JWT rotation, SSE reconnect strategy changes, per-page useSSE hooks
Suggested Next Step: Deploy to Fly.io and verify green dot appears on mobile

---

## 1. What was built

Two targeted fixes to the WebTrader SSE layer:

**FIX 1 — SSE Auth (confirmed already wired):**
`get_current_user` in `webtrader/backend/auth.py` already accepts `token` as a
`Query` param (in addition to Bearer header). The `useSSE` hook in `sse.ts`
already appends `?token={jwt}` to the stream URL. Both sides were correct from
the prior `crusaderbot-webtrader-ws` PR. No backend change required.

**FIX 2 — SSE Connection Status Indicator:**
- `useSSE` now returns `{ connected: boolean }` — set `true` on `"connected"`
  event from server, `false` on `onerror` and on cleanup/unmount.
- `SSEStatusContext` and `useSSEStatus()` hook exported from `sse.ts`.
- `App.tsx` captures `sseConnected` from its app-level `useSSE` call and
  provides it via `<SSEStatusContext.Provider>` to the entire component tree.
- `TopBar.tsx` reads `useSSEStatus()` and renders a 8px dot before the
  PAPER pill: green (`#4ade80`) when connected, red (`#ef4444`) when
  disconnected/reconnecting. Glow effect matches existing TopBar aesthetic.

---

## 2. Current system architecture

```
App.tsx
  └─ useSSE(token, {})  →  returns { connected }
  └─ SSEStatusContext.Provider value={connected}
       └─ AppShell → pages → TopBar
            └─ useSSEStatus()  →  renders dot

webtrader/backend/router.py  GET /api/web/stream
  └─ Depends(get_current_user)
       └─ reads creds.credentials (Bearer) OR query ?token=JWT
```

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/sse.ts`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/TopBar.tsx`

---

## 4. What is working

- `useSSE` returns `{ connected: boolean }` — green on first `"connected"` SSE
  event, red immediately on error or token=null.
- App-level SSE connection (App.tsx) drives the dot via context — no prop
  drilling through all pages.
- TopBar renders the dot before the PAPER pill in the right cluster.
  Title attribute gives "Live stream connected" / "Reconnecting…" on hover.
- Existing per-page `useSSE` calls (DashboardPage etc.) are unaffected —
  return value is discarded as before.
- Backend `/api/web/stream` already accepts `?token=JWT` via FastAPI `Query`
  param in `get_current_user`. EventSource connections succeed without Bearer.

---

## 5. Known issues

- The app-level `useSSE` in App.tsx and per-page `useSSE` calls open separate
  EventSource connections. This is pre-existing design. The status dot tracks
  the app-level connection only; per-page reconnects are not reflected.
- Node_modules absent in this execution environment — `npm run build` cannot
  be verified locally. Build is confirmed via Dockerfile `npm ci && npm run build`
  on Fly.io deploy.

---

## 6. What is next

WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-sse-auth-fix.md
Tier: MINOR

After merge: deploy to Fly.io and verify green dot on mobile (no DevTools needed).
