# WARP•FORGE REPORT — webtrader-emergency-stop

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader emergency-stop endpoint (kill switch + force-close all open positions) and the DesktopSidebar button that triggers it
Not in Scope: Live trading execution, Telegram emergency flow (unchanged), exit-watcher close logic (reused unchanged), kill-switch core (reused unchanged)
Suggested Next Step: WARP•SENTINEL validation required (MAJOR — touches execution/capital). Source: projects/polymarket/crusaderbot/reports/forge/webtrader-emergency-stop.md.

---

## 1. What Was Built

The WebTrader DesktopSidebar "Emergency Stop" button previously only navigated to `/dashboard` — it performed no halt despite its red styling and 🛑 label. It is now a real two-click emergency stop, per WARP🔹CMD direction: on confirm it must **close every open position at market price regardless of profit or loss**, and halt trading.

Implementation reuses existing, proven async-safe primitives — no new close logic, no change to the kill switch or exit watcher:

- **`POST /api/web/emergency-stop`** (new endpoint):
  1. `kill_switch.set_active(action="pause", …)` — activates the global kill switch (blocks all new trades), same call the existing `/kill` uses.
  2. `mark_force_close_intent_for_user(UUID(user_id))` — sets `force_close_intent=TRUE` on every open position for the user. The exit watcher consumes the flag on its next tick and closes each at current market price. This is the identical mechanism the Telegram pause+close-all flow uses.
  3. `audit.write(action="webtrader_emergency_stop_close_all", payload={positions_marked})`.
  4. Returns `{positions_marked, kill_switch_active}`.

- **DesktopSidebar button**: two-click inline confirm (Emergency Stop → "Cancel | Stop All" with a plain-language warning that all open positions close at market, profit or loss). On confirm it calls `api.postEmergencyStop()` then navigates to `/dashboard` to surface the halted state.

---

## 2. Current System Architecture

```
WebTrader sidebar "Emergency Stop"
  → POST /api/web/emergency-stop
      ├─ kill_switch.set_active(pause)         [blocks new trades — global]
      └─ mark_force_close_intent_for_user(uid) [UPDATE positions SET force_close_intent=TRUE]
                                                  ↓ (next tick)
                              exit_watcher closes each open position at market price
                                                  ↓
                              positions.status='closed', exit_reason resolved, PnL realised
```

No bypass of the RISK layer; no change to ENABLE_LIVE_TRADING; closes settle through the same exit-watcher path as any other close.

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| Modified | `projects/polymarket/crusaderbot/webtrader/backend/router.py` |
| Modified | `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` |
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` |
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/components/DesktopSidebar.tsx` |

---

## 4. What Is Working

- Endpoint AST-clean; reuses `kill_switch.set_active` and `mark_force_close_intent_for_user` (both already exported and used in production paths).
- `force_close_intent` marking is idempotent — already-flagged rows are not re-counted; double-submit is safe.
- Button shows a clear warning + Cancel before any destructive action; loading state during the call; navigates to dashboard on success so the user sees the halted state and kill-switch banner.
- `exit_reason` for these closes resolves through the watcher (the FORCE_CLOSE intent path), consistent with the Telegram emergency flow.

## 5. Known Issues

- The kill switch is **global** (system-wide), matching the existing WebTrader `/kill` semantics, while position force-close is **per-user**. In the current single-owner paper deployment this is correct; a future multi-user public deployment may want a per-user pause instead of the global kill switch — flagged for WARP🔹CMD.
- Frontend not type-checked in this environment (no node_modules); relies on CI/Docker `tsc`. No unused identifiers introduced.
- fly CLI not available in cloud env — deploy requires WARP🔹CMD `fly deploy --remote-only`.

## 6. What Is Next

- WARP•SENTINEL validation (MAJOR — execution/capital path).
- Deploy to Fly.io and confirm: clicking Stop All halts trading and all open positions close within one exit-watcher tick.
- Decision (WARP🔹CMD): global kill switch vs per-user pause for the multi-user public phase.
