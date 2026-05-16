# WARP•FORGE Report — role-model-admin-user

Branch: WARP/role-model-admin-user
Date: 2026-05-17 16:00 Asia/Jakarta
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: collapse the access model to two roles (admin + user),
  open paper trading to every user, remove operator/tier/allowlist/premium
  user-facing wording. NO live activation; internal live-safety gate
  preserved; no DB schema teardown.
Not in Scope: removing assert_live_guards / the Tier-4 + activation-guard
  LIVE-trading safety gate (explicitly declined — see Known Issues);
  dropping user_tiers / users.access_tier tables (logic+UX collapse only);
  merging PRs; production DB / fly ops.

## 1. What was built

A two-role model — `admin` (OPERATOR_CHAT_ID or ADMIN) and `user`
(everyone, full paper access):

- Paper trading opened to all: risk-gate step-3 tier check scoped to
  `trading_mode == "live"` only; `setup.py` access gate removed
  (`_ensure_tier2` → `_ensure_user`).
- All operator / "Tier 2/3/4" / allowlist / premium user-facing strings
  replaced with the two canonical messages: `Admin access required.` and
  `This feature is not available.`
- Admin surface relabelled to a `🛠 Admin` panel (Runtime Health / User
  Monitor / Emergency Stop / Logs / Roles / Broadcast) mapped to existing
  commands; `/admin settier` now takes `user|admin` (mapped onto the
  FREE/ADMIN tier column so the DB CHECK constraint is satisfied with no
  migration; legacy FREE/PREMIUM/ADMIN still accepted).
- Deposit-watcher notifications reworded — paper auto-trade is always
  available; a deposit minimum is relevant only to live trading.

## 2. Current system architecture

Pipeline unchanged. Access model: every onboarded user is a `user` with
full paper capability. `admin` = OPERATOR_CHAT_ID match or ADMIN tier
(existing `_is_admin_user`). The dual tier tables are retained internally;
`users.access_tier` still backs the LIVE-trading safety gate.

LIVE safety boundary UNCHANGED: `domain/execution/live.py:assert_live_guards`
(Tier-4 + ENABLE_LIVE_TRADING + EXECUTION_PATH_VALIDATED +
CAPITAL_MODE_CONFIRMED + USE_REAL_CLOB) is intact. Risk-gate step-3 still
blocks live for `access_tier < 3` as defence-in-depth. Live remains
owner-gated and OFF.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/risk/gate.py
- projects/polymarket/crusaderbot/bot/handlers/setup.py
- projects/polymarket/crusaderbot/bot/middleware/access_tier.py
- projects/polymarket/crusaderbot/bot/middleware/tier_gate.py
- projects/polymarket/crusaderbot/bot/tier.py
- projects/polymarket/crusaderbot/services/allowlist.py
- projects/polymarket/crusaderbot/bot/handlers/admin.py
- projects/polymarket/crusaderbot/domain/activation/live_checklist.py
- projects/polymarket/crusaderbot/bot/handlers/presets.py
- projects/polymarket/crusaderbot/scripts/seed_operator_tier.py
- projects/polymarket/crusaderbot/scheduler.py
- projects/polymarket/crusaderbot/tests/test_access_tiers.py
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/WORKTODO.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

Created:
- projects/polymarket/crusaderbot/reports/forge/role-model-admin-user.md

## 4. What is working

- Full suite from repo root: 1413 passed, 1 skipped (this branch is off
  main; the crusaderbot-finalize lane's added tests are not on it — count
  difference is expected).
- ruff (E9,F63,F7,F82) clean on changed Python.
- No production handler uses the @require_tier/@require_access_tier
  decorators (only tests) — confirming paper is genuinely open; the
  wording change has no gating side-effect.
- Updated 3 admin tests to the two-role wording.

## 5. Known issues

- WARP🔹CMD asked to also remove the internal Tier-4/activation-guard
  LIVE-trading safety gate. WARP•FORGE DECLINED that sub-item only:
  CLAUDE.md HARD RULE — "ENABLE_LIVE_TRADING guard must never be
  bypassed… NEVER bypass execution guard under any circumstances." The
  gate is invisible to users, so keeping it does not affect the role-model
  UX. Every other requested item was delivered.
- Dual tier tables retained (no DB teardown, by the chosen approach).
  Internal-only; not user-visible.
- MAJOR tier → WARP•SENTINEL validation required before merge.

## 6. What is next

- WARP•SENTINEL MAJOR validation (focus: no LIVE path weakened by the
  paper-open change; assert_live_guards intact).
- WARP🔹CMD merge decision (FORGE does not merge).

Suggested Next Step: WARP•SENTINEL audit (paper-open safety + live-gate
integrity) → WARP🔹CMD merge.
