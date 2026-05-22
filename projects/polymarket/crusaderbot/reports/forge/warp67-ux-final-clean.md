# WARP•FORGE Report — WARP-67 Telegram UX Final Clean

**Issue:** #1284
**Branch:** WARP/warp67-ux-final-clean
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION (UI/UX rendering + keyboard state)
**Validation Target:** Clean flat Markdown rendering (no box-drawing chars), correct Auto button labels, paused-aware Resume button, single Settings/Help response, no positions title artifact.
**Not in Scope:** Live trading, strategy/engine logic, DB queries, dispatcher.py routing (WARP-66, already correct), migrations.

---

## 1. What was built

Five confirmed live UX defects fixed:

- **Bug 1 — Tree lines berantakan:** Unicode box-drawing characters (`│ ├── └──`) replaced by a flat Markdown layout that renders consistently across Telegram clients (notably Android). All `messages_mvp.render_*` output now uses bold section headers (`*Header*`) and plain `Key: Value` lines, separated by a single blank line after the title. Messages are sent with `parse_mode="Markdown"`.
- **Bug 2 — "Setup Auto" label wrong:** `main_menu_kb()` gained a `configured` parameter; the Auto button now shows "🤖 Auto Mode" whenever a preset is configured (even when the bot is Stopped), and "🤖 Setup Auto" only when truly unconfigured.
- **Bug 3 — Resume button shown while Stopped:** `keyboards/mvp/autotrade.home_kb()` is now paused-aware — Pause (running) / Resume (paused) / **Start** (stopped+configured / unconfigured).
- **Bug 4 — Settings/Help double response:** `menus/main.MAIN_MENU_ROUTES` now maps "⚙️ Settings" and "❓ Help" to `_group0_noop` (same convention as Dashboard/Portfolio), so the legacy handlers no longer fire a second message alongside the group=-1 MVP handler.
- **Bug 5 — Positions "202" artifact:** `render_positions_list()` and `render_markets_trending()` now sanitize the dynamic market title (strip whitespace, collapse embedded newlines) before rendering, and all dynamic strings are Markdown-escaped.

Option B (flat Markdown) was implemented per WARP🔹CMD recommendation.

## 2. Current system architecture

Rendering pipeline (unchanged shape, reworked output):

```
handlers/mvp/* → messages_mvp.render_*  → ui.tree helpers (flat Markdown)
                                         → _send.send_or_edit(parse_mode="Markdown")
```

- `ui/tree.py` helpers (`title`, `leaf`, `section`, `nested`, `join_blocks`) were re-implemented to emit flat Markdown instead of box-drawing trees. A new `md_escape()` helper escapes Telegram Markdown-v1 reserved chars (`_ * ` `` ` `` `[`) in every label/value, so market titles and wallet addresses cannot break formatting. ASCII fallback constants `BAR/BRANCH/LAST` are retained (now `| |- `` `- ``) for the `ui` package public API but are no longer emitted by renderers.
- `_send.send_or_edit()` default `parse_mode` changed `None → "Markdown"`; every MVP call site renders messages_mvp output, so this is the single switch that activates Markdown rendering across all screens.
- Keyboard state: `main_menu_kb(configured=...)` and `home_kb(paused=...)` make button labels reflect true bot state.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/bot/ui/tree.py` — flat Markdown helpers + `md_escape()`; ASCII-safe constants.
- `projects/polymarket/crusaderbot/bot/messages_mvp.py` — removed direct tree-glyph lines; FAQ + loading/syncing reworked; positions/trending title sanitize; import cleanup (`md_escape` in, `BAR/BRANCH/LAST` out).
- `projects/polymarket/crusaderbot/bot/handlers/mvp/_send.py` — `parse_mode` default `"Markdown"`.
- `projects/polymarket/crusaderbot/bot/keyboards/mvp/_common.py` — `main_menu_kb(configured=...)`.
- `projects/polymarket/crusaderbot/bot/keyboards/mvp/autotrade.py` — `home_kb(paused=...)` (Pause/Resume/Start).
- `projects/polymarket/crusaderbot/bot/handlers/mvp/dashboard.py` — pass `configured=d["configured"]`.
- `projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py` — `home_kb(paused=...)` + `do_start` `configured=True`.
- `projects/polymarket/crusaderbot/bot/handlers/mvp/onboarding.py` — returning user `configured=returning`.
- `projects/polymarket/crusaderbot/bot/menus/main.py` — Settings + Help → `_group0_noop`; dropped now-unused `onboarding`/`settings` imports.

Tests updated to new intended behavior:
- `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py` — `test_settings_and_help_share_noop_sentinel` (replaces obsolete different-handlers assertion).
- `projects/polymarket/crusaderbot/tests/test_ux_overhaul.py` — `test_menu_routes_settings_registered` now asserts `_group0_noop`.

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md` updated.

## 4. What is working

- Manual render check: dashboard/positions/autotrade/FAQ/loading all emit flat Markdown, zero `│ ├ └` characters; `md_escape` neutralizes `*`/newline injection in dynamic titles (verified with `"2026 Election *winner*\n line2"` → single clean line).
- Full suite: **1614 passed** (`pytest projects/polymarket/crusaderbot/tests/`).

## 5. Known issues

- Visual rendering on a live Telegram client not exercised in this container (no bot token / network). Requires Fly.io redeploy + on-device confirmation by WARP🔹CMD.
- `bot/ui/__init__.py` still re-exports `BAR/BRANCH/LAST` (now ASCII) for API compatibility; renderers no longer use them — dead-export cleanup can be a later MINOR lane.

## 6. What is next

- WARP🔹CMD review (STANDARD) → merge → Fly.io redeploy → confirm rendering on Android/iOS Telegram client.

---

**Suggested Next Step:** WARP🔹CMD review + merge; redeploy and verify the five screens on a live device.
