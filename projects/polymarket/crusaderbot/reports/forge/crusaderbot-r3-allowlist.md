# WARP•FORGE Report — crusaderbot-r3-allowlist

**Branch:** WARP/CRUSADERBOT-R3-ALLOWLIST
**Last Updated:** 2026-05-04 12:10 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** FOUNDATION

---

## 1. What was built

R3 lane: Tier 2 allowlist gate system. First operator-privileged command surface plus reusable tier-gate primitive for future Tier 2+ commands.

- **Allowlist store** (`services/allowlist.py`): in-memory `set[int]` of `telegram_user_id` values, guarded by `asyncio.Lock`. Module-level singleton + helper functions `add_to_allowlist`, `remove_from_allowlist`, `is_allowlisted`, `get_user_tier`, `tier_label`. Tier semantics: Tier 1 (Browse) by default; Tier 2 (Community allowlisted) when `telegram_user_id` is in the allowlist.
- **Tier-gate decorator** (`bot/middleware/tier_gate.py`): `require_tier(min_tier)` wraps any Telegram handler and short-circuits with `🔒 This feature requires Tier 2 access...` for under-tier callers. Scaffolded but **not applied to any existing handler** — `/start`, `/status`, `/allowlist` all stay open per task. Future R5+ command handlers (`/config`, `/strategy`, `/risk`, `/paper`) will decorate with `@require_tier(TIER_ALLOWLISTED)`.
- **`/allowlist` command** (`bot/handlers/admin.py`): subcommand router for `add <id>`, `remove <id>`, `list`. Operator gate via `OPERATOR_CHAT_ID` match (reused — no new env var per WARP🔹CMD direction). Non-operator callers receive `⛔ Unauthorized.` with structured `allowlist.unauthorized_attempt` log entry.
- **`/status` extended** (`bot/dispatcher.py`): reply now begins with `Your access tier: Tier N — <label>` line above the existing guard-state output. Available to all tiers.

Lane also performs post-merge sync from PR #848: `ROADMAP.md` R2 row → ✅ Done; `PROJECT_STATE.md` COMPLETED list updated; `CHANGELOG.md` appended.

## 2. Current system architecture (slice for R3)

```
Telegram /allowlist <subcommand> [args]
  ↓
bot/dispatcher.py  CommandHandler("allowlist", partial(handle_allowlist, config=settings))
  ↓
bot/handlers/admin.handle_allowlist(update, context, *, config)
  ├── operator gate: caller_id == config.OPERATOR_CHAT_ID
  │     ├── no  → "⛔ Unauthorized." + structured warning log
  │     └── yes → subcommand dispatch
  ├── "list"   → allowlist.list_all() → markdown bullet list (or "📋 empty")
  ├── "add"    → add_to_allowlist(int(args[1])) → "✅ User X added..." | "ℹ️ already on..."
  ├── "remove" → remove_from_allowlist(int(args[1])) → "✅ User X removed..." | "ℹ️ was not on..."
  └── unknown  → "⚠️ Unknown subcommand: ..." + usage

services/allowlist.py
  AllowlistStore (asyncio.Lock-guarded set[int])
    add / remove / contains / list_all
  Module helpers: add_to_allowlist, remove_from_allowlist, is_allowlisted,
                  get_user_tier(telegram_user_id) -> {TIER_BROWSE=1, TIER_ALLOWLISTED=2}
                  tier_label(tier) -> str

Telegram /status (any tier)
  ↓
status_handler
  ├── caller_tier = await get_user_tier(update.effective_user.id)
  └── reply with: "Your access tier: <label>\n\nGuard states:\n..."

bot/middleware/tier_gate.py
  require_tier(min_tier) decorator
    @wraps(handler) async def wrapper(update, context, *args, **kwargs):
      if get_user_tier(...) < min_tier:
        reply TIER_DENIED_MESSAGE; return
      else handler(update, context, *args, **kwargs)
  (Currently no consumer — R5+ Tier 2+ command handlers will decorate)
```

`main.py` is unchanged: allowlist is a module-level singleton (matches existing `db` and `cache` pattern), so no injection through `setup_handlers` is needed. Operator gating is via existing `OPERATOR_CHAT_ID` (R1 config); no new env var introduced.

## 3. Files created / modified (full repo-root paths)

**Created (5):**
- `projects/polymarket/crusaderbot/services/allowlist.py` — `AllowlistStore` + helpers + tier resolution
- `projects/polymarket/crusaderbot/bot/middleware/__init__.py` — package marker
- `projects/polymarket/crusaderbot/bot/middleware/tier_gate.py` — `require_tier` decorator + `TIER_DENIED_MESSAGE`
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` — `handle_allowlist` subcommand router
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-r3-allowlist.md` — this report

