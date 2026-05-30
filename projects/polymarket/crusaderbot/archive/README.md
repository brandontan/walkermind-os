# archive/

Inert, de-referenced files preserved for historical record (WARP cleanup lane —
**ARCHIVE = MOVE, never delete**). Nothing in this directory is imported or
executed by the running system; there is intentionally no `__init__.py` so these
files are not importable as a package. Paths mirror the original location for
context.

| Archived path | Original path | Reason | Lane |
|---|---|---|---|
| `services/allowlist.py` | `projects/polymarket/crusaderbot/services/allowlist.py` | Orphaned integer-tier module — **zero inbound references** (no imports of the module or its symbols `is_allowlisted` / `add_to_allowlist` / `resolve_tier` / `TIER_ALLOWLISTED` anywhere, including tests). Superseded by RBAC (`users.role`) + the separate wired `services/tiers.py`. | WARP/ROOT/dead-code-archive |

The superseded blueprint `crusaderbot_old.md` was archived in the same lane to
`docs/archive/blueprint/crusaderbot_old.md` (repo-root docs tree; zero inbound
references; superseded by `docs/blueprint/crusaderbot.md`).
