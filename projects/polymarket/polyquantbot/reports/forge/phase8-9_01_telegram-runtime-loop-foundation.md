# Phase 8.8 Post-Merge Truth Sync + Phase 8.9 Real Telegram Polling / Runtime Loop Foundation

**Date:** 2026-04-19 15:21
**Branch:** claude/phase8-9-telegram-runtime-I5Jnb
**Validation Tier:** MAJOR (Part B); MINOR (Part A)
**Claim Level:** FOUNDATION
**Validation Target:** TelegramRuntimeAdapter abstract boundary; HttpTelegramAdapter Bot API calls; extract_command_context inbound mapping; TelegramPollingLoop dispatch + reply routing; run_polling_loop top-level wiring; bot.py adapter/loop wiring; staging identity contract
**Not in Scope:** full polished Telegram UX, broad command suite beyond /start, production-grade identity resolution, OAuth rollout, RBAC rollout, delegated signing lifecycle, exchange execution rollout, portfolio engine rollout, full web UX rollout, production Telegram deployment orchestration
**Suggested Next:** SENTINEL validation required before merge (Tier: MAJOR)

---

## 1. What Was Built

### Part A — Phase 8.8 Post-Merge Truth Sync (MINOR)

- `PROJECT_STATE.md` updated: Phase 8.8 moved from IN PROGRESS to COMPLETED (SENTINEL CONDITIONAL gate satisfied via `phase8-8_02_pytest-evidence-pass.md`, 77/77 pass); Phase 8.9 added to IN PROGRESS; NEXT PRIORITY updated to SENTINEL for Phase 8.9. Timestamp advanced from `2026-04-19 14:01` to `2026-04-19 15:21`.
- `ROADMAP.md` updated: Phase 8.8 checklist status changed from `🚧 In Progress — SENTINEL validation required before merge` to `✅ Done (merged. SENTINEL CONDITIONAL gate satisfied via phase8-8_02_pytest-evidence-pass.md, 77/77 pass. PR #606 merged, PR #607 CONDITIONAL satisfied)`; Phase 8.9 checklist section added.
- Stale wording removed: no more "In Progress" or "SENTINEL validation pending" for Phase 8.8.
- Truthful references preserved:
  - `projects/polymarket/polyquantbot/reports/forge/phase8-8_01_telegram-dispatch-foundation.md`
  - `projects/polymarket/polyquantbot/reports/forge/phase8-8_02_pytest-evidence-pass.md`
  - SENTINEL: PR #607 (CONDITIONAL gate satisfied)

### Part B — Phase 8.9 Real Telegram Polling / Runtime Loop Foundation (MAJOR)

**1. Telegram Runtime Adapter Boundary (`client/telegram/runtime.py`)**

- `TelegramInboundUpdate` — normalized inbound update dataclass (`update_id`, `chat_id`, `from_user_id`, `text`, `message_id`)
- `TelegramRuntimeAdapter` — abstract boundary with two methods: `get_updates(offset, limit)` and `send_reply(chat_id, text)`. The polling loop and dispatcher operate only against this boundary — never against raw Telegram API internals.
- `HttpTelegramAdapter` — concrete implementation calling the Telegram Bot API via httpx:
  - `get_updates()`: long-poll `getUpdates` call; returns `list[TelegramInboundUpdate]`; skips updates without `chat_id` or `from_id`; raises on HTTP error or `ok=false`
  - `send_reply()`: `sendMessage` call; raises on HTTP error
  - `_parse_single_update()`: static method converting raw Telegram update dict to `TelegramInboundUpdate`; returns `None` for malformed/incomplete entries

**2. Context Extraction (`extract_command_context`)**

- Reads `TelegramInboundUpdate.text` and checks for `/` prefix
- Extracts command as first word, lowercased
- Returns `TelegramCommandContext(command, from_user_id, chat_id, tenant_id, user_id)` ready for `TelegramDispatcher.dispatch()`
- Returns `None` for non-command messages (empty, whitespace, no `/` prefix)
- Staging identity contract: `tenant_id` and `user_id` default to `"staging"` because Telegram inbound messages do not carry backend identity; configurable via `CRUSADER_STAGING_TENANT_ID` and `CRUSADER_STAGING_USER_ID` env vars

**3. Polling Loop (`TelegramPollingLoop` + `run_polling_loop`)**

- `TelegramPollingLoop` — stateful loop class (`_offset` tracking):
  - `run_once()`: fetches one batch via adapter, processes each update, advances `_offset` to `update_id + 1` after each, returns count of processed updates
  - `_process_update()`: extracts command context; skips non-commands (logs + no reply); dispatches through `TelegramDispatcher`; sends `reply_text` back through adapter
  - Zero silent failures: dispatch exceptions caught + logged + safe error reply sent; send_reply exceptions caught + logged (loop continues)
