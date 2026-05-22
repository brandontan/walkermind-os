# WARP-64 Forge Report — CI pytest fix

**Branch:** WARP/warp64-ci-fix
**Issue:** #1277
**Date:** 2026-05-22
**Validation Tier:** STANDARD
**Claim Level:** MECHANICAL

---

## 1. What was built

Fixed 4 failing hermetic tests in `tests/test_warp59_copy_wallet_bridge.py` that broke CI after the WARP-62+63 merge. No production code was changed.

Root causes identified and fixed:

**A. Wrong patch target in `_patch_send_or_edit()`**
`copy_wallet.py` imports `send_or_edit` via `from ._send import send_or_edit`, binding the name in its own namespace. The test patched `_send.send_or_edit` (the definition site) instead of `copy_wallet.send_or_edit` (the use site). `unittest.mock.patch` must target the name where it is used. The mock had no effect — the real `send_or_edit` was called, hit `update.effective_message`, and raised `AttributeError`.

Fix: changed patch target to `projects.polymarket.crusaderbot.bot.handlers.mvp.copy_wallet.send_or_edit`.

**B. Missing `effective_message` on `_make_update()` SimpleNamespace**
The mock update object lacked the `effective_message` attribute accessed by `send_or_edit` when `callback_query is None`. Added `effective_message=None` to the SimpleNamespace factory for correctness and as a defense-in-depth guard.

**C. Queue undercount in `test_bridge_end_to_end_visibility_to_list_active_tasks`**
`do_start_copying` calls `show_home` at completion, which calls `_read_wallets`, which issues a second `FROM copy_trade_tasks` fetch. The test queue `[None, [inserted_row]]` had only 2 entries — the first consumed by the upsert probe `fetchrow`, the second consumed by `_read_wallets`. The scanner `list_active_tasks` call in Step 2 then found an empty queue and returned `[]`.

Fix: added a third queue entry `[]` (empty wallet list for `_read_wallets`) so the scanner read receives its `[inserted_row]` as intended.

---

## 2. Current system architecture

Unchanged. Tests are hermetic mocks against `domain/signal/copy_trade.py` and `bot/handlers/mvp/copy_wallet.py` — no production code paths altered.

---

## 3. Files created / modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/tests/test_warp59_copy_wallet_bridge.py` |

Changes:
- `_make_update()`: added `effective_message=None` to SimpleNamespace
- `_patch_send_or_edit()`: patch target `_send.send_or_edit` → `copy_wallet.send_or_edit`
- `test_bridge_end_to_end_visibility_to_list_active_tasks`: queue `[None, [inserted_row]]` → `[None, [], [inserted_row]]`

---

## 4. What is working

- `python -m pytest tests/ -v --tb=short` from `projects/polymarket/crusaderbot/`: **1613 passed, 0 failed, 1 skipped**
- All 6 tests in `test_warp59_copy_wallet_bridge.py` pass
- No regressions in any other test file

---

## 5. Known issues

None introduced by this fix. Pre-existing issues in PROJECT_STATE.md unchanged.

---

## 6. What is next

- WARP🔹CMD review and merge of this PR
- Once merged and CI green: WARP•SENTINEL re-audit can run to lift the BLOCKED verdict (F-001 + F-002 closed in WARP-62+63, CI now green)
- WARP-65: Fix Telegram UX persistent keyboard (`main_menu_kb` → `ReplyKeyboardMarkup`)

---

**Validation Tier:** STANDARD
**Claim Level:** MECHANICAL
**Validation Target:** `tests/test_warp59_copy_wallet_bridge.py` — 4 previously failing tests
**Not in Scope:** production code changes, new test coverage
**Suggested Next Step:** WARP🔹CMD merge → SENTINEL re-audit
