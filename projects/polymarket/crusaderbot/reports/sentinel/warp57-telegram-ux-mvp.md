# WARP•SENTINEL — WARP-57 Telegram UX MVP v1 (PR #1261)

**Branch:** WARP/warp57-telegram-ux-mvp
**Head SHA:** 271c7e0d630cbd2caa3bc9769401c469689a712d
**Dispatched by:** WARP🔹CMD — issue #1262
**Tier:** MAJOR
**Claim under audit:** FOUNDATION (UX rendering + routing — execution / strategy / risk engines untouched)
**Environment assumed:** dev (no live infra), paper-trade runtime intact

---

## 1. Test Plan

Phase 0 — Pre-Test gate (report + state + structure).
Phase 1 — Callback routing across all MVP prefixes; legacy regression surface.
Phase 2 — Quick Start journey readiness (code paths only — no live Telegram run in this audit).
Phase 3 — Failure modes for DB unavailability / missing columns / unknown user.
Phase 4 — Async safety in MVP handlers.
Phase 5 — Activation guard immutability (`ENABLE_LIVE_TRADING` / `EXECUTION_PATH_VALIDATED` / `CAPITAL_MODE_CONFIRMED` / `RISK_CONTROLS_VALIDATED`).
Phase 7/8 — Telegram preview review (no live screenshots in this audit — code-level only).

---

## 2. Findings (per-phase, with file:line evidence)

### Phase 0 — Pre-Test gate

- Forge report present at `projects/polymarket/crusaderbot/reports/forge/warp57-telegram-ux-mvp.md` with all 6 mandatory sections + metadata (Tier, Claim, Target, Not in Scope, Suggested Next Step). PASS.
- `state/PROJECT_STATE.md` updated (`Last Updated : 2026-05-21 18:00`, WARP-57 line flipped to "FORGE delivered"). PASS.
- No `phase*/` folders in tree. PASS.
- All 26 new MVP modules + dispatcher `py_compile` clean (verified locally). PASS.
- Branch verified: `git rev-parse --abbrev-ref HEAD` = `WARP/warp57-telegram-ux-mvp` (matches WARP🔹CMD declaration). PASS.

### Phase 1 — Callback routing + legacy regression surface

- MVP `attach()` is registered FIRST in `bot/dispatcher.py:165-174`, so MVP CallbackQueryHandlers for `dashboard:` / `auto:` / `copy:` / `portfolio:` / `markets:` / `settings:` / `help:` win over legacy handlers within group=0. Verified.
- `menu:*` taps from persistent reply-kb route through `_menu_nav_cb` (group=-1) to MVP entries — `bot/dispatcher.py:60-94`. Verified.
- `nav:*` global navigation routes through `_nav_cb` (group=-1) to MVP dashboard fallback — `bot/dispatcher.py:104-123`. Verified.
- Persistent reply-keyboard regex handlers (📊 Dashboard / 🤖 Auto-Trade / 💼 Portfolio / ⚙️ Settings / ❓ Help) retargeted to MVP — `bot/dispatcher.py:183-196`. Verified.
- **REGRESSION** — `bot/dispatcher.py:212` keeps `/settings` routed to legacy `settings_handler.settings_root`. The legacy hub keyboard emits buttons whose callback_data MVP does not route: `settings:tpsl`, `settings:capital`, `settings:profile`, `settings:referrals`, `settings:redeem`, `settings:hub`, `settings:notif_on`, `settings:notif_off`, `settings:health`, `settings:admin`, `settings:wallet`, `settings:back` (see `bot/handlers/settings.py:161-351`). MVP `_settings_cb` (`bot/handlers/mvp/settings.py:106-131`) ignores those sub-tokens and silently falls through to `show_home`. Users reaching the legacy hub via `/settings` will get redirected to MVP home instead of the intended sub-screen. Severity: MEDIUM (functional regression for legacy /settings entrants).

### Phase 2 — Quick Start journey (code path)

