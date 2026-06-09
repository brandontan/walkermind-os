# WARP•ROOT — dead-code-archive

Role: WARP•R00T
Branch: WARP/ROOT/dead-code-archive
Date: 2026-05-31 Asia/Jakarta
Validation Tier: MINOR (repo cleanup — ARCHIVE = MOVE, no runtime code changed)
Claim Level: FOUNDATION
Validation Target: removal of orphaned modules from the live tree (history preserved)
Not in Scope: deleting anything; refactoring services/tiers.py (the wired tier module — separate lane, see F13)
Closes: WARP/ROOT/prelaunch-system-audit finding F9

## 1. What was built

Archived two confirmed-dead files (MOVE via `git mv`, history preserved — never deleted, never force-pushed):
- `services/allowlist.py` → `archive/services/allowlist.py` — an orphaned integer-tier module with **zero inbound references** (verified: no `import`/`from .allowlist`, and none of its symbols `is_allowlisted` / `add_to_allowlist` / `remove_from_allowlist` / `get_user_tier` / `TIER_ALLOWLISTED` are used anywhere, including tests). Its own docstring's "imported by dispatcher, admin handler, tier gate" claim was false. Superseded by RBAC (`users.role`) + the separate, still-wired `services/tiers.py`.
- `docs/blueprint/crusaderbot_old.md` → `docs/archive/blueprint/crusaderbot_old.md` — superseded by `docs/blueprint/crusaderbot.md`; zero inbound references (no doc links, no code/config references).

## 2. Current system architecture

No runtime change. The live tree no longer carries the dead allowlist module or the superseded blueprint. `services/tiers.py` (the wired FREE/PREMIUM/ADMIN helper that reconciles to `users.role`) is untouched and remains the only tier-named module in the live tree. New `archive/` directory has no `__init__.py`, so archived `.py` files are not importable as a package.

## 3. Files created/modified

- Moved: `projects/polymarket/crusaderbot/services/allowlist.py` → `projects/polymarket/crusaderbot/archive/services/allowlist.py`.
- Moved: `docs/blueprint/crusaderbot_old.md` → `docs/archive/blueprint/crusaderbot_old.md`.
- Created: `projects/polymarket/crusaderbot/archive/README.md` (provenance note).
- Modified (state): `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md`.

## 4. What is working

`services/allowlist.py` is gone from the live tree; nothing imported it, so nothing breaks. Verified: `test_access_tiers.py` 32/32 pass (the wired `services/tiers.py` path + admin handler `get_user_tier` are unaffected); archived `allowlist.py` still `py_compile`s. Git records both moves as renames (full history retained).

## 5. Known issues

- `services/tiers.py` (FREE/PREMIUM/ADMIN string scheme + `user_tiers` table) remains in the live tree by design — it is WIRED (admin handler, hourly report) and reconciles to `users.role`. Consolidating it onto `users.role` is the separate audit finding F13 (P2), out of scope for this archive lane.

## 6. What is next

WARP🔹CMD review (MINOR). Closes audit F9 and completes the authorized Phase B lane set (preset-gate-deny-by-default, bnb-monitor-only-fallback-fix, blueprint-rbac-roster-sync, dead-code-archive).

Suggested Next Step: WARP🔹CMD reviews/merges the 4 Phase B PRs (SENTINEL on the two MAJOR execution-path lanes first); owner decisions on B1 (enable bankroll CB via directive track), B3 (sizing-cap posture), and the prod `contrarian` row remain.
