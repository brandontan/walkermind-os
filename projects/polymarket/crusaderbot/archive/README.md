# archive/

Inert, de-referenced files preserved for historical record (WARP cleanup lane —
**ARCHIVE = MOVE, never delete**). Nothing in this directory is imported or
executed by the running system; there is intentionally no `__init__.py` so these
files are not importable as a package. Paths mirror the original location for
context.

| Archived path | Original path | Reason | Lane |
|---|---|---|---|
| `projects/polymarket/crusaderbot/archive/services/allowlist.py` | `projects/polymarket/crusaderbot/services/allowlist.py` | Orphaned integer-tier module — **zero inbound references** (no imports of the module or its symbols `is_allowlisted` / `add_to_allowlist` / `remove_from_allowlist` / `get_user_tier` / `TIER_ALLOWLISTED` anywhere, including tests). Superseded by RBAC (`users.role`) + the separate wired `services/tiers.py`. Note: this module's `get_user_tier` (returns `int`) is distinct from — and superseded by — the wired `services/tiers.py:get_user_tier` (returns FREE/PREMIUM/ADMIN). | WARP/ROOT/dead-code-archive |
| `docs/archive/blueprint/crusaderbot_old.md` | `docs/blueprint/crusaderbot_old.md` | Superseded by `docs/blueprint/crusaderbot.md`; **zero inbound references** (no doc links, no code/config references). | WARP/ROOT/dead-code-archive |