- `/start` (MVP) → `mvp_onboarding.start_command` (`bot/handlers/mvp/onboarding.py:48-58`) routes returning users to MVP dashboard via `dash.show_dashboard`, new users to welcome screen. Verified path.
- Welcome → `auto:quick_start` → `auto:configure:strategy:<x>` → `auto:configure:capital:<n>` → `auto:configure:risk:<x>` → `auto:start` → `do_start` (`bot/handlers/mvp/autotrade.py:126-138`). Wizard state lives in `ctx.user_data["mvp_auto_flow"]`. Verified.
- `do_start` flips `users.auto_trade_enabled = TRUE` + `users.paused = FALSE` via `_users.set_auto_trade` / `_users.set_paused` only. **No preset-activation bootstrap call.** The legacy autotrade flow (`bot/handlers/autotrade.py:autotrade_callback`) does additional preset-activation that MVP skips. Forge report explicitly flagged this; left unresolved in code. Severity: MEDIUM (engine may not wake until the existing scheduler tick re-reads the flag).

### Phase 3 — Failure modes (defensive read patterns)

- Every DB accessor in `_users.py` is wrapped in `try / except Exception: log.debug(...)` returning defaults — `bot/handlers/mvp/_users.py:16-119`. Verified — no traceback can leak to chat.
- `send_or_edit` handles Telegram BadRequest "message is not modified" + edit-fail fallback to `reply_text` — `bot/handlers/mvp/_send.py:14-46`. Risk 5: PASS.
- 4-level relative imports (`from ....users import ...` etc.) resolve to `crusaderbot.users` / `crusaderbot.database` / `crusaderbot.wallet.ledger` because `bot/` is a sub-package of `crusaderbot/` (verified — `__init__.py` exists at `projects/polymarket/crusaderbot/__init__.py`, and `users.py`, `database.py`, `wallet/ledger.py` all live at that level). Imports cleared. Risk 4: PASS.

### Phase 4 — Async safety

- All MVP handlers are `async def`; no `threading` imports. All DB calls via `async with pool.acquire()`. No shared mutable state outside `ctx.user_data` (per-user). No race conditions identified. PASS.

### Phase 5 — Activation guard immutability

- Grep across `bot/handlers/mvp/`, `bot/keyboards/mvp/`, `bot/messages_mvp.py`, `bot/ui/` for `ENABLE_LIVE_TRADING|EXECUTION_PATH_VALIDATED|CAPITAL_MODE_CONFIRMED|RISK_CONTROLS_VALIDATED|enable_live` — only one hit, a docstring comment in `bot/handlers/mvp/settings.py:52`. **No code path writes any activation guard.** PASS.
- `settings:mode:live` route opens `live_gate_kb` showing lock screen + "Request Access" button (`bot/keyboards/mvp/settings.py:35-40`) — no flip. Risk 3: PASS.
- Risk-control sub-buttons (`settings:risk:loss_limit`, `position_size`, `concurrent`, `auto_pause`) fall through to `show_risk()` (re-render only). Display-only — consistent with FOUNDATION claim.
- `_read_settings` reads `u.get("live_mode_enabled") or u.get("live_trading_enabled")` (`bot/handlers/mvp/settings.py:34`) — neither column exists in `users` table (verified — no hits in migrations or `users.py`). Falsy → `trading_mode = PAPER` always. Paper-mode default preserved (Risk 6: PASS), though by accident of column absence rather than principle.

### Phase 7/8 — Telegram preview

- No live Telegram preview captured in this audit (dev environment, no bot token attached). Renderer output verified against blueprint section 4.1 spacing by reading `bot/messages_mvp.py` and `bot/ui/tree.py` constants only.

---

## 3. Critical Issues

### CRITICAL-1 — `copy_targets` schema mismatch causes silent persistence failure

**Files:**
- `bot/handlers/mvp/copy_wallet.py:43-54` — SELECT
- `bot/handlers/mvp/copy_wallet.py:140-148` — INSERT
- `bot/handlers/mvp/copy_wallet.py:170-176` — UPDATE on pause

**Schema (truth from migrations):**

