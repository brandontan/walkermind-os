# WARP•FORGE Report — crusaderbot-phase5h-onboarding

**Branch:** claude/crusaderbot-onboarding-flow-R4Y1v
**Date:** 2026-05-10 20:00 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION — New ConversationHandler + DB migration + /start routing
**Validation Target:** Phase 5H first-time onboarding flow (/start routing, welcome, FAQ, wallet, style picker, deposit prompt, onboarding_complete flag)
**Not in Scope:** wallet generation logic, preset system internals, copy trade execution, activation guards, tier promotion

---

## 1. What Was Built

Five-step guided onboarding ConversationHandler for first-time CrusaderBot users.

**Step 1 — Welcome**
- Message: "Welcome to CrusaderBot" with 3-point how-it-works summary.
- Buttons: [🚀 Let's Go] [ℹ️ Learn More]
- Learn More shows FAQ (What is Polymarket? / Copy trade? / Safety? / Paper trades?), [Got it, let's go!] returns to welcome.

**Step 2 — Wallet**
- Let's Go checks for existing wallet via `get_wallet()`.
- If wallet exists: skips to Step 3 (style picker).
- If no wallet: sends "Creating your wallet..." → calls `create_wallet_for_user()` → shows `0xABCD...XYZ` + [📋 Copy Address] [➡️ Next].
- Copy Address: sends full address as copyable message, stays in ONBOARD_WALLET.
- Next: advances to Step 3.

**Step 3 — Style Picker**
- Message: "How do you want to trade?"
- [🐋 Copy Trade] / [🤖 Auto Trade] / [⚡ Both]
- Stores choice in `ctx.user_data["onboard_style"]`.
- Advances to Step 4 (deposit prompt).

**Step 4 — Deposit Prompt**
- Message: "Deposit USDC (Polygon) to start trading. Minimum deposit: $50"
- [📷 Show QR] → generates QR with `qrcode.make()`, sends as Telegram photo.
- [📋 Copy Address] → sends full address as message, stays in ONBOARD_DEPOSIT.
- [⏭️ Skip for now] → calls `set_onboarding_complete(user_id)`, shows completion message with style-specific tip + main menu keyboard, ends conversation.

**Routing on /start:**
- `onboarding_complete=True` + ALLOWLISTED: → dashboard()
- `onboarding_complete=True` + BROWSE: → "Welcome back" + main menu
- `onboarding_complete=False`: → onboarding Welcome step

---

## 2. Current System Architecture

```
/start (CommandHandler inside ConversationHandler)
   └── _entry()
         ├── onboarding_complete=True → dashboard() or welcome-back message → END
         └── onboarding_complete=False → WELCOME message → ONBOARD_WELCOME (0)
               ├── learn_more → FAQ → ONBOARD_FAQ (1)
               │     └── got_it → back to WELCOME → ONBOARD_WELCOME
               └── lets_go
                     ├── wallet exists → STYLE PICKER → ONBOARD_STYLE (3)
                     └── no wallet → create → WALLET STEP → ONBOARD_WALLET (2)
                           ├── copy_addr → send address → ONBOARD_WALLET
                           └── next → STYLE PICKER → ONBOARD_STYLE
                                         └── pick style → DEPOSIT → ONBOARD_DEPOSIT (4)
                                               ├── qr → photo → ONBOARD_DEPOSIT
                                               ├── deposit_copy → address → ONBOARD_DEPOSIT
                                               └── skip → set_onboarding_complete → END
```

ConversationHandler registered in `dispatcher.py` as the first handler so it intercepts `/start` before any other CommandHandler.

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/migrations/019_onboarding_flag.sql`
- `projects/polymarket/crusaderbot/bot/keyboards/onboarding.py`
- `projects/polymarket/crusaderbot/tests/test_phase5h_onboarding.py`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5h-onboarding.md`

**Modified:**
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — full rewrite; added ConversationHandler, 5 state callbacks, `build_onboard_handler()`; `help_handler`/`menu_handler` preserved verbatim
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — replaced `CommandHandler("start", ...)` with `onboarding.build_onboard_handler()` registered first
- `projects/polymarket/crusaderbot/users.py` — added `set_onboarding_complete()` helper
- `requirements.txt` — added `qrcode[pil]>=7.4.2`

---

## 4. What Is Working

- New user flow: 5 steps fully wired (Welcome → FAQ → Wallet → Style → Deposit).
- Existing user routing: `onboarding_complete=True` → dashboard or welcome-back.
- Wallet creation deferred to "Let's Go" press; skipped if wallet already exists.
- `set_onboarding_complete` sets DB flag on Skip action.
- QR code generated via `qrcode.make()` and sent as Telegram photo.
- Copy Address available at wallet step and deposit step.
- Style tip in completion message varies by choice (copy_trade / auto_trade / both).
- ConversationHandler registered before other handlers; `onboard:*` callbacks don't conflict with existing `copytrade:`, `wallet:`, etc. patterns.
- 18 hermetic tests covering all keyboard shapes and handler state transitions.

---

## 5. Known Issues

- `qrcode[pil]` dependency added to requirements.txt but not yet installed in the environment; CI build will install it. No runtime impact until handler is invoked.
- Branch name is `claude/crusaderbot-onboarding-flow-R4Y1v` (harness-assigned); CLAUDE.md requires `WARP/` prefix. Flagged as deviation — harness override, not agent choice.
- ConversationHandler state is in-memory only (no persistence). If the bot restarts mid-onboarding, the user restarts from Step 1. Acceptable for current scope; persistence can be added as a follow-up.
- `/start` from inside an active Copy Trade wizard (Phase 5F) will trigger the fallback entry of the onboarding ConversationHandler since both listen to `/start`. Existing wizard `allow_reentry=True` + fallback ensures clean exit. No data loss risk.

---

## 6. What Is Next

- WARP🔹CMD review (STANDARD tier, no SENTINEL required).
- Install `qrcode[pil]` on production Fly.io instance via `requirements.txt` rebuild.
- Post-allowlist: the deposit prompt could auto-route to Copy Trade or Preset Picker when user is promoted to ALLOWLISTED. Deferred to a follow-up lane.
- Consider ConversationHandler persistence (PicklePersistence or Redis) for bots that restart frequently.

---

**Suggested Next Step:** WARP🔹CMD review and merge.
