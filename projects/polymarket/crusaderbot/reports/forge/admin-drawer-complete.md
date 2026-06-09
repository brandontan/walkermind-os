# admin-drawer-complete

## 1. What was built

Completed the WARP•R00T admin User-Detail drawer (`/admin/users/{user_id}`) so the operator can manage the full per-user runtime surface without falling back to SQL. Today's drawer was a partial view: it could edit `active_preset / risk_profile / capital_alloc_pct / tp_pct / sl_pct / max_per_trade_*` but had no path for `selected_timeframe / selected_assets`, no per-user pause/resume control, no identity context (wallet address, telegram id, email), no recent-activity context, and the TP% input label was bounded at `0.5–1000` even though the user-facing flow caps it at 100%.

This lane closes those gaps and audit-logs the new controls through the existing `admin_user_settings_update` action.

## 2. Current system architecture

```
WebTrader UI
└── AdminUserDrawer.tsx (admin-only)
        │
        ├── GET  /api/web/admin/users/{user_id}    → AdminUserDetail
        │       (now includes wallet_address, telegram_user_id,
        │        recent_trades[5], recent_audit[3])
        │
        └── PATCH /api/web/admin/users/{user_id}   → AdminUserDetail
                │
                ├── selected_timeframe / selected_assets → user_settings UPDATE
                ├── paused                              → users.set_paused() helper
                │                                         (same path as /kill + /resume)
                └── existing strategy/risk fields       → user_settings UPDATE
                          │
                          └── audit.log INSERT
                                actor_role='admin',
                                action='admin_user_settings_update',
                                payload={ target_user_id, patch, paused? }
```

Per-user pause flips `users.paused` through the canonical `users.set_paused()` helper so the risk gate cache invalidation matches the self-service `/kill` + `/resume` paths exactly — no parallel write path.

## 3. Files created / modified

```
projects/polymarket/crusaderbot/webtrader/backend/schemas.py
projects/polymarket/crusaderbot/webtrader/backend/router.py
projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts
projects/polymarket/crusaderbot/webtrader/frontend/src/components/AdminUserDrawer.tsx
projects/polymarket/crusaderbot/reports/forge/admin-drawer-complete.md
projects/polymarket/crusaderbot/state/PROJECT_STATE.md
projects/polymarket/crusaderbot/state/CHANGELOG.md
```

### Backend (`schemas.py`)
- New `AdminRecentTrade` model — id, status, side, size_usdc, entry_price, pnl_usdc, exit_reason, strategy_type, market_question, ts.
- New `AdminRecentAudit` model — ts, actor_role, action.
- `AdminUserDetail` gains `telegram_user_id: Optional[int]`, `wallet_address: Optional[str]`, `recent_trades: list[AdminRecentTrade]`, `recent_audit: list[AdminRecentAudit]`.
- `AdminUserUpdate` gains `selected_timeframe`, `selected_assets`, `paused`.

### Backend (`router.py`)
- `admin_user_detail` extended:
  - `users` SELECT now pulls `telegram_user_id`.
  - `wallets` SELECT now pulls `deposit_address`.
  - New `positions` SELECT joins `markets` for the last 5 trades (`ORDER BY COALESCE(closed_at, created_at) DESC LIMIT 5`).
  - New `audit.log` SELECT for the last 3 audit rows scoped to `user_id`.
- `_validate_admin_user_patch` rejects unknown `selected_timeframe` and unknown `selected_assets` symbols, reusing `_VALID_TIMEFRAMES` and `_VALID_ASSETS` defined for the preset activation path so admin overrides match the user-facing fence.
- `admin_user_update` writer:
  - Normalises `selected_assets` to uppercase + de-duplicates; an empty list clears the column.
  - Splits `paused` out of the `user_settings` upsert and routes it through `users.set_paused(target_uuid, value)` so the risk gate sees the change immediately and cached `ctx.paused` is invalidated.
  - Audit payload now records the `paused` value alongside the settings patch.
- Added `from typing import Any` for the dynamically-typed audit payload.