- `migrations/001_init.sql:77-86` — legacy columns: `wallet_address`, `enabled`, `scale_factor`, `last_seen_tx`.
- `migrations/009_copy_trade.sql:56-65` — canonical columns: `target_wallet_address`, `status` ('active'/'inactive'), `scale_factor`, `trades_mirrored`.
- **No `target_address` column** in either revision.
- **No `allocation_usdc` column** anywhere in `copy_targets`.

**Effect:**
- INSERT references `target_address` + `allocation_usdc` → `UndefinedColumnError` → caught silently by `except Exception: log.debug(...)` at `copy_wallet.py:150-151` → handler returns success to UI (`show_home`) and user sees "wallet added" UX with no row written.
- SELECT references the same missing columns → asyncpg raises → caught → empty list → user sees "no wallets" forever.
- UPDATE on pause uses legacy `enabled` column; works on upgraded DBs that retained it (001_init.sql), but fails on a fresh deploy that runs 009 without 001's legacy column. Either way, the canonical column per migration 009 is `status`, not `enabled`.

**Why this matters:** the Copy Wallet flow is one of two flagship MVP surfaces. The defective persistence path looks identical to a working one from the user's POV — there's no error surfaced. This is a UX-deceptive silent-failure pattern that violates "Zero silent failures" in the engineering standards. Forge report `[Known issues] §1` flagged the table-name risk explicitly and deferred verification to SENTINEL; verification confirms the mismatch.

**Fix (one file):** in `bot/handlers/mvp/copy_wallet.py`, swap:
- `target_address` → `target_wallet_address`
- `allocation_usdc` → drop from INSERT / SELECT (column does not exist); use `scale_factor` if a per-wallet capital fraction is required, or add the column via a new migration before merging.
- `enabled` → `status IN ('active', 'inactive')` — toggle by `status = 'active'` / `status = 'inactive'`.

**Verdict impact:** Single critical issue → BLOCKED per CLAUDE.md sentinel rule ("ANY single critical issue = BLOCKED. No exceptions.").

---

## 4. Non-Critical Findings

### MEDIUM-1 — `wallets.public_address` does not exist

`bot/handlers/mvp/onboarding.py:38` reads `SELECT public_address FROM wallets WHERE user_id=$1`. Actual column per `migrations/001_init.sql:30` is `deposit_address`. Result: `UndefinedColumn` → caught → wallet_addr None → onboarding shows placeholder `0x12...ab9` rather than the user's real deposit address. Fix: rename to `deposit_address`.

### MEDIUM-2 — `auto:start` does not bootstrap engine

`bot/handlers/mvp/autotrade.py:126-138` only flips two flags (`auto_trade_enabled=TRUE`, `paused=FALSE`). The legacy preset-activation entry (`bot/handlers/autotrade.py:autotrade_callback`) performs additional work that MVP skips. Whether the scanner picks up the flag flip without that work depends on existing schedule cadence — not verified in this audit. Forge report flagged; left unresolved.

### MEDIUM-3 — Legacy `settings:*` sub-routes silently redirected

See Phase 1 finding. `/settings` (line 212) → legacy hub → buttons emitting `settings:tpsl|capital|profile|referrals|redeem|hub|...` → MVP `show_home` instead of the intended destination. Fix options: (a) remove `/settings` legacy entry and re-route to MVP `settings_home`, or (b) widen MVP `_settings_cb` to detect unknown sub-tokens and delegate to `settings_handler.settings_callback` instead of fallback-to-home.

### LOW-1 — `users.live_mode_enabled` / `live_trading_enabled` columns do not exist

`bot/handlers/mvp/settings.py:34` — both column lookups return `None`, so `trading_mode = PAPER` always. The display is correct by accident; if a future migration adds either column, the UX will start reflecting state that the actual execution guard (`ENABLE_LIVE_TRADING`) may not match. Recommend either reading the env guard directly or removing the column reads.

### LOW-2 — Risk-control sub-buttons are display-only