- `run_polling_loop()` — top-level async function: creates `TelegramPollingLoop`; runs `run_once()` in a while-True loop; sleeps 1s when no updates (avoids tight loop); sleeps 5s on unexpected errors (natural backoff); exits cleanly on `asyncio.CancelledError`

**4. Bot Bootstrap Update (`client/telegram/bot.py`)**

- Added `staging_tenant_id` and `staging_user_id` to `TelegramBotSettings` with env var bindings (`CRUSADER_STAGING_TENANT_ID`, `CRUSADER_STAGING_USER_ID`)
- `run_bot()` now creates `HttpTelegramAdapter(token=settings.telegram_token)` and calls `run_polling_loop(adapter, dispatcher, staging_tenant_id, staging_user_id)`
- Logs `adapter`, `staging_tenant_id`, `staging_user_id` truthfully at bootstrap
- Phase log advanced from `"8.8"` to `"8.9"`
- No more `_ = dispatcher; await asyncio.sleep(0)` placeholder — real polling loop is now called

**5. Targeted Phase 8.9 Tests (`tests/test_phase8_9_telegram_runtime_20260419.py`)**

17 targeted tests covering:
- `extract_command_context`: `/start` extraction, non-command None, empty/whitespace None, unknown command extraction, command with args, staging defaults
- `TelegramPollingLoop.run_once()`: `/start` dispatch invocation, reply routing to adapter, unknown command fallback, non-command skip (no dispatch), dispatch exception → safe error reply, offset advancement, empty updates (count=0), send_reply exception no crash, mixed update batch (3 updates: /start + non-command + /help), staging contract propagation

---

## 2. Current System Architecture (Relevant Slice)

```
Telegram Bot API (long-poll)
        |
        v
HttpTelegramAdapter.get_updates(offset)
  -> GET /bot{token}/getUpdates?offset=N&limit=100&timeout=30
  -> _parse_single_update(raw) -> TelegramInboundUpdate
        |
        v
TelegramPollingLoop.run_once()
  for each TelegramInboundUpdate:
        |
        v
extract_command_context(update, tenant_id, user_id)
  text.startswith('/') -> TelegramCommandContext(command, from_user_id, chat_id, tenant_id, user_id)
  else -> None (skipped, logged)
        |
        v
TelegramDispatcher.dispatch(ctx)
  ctx.command == "/start" -> _dispatch_start() -> handle_start()
  else -> DispatchResult(outcome="unknown_command", reply_text="Unknown command...")
        |
        v
DispatchResult.reply_text
        |
        v
HttpTelegramAdapter.send_reply(chat_id, reply_text)
  -> POST /bot{token}/sendMessage {chat_id, text}

Staging identity contract (Phase 8.9):
  tenant_id = CRUSADER_STAGING_TENANT_ID env var (default: "staging")
  user_id   = CRUSADER_STAGING_USER_ID env var   (default: "staging")
  Production identity resolution is a follow-up lane.

Persistence backbone (unchanged from Phase 8.6/8.7/8.8):
  PersistentMultiUserStore  (multi_user.json)    <- restart-safe ownership
  PersistentSessionStore    (sessions.json)      <- restart-safe sessions
  PersistentWalletLinkStore (wallet_links.json)  <- restart-safe wallet-links
```

---

## 3. Files Created / Modified (Full Repo-Root Paths)

### Created
- `projects/polymarket/polyquantbot/client/telegram/runtime.py`
- `projects/polymarket/polyquantbot/tests/test_phase8_9_telegram_runtime_20260419.py`
- `projects/polymarket/polyquantbot/reports/forge/phase8-9_01_telegram-runtime-loop-foundation.md` (this file)

### Modified
- `projects/polymarket/polyquantbot/client/telegram/bot.py` (HttpTelegramAdapter wiring + run_polling_loop + staging env vars + phase 8.9 log)
- `PROJECT_STATE.md` (Phase 8.8 COMPLETED + Phase 8.9 IN PROGRESS + NEXT PRIORITY updated + timestamp advanced)
- `ROADMAP.md` (Phase 8.8 Done + Phase 8.9 checklist added + Last Updated advanced)

---

## 4. What Is Working

**TelegramRuntimeAdapter boundary (unit-tested via MockTelegramAdapter):**
- `TelegramRuntimeAdapter` is abstract — concrete implementations must implement `get_updates` and `send_reply`
- `MockTelegramAdapter` correctly satisfies the interface and captures replies

**extract_command_context (unit-tested, 7 tests):**
- `/start` text → `TelegramCommandContext(command="/start", ...)`
- Non-command text → `None`
- Empty / whitespace text → `None`
- Unknown command → context with correct command string
- Command with trailing args → command extracted as first token only
- Staging defaults propagated when not overridden