**Modified (4):**
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registered `/allowlist` via `partial(handle_allowlist, config=)`; `/status` now shows caller's tier above guard states
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Last Updated bumped, COMPLETED includes R2 (PR #848), IN PROGRESS = crusaderbot-r3-allowlist, NEXT PRIORITY = R4
- `projects/polymarket/crusaderbot/state/ROADMAP.md` — R2 row 🚧 → ✅ (PR #848); R3 row ❌ → 🚧 (this lane); Last Updated bumped
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — appended R3 lane entry

**Unchanged (intentional):**
- `main.py` — singleton pattern means no wiring change required
- `config.py` / `.env.example` — `OPERATOR_CHAT_ID` reused per WARP🔹CMD; no new env var

## 4. What is working

- `add_to_allowlist` / `remove_from_allowlist` are idempotent: returning `True` if state actually changed, `False` if no-op
- `AllowlistStore` is async-safe via `asyncio.Lock`; concurrent add/remove from multiple handlers cannot corrupt the underlying set
- `get_user_tier(telegram_user_id)` resolves at read time; no DB write needed when adding to allowlist (instant tier promotion)
- `tier_label` produces readable strings matching blueprint v3.1 §1 wording (`Tier 1 — Browse only`, `Tier 2 — Community allowlisted`)
- `/allowlist` subcommands fully functional: usage message on no args, integer parsing on `add`/`remove`, markdown-formatted list on `list`, friendly fallback on unknown subcommand
- Operator gate: any `telegram_user_id != config.OPERATOR_CHAT_ID` receives `⛔ Unauthorized.` and a structured `allowlist.unauthorized_attempt` log entry (visible to ops audit)
- `/status` now opens with `Your access tier: <label>` for the calling user; same handler still surfaces guard states + mode + env (unchanged otherwise)
- `require_tier` decorator preserves the wrapped handler's signature via `@wraps`; supports both standard (update, context) handlers AND `partial`-bound handlers receiving extra `*args/**kwargs` (e.g., `handle_start(update, context, *, pool, config)` style)
- `/start`, `/help`, `/status` remain unrestricted to any tier per task spec

## 5. Known issues

- **Allowlist is in-memory only.** Per task `Not in Scope: Postgres persistence`. Allowlist resets on every container restart; operator must re-`/allowlist add` after redeploy. Persistence will land in a follow-up lane (likely consolidated with R4 ledger crediting or a dedicated R3.1 follow-up).
- **No test coverage in this lane** (per task scope). Manual verification path: deploy + send `/allowlist list` from non-operator → expect `⛔ Unauthorized.`; then from operator chat → expect `📋 Allowlist is empty.`; `/allowlist add 12345` → expect `✅ User 12345 added...`; `/allowlist list` → expect single bullet; `/status` from user 12345 → expect `Tier 2 — Community allowlisted`; `/status` from any other user → `Tier 1 — Browse only`.
- **`require_tier` decorator has no consumer in this lane.** It's scaffolded for R5+ command handlers. Verified by code review only — runtime behavior will be exercised when first `@require_tier(TIER_ALLOWLISTED)` is applied (R5 strategy config commands).
- **Tier 3 / Tier 4 not yet modeled.** `get_user_tier` returns only 1 or 2. Funded-beta (Tier 3, deposit confirmed) and live-auto-trade (Tier 4, all activation guards SET) gates are deferred to R4 (deposit watcher) and R7+ (live activation) respectively.
- **`OPERATOR_CHAT_ID` semantic dual-use.** This env var was originally added in R1 as the operator's chat for alerts. R3 reuses it as the operator's user_id for command authorization (per WARP🔹CMD direction: no duplicate env var). For private chats with the bot, chat_id == user_id, so this works in practice. If the operator interacts via a group chat, separate vars may be required — defer to future ops phase if/when that's needed.
- **`/allowlist` allows the operator to add their own ID.** Not blocked. Operator is implicitly Tier 2+ regardless of allowlist membership for R3 purposes (operator gating is via `OPERATOR_CHAT_ID` match, not tier). If desired, future hardening can refuse self-adds with a friendly message.
- **No rate limiting on `/allowlist`.** A misbehaving operator session could spam add/remove. Rate-limit primitive deferred to ops/monitoring lane (R12).

## 6. What is next

- **R4 — Deposit watcher + ledger crediting** (MAJOR tier): Polygon chain watcher for USDC deposits to per-user HD-derived addresses, ledger crediting, sub-account balance updates, deposit confirmation Telegram notifications, Tier 3 promotion on first confirmed deposit ≥ `MIN_DEPOSIT_USDC`.
- Post-merge sync per AGENTS.md POST-MERGE SYNC RULE: bump PROJECT_STATE.md from IN PROGRESS → COMPLETED for R3; ROADMAP R3 row 🚧 → ✅; append CHANGELOG entry with merge SHA.

---

**Validation Tier:** STANDARD — operator command surface + tier-resolution helper + middleware primitive. No risk/capital/execution paths touched. WARP•SENTINEL NOT ALLOWED on STANDARD per AGENTS.md.

**Claim Level:** FOUNDATION — allowlist store and tier-gate decorator are functional but no production tier-gated command exists yet (R5+ scope). Paper mode preserved; all activation guards remain OFF.

**Validation Target:** (a) non-operator calling `/allowlist` → blocked with `⛔ Unauthorized.`; (b) operator calling `/allowlist add <id>` → user added, confirmation reply; (c) `/allowlist list` shows markdown-bulleted member list (or empty message); (d) `get_user_tier(id)` returns 1 by default, 2 when added to allowlist; (e) `/start` and `/status` work for all tiers; (f) `/status` reply opens with caller's tier label; (g) `require_tier(TIER_ALLOWLISTED)` decorator denies tier-1 callers and admits tier-2 callers (verified by code-path review; no runtime consumer in this lane); (h) module-level singleton pattern works with no `main.py` change.

**Not in Scope:** Postgres persistence for allowlist, Tier 3/Tier 4 gates, applying `require_tier` to existing commands, trading logic, wallet logic, activation guard changes, fee system, modifications to legacy polyquantbot/ tree.

**Suggested Next:** WARP🔹CMD review on PR (STANDARD; SENTINEL not allowed). On merge → R4 deposit watcher lane.