`bot/keyboards/mvp/settings.py:43-50` emits `settings:risk:loss_limit|position_size|concurrent|auto_pause` but `_settings_cb` only routes `screen == "risk"` and ignores `parts[2]`. Buttons re-render the same screen. Forge report consistent ("all UI-display only").

### LOW-3 — `/start` shadowing of legacy ConversationHandler

`bot/dispatcher.py:174` registers MVP `/start` before `build_start_handler()` (line 201). MVP wins; legacy ConversationHandler's `/start` entry is shadowed. Mid-conversation users won't reset cleanly. Forge report acknowledged.

---

## 5. Stability Score

| Bucket | Weight | Score | Reasoning |
| --- | --- | --- | --- |
| Architecture | 20 | 16 | Clean additive layer; precedence rules sound. Silent-failure pattern on DB writes is a structural concern. |
| Functional | 20 | 10 | Most surfaces correct; copy-wallet add/list/pause broken on canonical schema; legacy `/settings` sub-route regression; `auto:start` may not wake engine. |
| Failure modes | 20 | 16 | Defensive `try/except + log.debug` everywhere; renderers degrade to defaults; BadRequest "not modified" handled. Silent persistence success-lies cost 4 points. |
| Risk rules | 20 | 20 | No activation guard touched; paper-mode preserved; no manual trade buttons; Kelly/limits display-only. |
| Infra + Telegram | 10 | 8 | Renderers render; no live Telegram preview attached to this audit. |
| Latency | 10 | 8 | Simple async DB reads; no measurable impact predicted. |
| **Total** | **100** | **78** | — |

---

## 6. GO-LIVE Status

**Verdict: BLOCKED**

Reason: CRITICAL-1 (copy-wallet schema mismatch — silent persistence failure on the canonical `copy_targets` schema). Per CLAUDE.md sentinel rule: "ANY single critical issue = BLOCKED. No exceptions."

Note: the rest of the audit surface is clean (score 78/100 on non-critical buckets). With CRITICAL-1 resolved and a re-spin, this is on track for APPROVED.

---

## 7. Fix Recommendations (priority order)

1. **[CRITICAL — required before merge]** `bot/handlers/mvp/copy_wallet.py` — rewrite SQL to canonical `copy_targets` schema:
   - INSERT/UPDATE/SELECT: `target_wallet_address` (not `target_address`)
   - SELECT: drop `allocation_usdc` (or add a migration introducing it)
   - Pause/resume: toggle `status = 'active' / 'inactive'` instead of `enabled = TRUE/FALSE`
   - Verify on a fresh deploy of `migrations/009_copy_trade.sql` that INSERT/SELECT/UPDATE all succeed.
2. **[MEDIUM]** `bot/handlers/mvp/onboarding.py:38` — rename `public_address` → `deposit_address` (matches `migrations/001_init.sql:30`).
3. **[MEDIUM]** `bot/handlers/mvp/autotrade.py:do_start` — either (a) confirm the scanner picks up `auto_trade_enabled` on its next tick (paper-mode evidence), or (b) delegate to the legacy preset-activation entry point. Document in the forge follow-up.
4. **[MEDIUM]** `bot/dispatcher.py` — decide on legacy `/settings` posture: either retarget `/settings` command to `mvp_settings.show_home`, or widen `_settings_cb` to delegate unknown sub-tokens to `settings_handler.settings_callback`.
5. **[LOW]** `bot/handlers/mvp/settings.py:34` — read `os.getenv("ENABLE_LIVE_TRADING")` (or the canonical guard accessor) instead of non-existent `users.live_mode_enabled` columns.
6. **[LOW]** `bot/keyboards/mvp/settings.py:43-50` — either implement the risk sub-flows or downgrade buttons to coming-soon labels.

---

## 8. Telegram Preview

Not captured in this audit — dev environment without a live bot token. Recommend WARP🔹CMD or the forge follow-up attach screenshots of the 7 main surfaces (Dashboard / Auto Trade home / Copy Wallet home / Portfolio home / Markets home / Settings home / Help home) before merge gate review.

---

## Done

GO-LIVE: BLOCKED. Score 78/100. Critical: 1.

