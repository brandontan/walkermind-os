# telegram-live-truth — gate-7 2FA truth sync + /wallet command

Role: WARP•R00T | Branch: WARP/root-telegram-live-truth | Linear: WARP-97
Date: 2026-06-11 Asia/Jakarta
Source gap: reports/forge/readiness-matrix.md row 8(b)+(c) — Telegram bot × LIVE

## 1. What was built

1. `domain/activation/live_checklist.py` gate-7 truth sync: the `_gate_two_factor` docstring claimed "Self-serve 2FA infrastructure does not yet exist" — false since #1737 shipped web-side TOTP (`domain/auth/totp.verify_and_enable` writes the exact `system_settings` key `2fa_enabled:{user_id}` the gate reads). Docstring now states the shipped contract (web enrolment lights the gate automatically; operator manual flip = break-glass fallback). The user-facing `GATE_FIX_HINTS[GATE_TWO_FACTOR_SETUP]` no longer says "Contact an admin until self-serve 2FA ships" — it directs users to WebTrader → Settings → Two-Factor Authentication. NO behavioral change: the gate read path, key, and fail-closed default are byte-unchanged (the #1737 write/read pin test `test_live_checklist_gate_reads_the_flag_we_write` still passes untouched).
2. `bot/dispatcher.py`: registered `CommandHandler("wallet", wallet_root)` — the deposit-gate fix hint (`GATE_FIX_HINTS[GATE_ACTIVE_SUBACCOUNT]`) has always told users "/wallet → Deposit", but the command did not exist (menu route only). `wallet_root` was already imported; one registration line next to /settings.

## 2. Current system architecture (relevant slice)

Live activation UX: /enable_live → live_checklist.evaluate (8 gates) → failed gates render GATE_FIX_HINTS. Gate 4 hint → /wallet (now a real command → wallet_root deposit screen). Gate 7 hint → WebTrader 2FA card (shipped #1737) → verify_and_enable writes `2fa_enabled:{user_id}` → gate passes. No gate logic touched.

## 3. Files created / modified

- projects/polymarket/crusaderbot/domain/activation/live_checklist.py — modified (docstring + one hint string; zero logic)
- projects/polymarket/crusaderbot/bot/dispatcher.py — modified (+1 CommandHandler registration)
- projects/polymarket/crusaderbot/tests/test_telegram_live_truth.py — created (4 tests)
- projects/polymarket/crusaderbot/reports/forge/telegram-live-truth.md — this report
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md, state/CHANGELOG.md — synced

## 4. What is working

- 4 new tests: hint points at shipped web flow / stale claim gone from module source (+ key anchor `2fa_enabled:{user_id}` still present) / /wallet CommandHandler registered (source-regex layer, same pattern as test_paper_default_invariant) / deposit hint ↔ registration pinned together so they cannot drift apart again.
- 78 activation/checklist/totp regression tests pass; full suite **3413 passed / 11 skipped** (+4 on 3409); ruff + py_compile clean.

## 5. Known issues

- None. Telegram-side 2FA enrolment UI remains web-only by design (one account across surfaces via /link); the hint now says exactly that.

## 6. What is next

- Merge on CI green (STANDARD, WARP•R00T authority), then overnight handoff report.

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION (activation UX wording + one command registration)
Validation Target : gate-7 hint/docstring truth; /wallet registration reachable
Not in Scope      : gate evaluation logic (byte-unchanged), 2FA module, wallet handler internals
Suggested Next    : WARP•R00T merge on CI green
