# WARP•R00T FORGE REPORT — admin-user-detail-edit

Branch: `WARP/ROOT/admin-user-detail-edit`
Role: WARP•R00T (owner-requested admin feature)
Validation Tier: MAJOR (admin-only mutation surface touching user-settings persistence)
Claim Level: NARROW INTEGRATION

## 1. What was built

Closes owner-reported gap: the Ops Console USERS table was read-only — the
operator could see who was on which preset and what they had on, but had
no way to inspect or change a user's bot settings without going through
Supabase directly.

This lane adds a per-user detail + edit surface to the Ops Console:

1. **Backend** — two new admin endpoints:
   - `GET /api/web/admin/users/{user_id}` → `AdminUserDetail` schema. Full
     read-only superset of the `AdminUsers` row plus all editable settings
     (active_preset, risk_profile, capital_alloc_pct, tp_pct, sl_pct,
     max_per_trade_mode/usdc/pct, selected_timeframe, selected_assets),
     the wallet snapshot (balance_usdc), and the live open-position count.
     400 on invalid UUID, 404 on missing user. Handles the
     missing-user_settings edge case (legacy / not-yet-bootstrapped row)
     by returning the canonical paper/balanced/0.40 defaults instead of
     crashing.
   - `PATCH /api/web/admin/users/{user_id}` → `AdminUserDetail`. Partial
     update with `AdminUserUpdate` body (every field Optional). Validates
     each provided field against the **same** allowed-value sets as the
     user-facing endpoints (no admin-only loophole that would let the
     operator persist a value the user couldn't): `active_preset` ∈
     `_PRESET_TO_STRATEGY` keys, `risk_profile` ∈ `_VALID_RISK_PROFILES`,
     `max_per_trade_mode` ∈ `{auto, fixed, pct}`, numeric bounds match
     the customize/risk endpoints (capital_alloc_pct [0.01, 1.00], tp_pct
     [0.005, 5.00], sl_pct [0.005, 1.00], max_per_trade_usdc [1, 500],
     max_per_trade_pct [0.005, 0.10]). 400 on validation miss, 400 on
     empty patch body, 404 on missing target user.

2. **Upsert preserves paper-default invariant** — the PATCH builds an
   `INSERT ... ON CONFLICT (user_id) DO UPDATE` so an admin edit on a
   brand-new user (no user_settings row yet) creates the row with the
   canonical paper-default literals (`'paper'`, `'balanced'`, `0.40`)
   inline in the INSERT — same pattern test_paper_default_invariant.py
   pins for every other user_settings INSERT path. Dynamic
   column-drop logic ensures no duplicate-column error when the patch
   itself already touches `risk_profile` or `capital_alloc_pct`.

3. **Audit log on every successful edit** — `audit.write` is called with
   `actor_role="admin"`, `action="admin_user_settings_update"`,
   `user_id=<actor admin UUID>`, `payload={"target_user_id": ...,
   "patch": {<fields>}}`. Post-hoc operator review can attribute every
   change to the admin who made it.

4. **Frontend** — Ops Console UX:
   - `lib/api.ts`: new `AdminUserDetail` + `AdminUserPatch` types;
     `getAdminUserDetail(userId)` + `updateAdminUser(userId, patch)` methods.
   - `components/AdminUserDrawer.tsx` (NEW): modal drawer rendering the
     read-only stat tiles (Mode / Auto / Balance / Open) on top of an
     edit form (select for active_preset / risk_profile /
     max_per_trade_mode; number inputs for the 5 numeric fields, each
     labelled with its range AND the current persisted value so the
     operator sees what they're changing from). Dirty-diff tracking —
     only fields that differ from the loaded detail are included in the
     PATCH body. On success the drawer re-syncs from the server response.
   - `pages/AdminPage.tsx`: user table rows are now keyboard-accessible
     clickable (`role="button"`, `tabIndex={0}`, `onKeyDown` for
     Enter/Space, aria-label). Click → drawer opens. On save, the row in
     the table is inline-synced with the returned detail so the list
     reflects the edit without a full `/admin/users` reload.

## 2. Current system architecture

```text
[Ops Console USERS table row click]
        │
        └─► AdminUserDrawer (modal)
              │
              ├─► GET /admin/users/{user_id}     → AdminUserDetail
              │     (read-only snapshot for stat tiles + form prefill)
              │
              └─► PATCH /admin/users/{user_id}   → AdminUserDetail
                    │
                    ├─► validate {preset, risk_profile, mode, bounds}
                    │     same enums + bounds as user-facing endpoints
                    │
                    ├─► upsert user_settings ON CONFLICT
                    │     INSERT side: 'paper' / 'balanced' / 0.40 literals
                    │     (paper-default invariant for new-user row)
                    │     UPDATE side: SET <patched fields>, updated_at = NOW()
                    │
                    └─► audit.write(actor_role='admin',
                                    action='admin_user_settings_update',
                                    user_id=<actor>, payload={target, patch})
```

No trading-logic change. No new background jobs. Pure admin surface.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py`
  (`AdminUserDetail`, `AdminUserUpdate`)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  (schema imports; new `admin_user_detail` + `admin_user_update` handlers;
   `_validate_admin_user_patch` helper; new bounds + valid-modes constants)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts`
  (`AdminUserDetail` + `AdminUserPatch` types; `getAdminUserDetail`
   + `updateAdminUser` endpoints)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AdminUserDrawer.tsx` (NEW)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx`
  (drawer state, row click handler, inline row sync on save)
- `projects/polymarket/crusaderbot/tests/test_admin_console.py`
  (+12 test functions, +17 test cases including parametrize)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (lane entry)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (status + COMPLETED + NEXT PRIORITY)

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/test_admin_console.py`
  → 47 passed, 0 failed (17 new + 30 existing).
- `python -m py_compile` clean on router.py + schemas.py.
- `npx tsc --noEmit` clean.
- `npm run build` (vite) clean — AdminPage bundle 37.41 kB / 5.86 kB gzip.

## 5. Known issues

- The PATCH endpoint upserts user_settings with the paper-default invariant
  literals, but the brand-new-user path is exceedingly rare in practice —
  signup/upsert_user already creates the row. Kept as a defence-in-depth
  guarantee, not a hot path.
- `tp_pct` and `sl_pct` cannot currently be "cleared to NULL" from the
  drawer (a number-input blank reads as "unchanged" rather than "clear").
  This matches the user-facing customize endpoint semantics; an explicit
  "Clear" affordance can ship in a follow-up if needed.

## 6. What is next

- WARP🔹CMD review + merge. Tier MAJOR, NARROW INTEGRATION. WARP•SENTINEL
  validation recommended before merge per CLAUDE.md; otherwise WARP🔹CMD
  review on the diff is sufficient given the additive nature (no migration,
  no existing endpoint mutated, validation mirrors user-facing endpoints).
- Operator visual check after redeploy:
  - Open Ops Console → USERS → click any row → drawer opens with full detail
  - Change `active_preset` from one candle preset to another → Save → row
    in the table updates inline → refresh page → change persists
  - Try to set `capital_alloc_pct = 1.5` → 400 error surfaces in the drawer
  - `audit_log` table shows `admin_user_settings_update` row with the
    target user_id and patch payload
- Next lane (research only, no code): WARP/ROOT/heisenberg-survey —
  produce a recommendation memo on which of Heisenberg's 4 agents
  (574 Markets / 568 Candlesticks / 575 Market Insights / 585 Social Pulse)
  is highest-ROI to wire as a new bot feature.

- Validation Tier: **MAJOR** — WARP•SENTINEL validation recommended before
  merge per CLAUDE.md. WARP🔹CMD decides merge after SENTINEL verdict (or
  on diff review if reclassifying as STANDARD).
- Claim Level: **NARROW INTEGRATION**
- Validation Target: admin_user_detail GET path (read shape + edge cases),
  admin_user_update PATCH path (validation gates + upsert SQL +
  audit-log integrity + paper-default invariant), AdminUserDrawer
  edit-form dirty tracking, AdminPage row click + inline sync
- Not in Scope: trading logic, signal generation, exit watcher, risk gate,
  CLOB orders, Telegram bot, wallet flows
- Suggested Next Step: WARP🔹CMD review/merge, then deploy via existing
  crusaderbot-cd.yml on push to main.