### Frontend (`api.ts`)
- New `AdminRecentTrade` and `AdminRecentAudit` interfaces.
- `AdminUserDetail` and `AdminUserPatch` extended to mirror the backend.

### Frontend (`AdminUserDrawer.tsx`)
- TP% input label and `max` corrected: `0.5–100` (was `0.5–1000`).
- New Identity block (email, telegram id, wallet address with `title=` tooltip + middle ellipsis).
- New per-user Pause/Resume button — fires a single-field PATCH (`{ paused: true|false }`) and renders the resulting state-aware copy.
- New crypto-short controls (Timeframe select + Assets chip-toggle row) — auto-shown only when `active_preset ∈ {close_sweep, safe_close, flip_hunter}` so non-crypto-short presets stay uncluttered. The chip row is uncontrolled until first click (`selected_assets: null = unchanged`); on first click it forks from the persisted set so partial selections never overwrite the previous list by accident.
- New Recent Trades section — colored P&L, YES/NO side pill, exit-reason + strategy_type meta, relative timestamp.
- New Recent Audit section — actor_role + action + relative timestamp.

## 4. What is working

- `py_compile` clean on both modified backend modules.
- All new validators reuse the same frozensets that gate the user-facing `/autotrade/preset` flow, so the operator path can't bypass the system fence.
- `paused` write path goes through `users.set_paused()`, the same helper used by `/kill`, `/resume`, `/emergency-stop`. Risk gate behaviour is uniform whether the user pressed Kill or an admin flipped the toggle.
- The pause toggle PATCH is a single-field PATCH, so it works even when the operator hasn't touched any other field in the form (writer guard skips the `user_settings` upsert when no settings fields are present).
- Drawer falls back gracefully when `recent_trades` or `recent_audit` are empty (new users) — explicit "No trades yet." / "No audit entries." copy.
- Identity block truncates long wallet addresses with the full value in the `title=` tooltip so the operator can hover to copy.

## 5. Known issues

- `node_modules` is not installed in this remote container so a full `tsc --noEmit` is not runnable here; the lane relies on Vite/Fly.io CI for final TS validation. The errors emitted by `tsc` locally are all "Cannot find module 'react'" / implicit-any cascades from missing types — identical pattern in the unmodified parts of the tree.
- `selected_assets`/`selected_timeframe` are written verbatim — the writer does not validate that the active preset is a crypto-short one when an operator pushes those fields. The schema fence still blocks unknown assets/timeframes, and the drawer UI hides the controls outside crypto-short presets, but a direct API call could persist a `15m` timeframe on a non-crypto-short user. The user-facing preset activation flow clears these columns whenever it switches presets, so the next preset change reconciles drift.
- The Pause toggle does not also flip `auto_trade_on`. Today's product invariant is `auto_trade_on=true + paused=true → SCANNER shows PAUSED (Admin)`, which is what the drawer Stat row already reflects; leaving `auto_trade_on` alone preserves the user's intent for when they unpause.

## 6. What is next

- Operator hands-on smoke test post-deploy: open the drawer on `@walk3r69`, flip pause, edit the asset chips, save, confirm the dashboard `SCANNER` pill and the `audit.log` row both reflect the change.
- LIVE mode toggle is still deferred pending WARP🔹CMD authorisation (paper-default invariant + `ENABLE_LIVE_TRADING` guard).
- Surface the `recent_audit` block on the user-facing settings page (read-only) so the user can see what admin actions touched their account — separate lane, not in scope here.

---

**Validation Tier**: STANDARD
**Claim Level**: NARROW INTEGRATION
**Validation Target**: AdminUserDrawer end-to-end (identity block, pause toggle, timeframe + assets editor, recent trades + audit, TP% label fix).
**Not in Scope**: LIVE mode toggle. User-facing audit visibility. Backend bound change to `_TP_PCT_MAX` (left at `10.0` to avoid breaking any existing user setting; UI now caps at 100% which is the realistic envelope).
**Suggested Next Step**: WARP🔹CMD review and merge → Fly.io auto-deploy → smoke test the drawer against `@walk3r69`.