**TelegramPollingLoop (unit-tested, 10 tests):**
- `/start` update → `dispatcher.dispatch()` called with correct context
- `DispatchResult.reply_text` → `adapter.send_reply(chat_id, reply_text)` called
- Unknown command → real dispatcher returns `unknown_command` reply → sent via adapter
- Non-command text → no dispatch, no reply (skipped and logged)
- Dispatch exception → safe error reply sent → loop continues
- `_offset` advances to `last_update_id + 1` after batch
- Empty update batch → returns 0
- `send_reply` exception → caught + logged → loop continues (count still increments)
- Mixed batch (3 updates) → correct count=3, dispatch=2, replies=2, offset=43
- Staging contract propagated from loop config to extracted context

**Full pytest evidence (94/94 pass):**
```
platform linux -- Python 3.11.15, pytest-9.0.2, pluggy-1.6.0

Phase 8.9 runtime loop tests (17/17):
test_extract_command_context_start                         PASSED
test_extract_command_context_non_command                   PASSED
test_extract_command_context_empty_text                    PASSED
test_extract_command_context_whitespace_text               PASSED
test_extract_command_context_unknown_command               PASSED
test_extract_command_context_command_with_args             PASSED
test_extract_command_context_staging_defaults              PASSED
test_polling_loop_run_once_dispatches_start                PASSED
test_polling_loop_run_once_sends_reply                     PASSED
test_polling_loop_run_once_unknown_command_fallback        PASSED
test_polling_loop_run_once_non_command_no_dispatch         PASSED
test_polling_loop_run_once_dispatch_exception_sends_error_reply PASSED
test_polling_loop_run_once_advances_offset                 PASSED
test_polling_loop_run_once_empty_updates                   PASSED
test_polling_loop_run_once_send_reply_exception_no_crash   PASSED
test_polling_loop_run_once_multiple_mixed_updates          PASSED
test_polling_loop_uses_staging_contract                    PASSED

Phase 8.8 regression (15/15): all PASSED
Phase 8.7 regression (16/16): all PASSED
Phase 8.6 regression (13/13): all PASSED
Phase 8.5 regression (13/13): all PASSED
Phase 8.4 regression (12/12): all PASSED
Phase 8.1 regression  (8/8):  all PASSED

94 passed, 1 warning in 3.82s
```

---

## 5. Known Issues

- `HttpTelegramAdapter` requires a real Telegram Bot API token to operate — tests exercise the adapter boundary via `MockTelegramAdapter`, not a live API call
- Staging identity contract: `tenant_id` and `user_id` default to `"staging"` because Telegram inbound messages do not carry backend user identity. Production identity resolution (mapping Telegram user IDs to backend user/tenant records) is a follow-up lane.
- `run_polling_loop()` runs indefinitely until `asyncio.CancelledError` — no built-in max-iteration or shutdown signal mechanism beyond cancellation; graceful shutdown orchestration is a follow-up lane
- Only `/start` is dispatched through the real backend path; all other commands return `unknown_command` with safe reply
- `Unknown config option: asyncio_mode` warning in pytest is pre-existing hygiene backlog (non-runtime, carried forward)

---

## 6. What Is Next

SENTINEL validation required for Phase 8.9 before merge.

Source: `projects/polymarket/polyquantbot/reports/forge/phase8-9_01_telegram-runtime-loop-foundation.md`
Tier: MAJOR
Claim Level: FOUNDATION

Validation Target:
- `TelegramRuntimeAdapter` abstract boundary enforced (no direct API calls in loop/dispatcher)
- `extract_command_context()` returns correct `TelegramCommandContext` for commands; `None` for non-commands
- `TelegramPollingLoop.run_once()` dispatch + reply routing contract
- Dispatch exception → safe error reply, loop does not crash
- `send_reply` exception → caught, logged, loop continues
- Offset advancement correctness
- Staging identity contract: `tenant_id` / `user_id` from env vars propagated to context
- Phase 8.8 regression: 15/15 pass preserved
- Full 94/94 regression pass

After SENTINEL validates and COMMANDER approves merge, the next public-readiness lanes are:
- Production identity resolution: mapping `from_user_id` to backend `tenant_id`/`user_id` via a user lookup service
- Graceful shutdown signal handling for the polling loop
- Additional commands beyond `/start` (e.g. `/status`, `/help`)
- RBAC / permission scope hardening

---

**Validation Tier:** MAJOR (Part B) / MINOR (Part A — truth sync only)
**Claim Level:** FOUNDATION
**Validation Target:** TelegramRuntimeAdapter boundary; extract_command_context mapping; TelegramPollingLoop dispatch + reply routing; bot.py real polling loop wiring; staging identity contract
**Not in Scope:** full polished Telegram UX, broad command suite beyond /start, production identity resolution, OAuth, RBAC, delegated signing lifecycle, exchange execution rollout, portfolio engine rollout, full web UX rollout, production Telegram deployment orchestration
**Suggested Next:** SENTINEL validation required before merge
