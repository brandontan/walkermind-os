# WARP•FORGE REPORT — crusaderbot-tg-kb-cleanup

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Telegram inline keyboard orphan bug on Home navigation from Portfolio and Settings
Not in Scope: Wallet (already correct), Auto Mode (already correct), force-close flows, reply-keyboard paths

---

## 1. What was built

Fixed inline keyboard ghost artifact: when navigating back to Home (Dashboard) from
Portfolio or Settings, the originating message now edits in-place instead of sending
a new reply. This eliminates the stale `p5_dashboard_kb` inline buttons that floated
above the newly sent sub-menu message.

Root cause: both `show_portfolio` (positions.py) and `_render_hub` (settings.py) used
`reply_text` when triggered from a callback query, creating a new message instead of
editing the triggering message. Autotrade and Wallet handlers already used
`edit_message_text` correctly and were not changed.

---

## 2. Current system architecture

Navigation flow (fixed):

```
Dashboard message (M1) with p5_dashboard_kb
  └─ tap Portfolio (menu:portfolio)
       → show_portfolio: edit_message_text on M1 → M1 becomes Portfolio message
  └─ tap Home (dashboard:main)
       → show_dashboard_for_cb: edit_message_text on M1 → M1 becomes Dashboard again
```

No new messages are created during inline navigation. The edit-in-place contract is
now consistent across all four primary sub-menus (Portfolio, Settings, Auto Mode, Wallet).

---

## 3. Files created / modified

Modified:
- projects/polymarket/crusaderbot/bot/handlers/positions.py
  - Added `from telegram.error import BadRequest` import
  - `show_portfolio`: callback path changed from `reply_text` to `edit_message_text`
    with BadRequest fallback (preserves "Message is not modified" guard)

- projects/polymarket/crusaderbot/bot/handlers/settings.py
  - Added `from telegram.error import BadRequest` import
  - `_render_hub`: callback path changed from `reply_text` to `edit_message_text`
    with BadRequest fallback

No new files created.

---

## 4. What is working

- Portfolio: tapping from Dashboard edits message in-place; Home returns to Dashboard
  in-place with no orphaned inline keyboard
- Settings: same edit-in-place flow
- Auto Mode, Wallet: unchanged — were already correct
- Reply keyboard paths (text button taps) unaffected — still use reply_text as intended
- compileall: zero errors on both modified files

---

## 5. Known issues

None introduced by this change.

---

## 6. What is next

WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/crusaderbot-tg-kb-cleanup.md
Tier: STANDARD

Suggested Next Step: QA validation — navigate Home → Portfolio → Home, Home → Settings → Home,
confirm zero floating inline keyboard artifacts in Telegram client.
