# WARP•R00T FORGE REPORT — live-activation-ux

Branch: `WARP/ROOT/live-activation-ux`
Role: WARP•R00T (self-validated under WARP🔹CMD delegation)
Validation Tier: **MAJOR** (live-trading / capital path)
Claim Level: **FULL RUNTIME INTEGRATION**
Validation Target: per-user LIVE opt-in UX symmetry across WebTrader (full control) and Telegram (simple control); shared cap/phrase source of truth; no-silent-failure hardening on the live path.
Not in Scope: flipping operator activation guards (owner-only per `state/LIVE_READINESS.md`); on-chain capital wiring; `bot/_keyboards_archive/` dead-code deletion; MVP `_users.py` fail-open redesign; market-feed `[]`-on-error → 503 change (LOW, deferred).
Suggested Next Step: WARP🔹CMD review + merge; auto-deploy to Fly via crusaderbot-cd.

---

## 1. What was built

Completed the per-user LIVE opt-in flow on BOTH surfaces so the backend
`/api/web/live/{status,enable,disable}` endpoints (#1435) are actually
reachable by public users. Before this lane the live opt-in was unreachable
from the WebTrader UI and broken on Telegram, so no public user could go LIVE
even with operator guards open (every live trade was rejected `live_not_opted_in`
at risk-gate step 15).

A 3-surface audit (WebTrader frontend / WebTrader backend / Telegram bot) first
confirmed the system is otherwise clean: no fake/synthetic data in any
production path, SSE realtime with polling fallback, per-user isolation intact,
no swallowed exceptions in trade paths. The only public-LIVE blocker was the
incomplete opt-in UX — fixed here.

Changes:

1. **Shared source of truth** (`domain/activation/live_opt_in_gate.py`):
   `LIVE_ENABLE_CONFIRM_PHRASE`, `LIVE_CAP_MIN_USDC` (0), `LIVE_CAP_MAX_USDC`
   (10000), and `validate_live_capital_cap()` (parse + bounds-check, raises
   human-readable `LiveCapError`). WebTrader router now imports the phrase +
   bounds from here (kills the duplicated magic string), and the Telegram flow
   uses the same validator + bounds. Three surfaces, one truth.

2. **Telegram `/enable_live` CRITICAL fix**: inserted a cap-capture step. The
   flow is now warning → `CONFIRM` → enter cap (1–10000) → typed YES button.
   On confirm it writes `trading_mode='live'` **and** `live_capital_cap_usdc`
   together (was writing only the mode → gate step 15 rejected every trade).
   Added symmetric `/disable_live` (single-step revert to paper, cap preserved),
   mirroring the WebTrader `/live/disable` endpoint.

3. **WebTrader `LiveActivationModal`** (full-control surface): multi-step modal
   (readiness preview with per-gate checklist → capital-cap input with presets →
   typed confirm phrase) wired to `api.getLiveStatus/enableLive/disableLive`.
   Surfaced as a described "Live Trading" section in Settings showing current
   mode, cap, and open live exposure, with a "Switch back to Paper" control when
   live. Mode-aware footer disclaimer.

4. **No-silent-failure hardening**: `write_mode_change_event()` now returns a
   bool; both Telegram enable/disable surface a soft warning if the mode-change
   audit row fails to write (was silently logged only). `dashboard.py`
   last-trade fallback now `logger.exception(...)` instead of a bare swallow
   (still fail-open for UX).

Every step on both surfaces carries plain-language trade explanations
(what the cap means, what stays protected, what switching back does).

## 2. Current system architecture

Defence-in-depth on a live trade is unchanged and now fully reachable:

```
operator env guards (5, owner-only)
  → per-user opt-in switch  ← THIS LANE made it reachable on both surfaces
      • WebTrader: LiveActivationModal → POST /live/enable (phrase + cap)
      • Telegram:  /enable_live → CONFIRM → cap → YES (same write)
  → 8-gate live_checklist (re-evaluated at opt-in on both surfaces)
  → risk gate step 15 capital cap (per trade, gate.py)
```

Shared constants/validator in `domain/activation/live_opt_in_gate.py` keep the
phrase + cap bounds identical across WebTrader backend, WebTrader frontend
(mirrored constants in `api.ts`), and the Telegram handler.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/LiveActivationModal.tsx`
- `projects/polymarket/crusaderbot/tests/test_live_cap_shared.py`
- `projects/polymarket/crusaderbot/reports/forge/live-activation-ux.md`

Modified:
- `projects/polymarket/crusaderbot/domain/activation/live_opt_in_gate.py` (shared constants + validator + bool return)
- `projects/polymarket/crusaderbot/bot/handlers/live_gate.py` (cap step + /disable_live + explanations)
- `projects/polymarket/crusaderbot/bot/dispatcher.py` (register /disable_live)
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` (log instead of silent swallow)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (import shared phrase + bounds)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` (live methods + types + shared constants)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx` (Live Trading section + modal)
- `projects/polymarket/crusaderbot/tests/test_live_activation_flow.py` (cap-bounds pin → shared-constant form)
- `projects/polymarket/crusaderbot/tests/test_live_opt_in_gate.py` (flow tests updated to cap-aware flow)

## 4. What is working

- Telegram `/enable_live` now captures + writes the cap; `/disable_live` reverts.
- WebTrader users can opt into live via the modal (gate preview, cap, typed confirm) and revert from Settings.
- Both surfaces share one phrase + cap bounds; risk-gate step 15 enforcement unchanged.
- Full suite **1990 passed / 0 failed** (added 31 tests, updated 2 flow pins). ruff clean; py_compile clean.
- Frontend `tsc --noEmit` clean; `vite build` clean.

## 5. Known issues

- DB_POOL_MAX 10→3 carry-over — 48h Sentry watch (LOW, operational, pre-existing; not a launch blocker).
- Deferred (out of scope, non-blocking): delete `bot/_keyboards_archive/` (21 dead files); market/market-feed `[]`-on-error → 503; MVP `_users.py` fail-open documentation; deprecate vestigial `_tp_exit_price`/`_sl_exit_price`.

## 6. What is next

WARP🔹CMD review + merge → Fly auto-deploy. Going LIVE remains an owner-only
operational decision per `state/LIVE_READINESS.md`.
