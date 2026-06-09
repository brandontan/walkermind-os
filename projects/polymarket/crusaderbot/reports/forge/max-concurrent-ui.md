# WARP•R00T — max-concurrent-ui (Lane 3C frontend follow-up)

**Branch:** `WARP/ROOT/max-concurrent-ui-parity`
**Role:** WARP•R00T (system hardening)
**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Surface the `max_concurrent_override` user setting in the
WebTrader Auto Mode customize form. Backend was wired in Lane 3C (PR #1546:
schema, router validation, gate step 7, migration 077). This PR closes the
frontend gap so users can actually set the value.
**Not in Scope:** Telegram menu parity (different UX pattern — would need a
multi-step menu insertion in `bot/handlers/mvp/settings.py`, deferred to a
future lane if requested); migration application (operator action).

---

## 1. What was built

A new `MaxConcurrentControl` component on `AutoTradePage` (rendered immediately
after `MaxDrawdownControl`), mirroring the existing controls' visual + interaction
pattern (`DailyLossControl`, `MaxDrawdownControl`). It:

- Reads the current value from `AutoTradeState.max_concurrent_override`
- Shows the user's risk-profile cap (conservative=5, balanced=12, custom=12,
  aggressive=20) inline so they know what they're tightening against
- Computes "Effective" as `min(override, profile_cap)` — matches gate step 7's
  most-restrictive-wins semantics exactly
- Surfaces a clear note when the override is ≥ profile cap ("profile cap wins
  — override looser") so the user understands their override is a no-op
- Clamps input to `[1, 20]` and rounds to integer before POSTing to
  `/autotrade/customize` (`max_concurrent_override`)
- Reset button clears the override (sends `null`) so the user falls back to the
  pure profile cap

## 2. Current system architecture

```
user input (number 1..20)
    │
    ▼
MaxConcurrentControl.save()
    │  POST /autotrade/customize  body: { max_concurrent_override: N }
    ▼
webtrader/backend/router.py (1080-1083)
    │  validate 1 ≤ N ≤ 20 → 400 if out of range
    │  UPSERT user_settings.max_concurrent_override
    ▼
domain/risk/gate.py step 7
    │  K.effective_max_concurrent(ctx.risk_profile, ctx.max_concurrent_override)
    │  → min(PROFILES[profile]["max_concurrent"], N)
    ▼
denied if open_position_count >= effective
```

The `PROFILE_MAX_CONCURRENT` constant in the frontend duplicates the backend
`PROFILES` numbers — kept in sync by the (small) integer values + the inline
comment pointing back to `domain/risk/constants.py`. Future change to the
profile defaults will need both. Acceptable cost for a snappy preview without a
round-trip to the backend.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` — added
  `max_concurrent_override?: number | null` to `AutoTradeState` and
  `CustomizeParams` interfaces (mirrors the existing `daily_loss_override` /
  `max_drawdown_pct` shape).
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`
  — added `<MaxConcurrentControl />` to the customize section + the component
  definition at the bottom of the file (mirrors `MaxDrawdownControl` 1:1 in
  layout / styling / save-clear flow).

Created:
- `projects/polymarket/crusaderbot/reports/forge/max-concurrent-ui.md` — this
  report.

## 4. What is working

- `npx tsc --noEmit` — clean (zero errors).
- `npx vite build` — clean (5.83s, AutoTradePage bundle 117.32 kB / 17.53 kB
  gzip — within rounding of pre-change baseline).
- The control reads from + writes to the same backend fields Lane 3C wired.
- Reset path sends `null` to clear the override (matches the existing pattern
  for `daily_loss_override` and `max_drawdown_pct`).

## 5. Known issues

None introduced by this lane.

- Telegram parity intentionally deferred (different UX pattern — TG uses menu
  trees, not single-shot slash commands; adding a `/max_concurrent` would be
  inconsistent with the existing settings UX).
- `PROFILE_MAX_CONCURRENT` mirrored on the frontend (5 / 12 / 20 — same as
  `domain/risk/constants.py:PROFILES`). Future profile-cap changes need both
  sides updated.

## 6. What is next

- WARP🔹CMD review + merge of `WARP/ROOT/max-concurrent-ui-parity` (MINOR,
  NARROW INTEGRATION). No SENTINEL required — frontend-only, behaviour-preserving.
- Optional follow-up: Telegram menu integration in `bot/handlers/mvp/settings.py`
  if the user wants TG parity (would be a separate lane).
- Lane 5 LIVE live-fire validation remains the only blocking lane before public
  LIVE flip — MAJOR, OWNER-gated, SENTINEL-routed.

---

**Suggested Next Step:** WARP🔹CMD review + merge. Then deploy WebTrader to Fly
so the new control appears in the live customize form.
