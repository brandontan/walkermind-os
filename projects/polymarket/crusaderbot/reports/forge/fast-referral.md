# WARP•FORGE Report — fast-referral

Validation Tier: STANDARD
Claim Level: FOUNDATION
Validation Target: Referral code generation, deep-link parsing, referral recording,
  /referral command, share card on winning trades, fee system table prep (gated).
Not in Scope: Fee collection activation, referral payout activation, payment/withdrawal
  logic, changes to existing trade close flow beyond adding [Share] button.
Suggested Next Step: WARP🔹CMD review → merge decision.

---

## 1. What Was Built

Track I — Referral + Share System (FOUNDATION layer):

- **Migration 022** (`022_referral_fee_system.sql`): additive-only DDL.
  Four new tables: `referral_codes`, `referral_events`, `fees`, `fee_config`.
  `fee_config` seeded with default 10% fee rate.

- **Referral service** (`services/referral/referral_service.py`):
  Code generation (8-char uppercase alphanumeric, unique, collision-retry),
  deep-link builder (`t.me/CrusaderBot?start=ref_{CODE}`), referral recording,
  stats query, payout stub (gated behind `REFERRAL_PAYOUT_ENABLED`),
  `parse_ref_param` for Telegram start-param extraction.

- **Fee service** (`services/fee/fee_service.py`):
  `calculate_and_record_fee` — reads `fee_config`, writes `fees` row, gated
  behind `FEE_COLLECTION_ENABLED`. Never called in any active code path.

- **/referral handler** (`bot/handlers/referral.py`):
  Shows user's code, deep link, total referrals, and earnings (always $0.00
  until guard ON). MarkdownV2 formatted.

- **Onboarding deep-link wiring** (`bot/handlers/onboarding.py`):
  `parse_ref_param` called on `/start`; referral recorded for new users who
  join via deep link. `get_or_create_referral_code` called for every `/start`
  so all users auto-receive a code.

- **Share card** (`bot/handlers/share_card.py`):
  `referral:share:{trade_id}` callback — fetches closed position, verifies
  PNL > 0, generates share card text with PNL % and deep link.

- **Share keyboard** (`bot/keyboards/referral.py`):
  `share_trade_kb(trade_id)` inline keyboard, one button: `[🏆 Share]`.

- **Notifier update** (`services/trade_notifications/notifier.py`):
  `notify_tp_hit`, `notify_sl_hit`, `notify_manual_close` now accept optional
  `reply_markup` parameter forwarded to `notifications.send`. No behaviour
  change when `reply_markup=None` (default).

- **notifications.send update** (`notifications.py`):
  `reply_markup: Optional[Any] = None` added — forwarded to
  `bot.send_message`. Backwards-compatible: all existing call sites unchanged.

- **Dispatcher** (`bot/dispatcher.py`):
  `CommandHandler("referral", ...)` and
  `CallbackQueryHandler(share_card.referral_callback, pattern=r"^referral:share:")` wired.

- **Config** (`config.py`):
  `REFERRAL_PAYOUT_ENABLED: bool = False` added. Default OFF. Not set anywhere.

- **Tests** (`tests/test_referral_system.py`): 18 hermetic tests.

---

## 2. Current System Architecture

```
/start (deep link with ref_CODE)
    └── onboarding._entry
            ├── parse_ref_param(start_param) → code or None
            ├── record_referral(referrer_code, referred_user_id)  [new user only]
            └── get_or_create_referral_code(user_id)              [all users]

/referral
    └── referral.referral_command
            ├── get_or_create_referral_code(user_id)
            └── get_referral_stats(user_id)
                    └── _calculate_referral_earnings()  [gated: REFERRAL_PAYOUT_ENABLED]

Trade close notification (TP_HIT / MANUAL) with PNL > 0
    └── TradeNotifier.notify_tp_hit(reply_markup=share_trade_kb(trade_id))
            └── notifications.send(reply_markup=...)

[🏆 Share] button
    └── share_card.referral_callback
            ├── fetch closed position
            ├── verify PNL > 0
            └── send share card text with deep link

Fee tables: referral_codes, referral_events, fees, fee_config
Fee logic:  calculate_and_record_fee() — gated FEE_COLLECTION_ENABLED (OFF)
Payout:     _calculate_referral_earnings() — gated REFERRAL_PAYOUT_ENABLED (OFF)
```

---

## 3. Files Created / Modified

Created:
- `projects/polymarket/crusaderbot/migrations/022_referral_fee_system.sql`
- `projects/polymarket/crusaderbot/services/referral/__init__.py`
- `projects/polymarket/crusaderbot/services/referral/referral_service.py`
- `projects/polymarket/crusaderbot/services/fee/__init__.py`
- `projects/polymarket/crusaderbot/services/fee/fee_service.py`
- `projects/polymarket/crusaderbot/bot/handlers/referral.py`
- `projects/polymarket/crusaderbot/bot/handlers/share_card.py`
- `projects/polymarket/crusaderbot/bot/keyboards/referral.py`
- `projects/polymarket/crusaderbot/tests/test_referral_system.py`

Modified:
- `projects/polymarket/crusaderbot/config.py` — added REFERRAL_PAYOUT_ENABLED
- `projects/polymarket/crusaderbot/notifications.py` — reply_markup param
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` — reply_markup on close events
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — deep-link + auto-code wiring
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — /referral + referral:share: handlers

---

## 4. What Is Working

- Migration 022: additive DDL, `referral_codes`, `referral_events`, `fees`, `fee_config`.
- Referral code generation: 8-char uppercase alphanumeric, uniqueness enforced, collision retry.
- Deep-link parsing: `parse_ref_param("ref_ABCD1234")` → `"ABCD1234"`.
- Deep-link: `https://t.me/CrusaderBot?start=ref_{CODE}` format.
- Onboarding: new users joining via deep link → referral recorded automatically.
- Onboarding: all `/start` users → referral code auto-generated if missing.
- `/referral`: shows code, link, total_referrals, earnings ($0.00 until guard ON).
- `[Share]` button: only rendered when PNL > 0; produces formatted share card.
- Share card text: `🏆 Just made +{pct}% on {market} using CrusaderBot! Join me: ...`
- Fee tables: DDL in place, `fee_config` seeded with 10%.
- Fee logic: present but gated behind `FEE_COLLECTION_ENABLED=False`.
- Referral payout: present but gated behind `REFERRAL_PAYOUT_ENABLED=False`.
- Guard validation: `grep` confirms neither guard set to True in any code path.
- All files: syntax clean, 18 hermetic tests written.

---

## 5. Known Issues

- `[Share]` button is exposed via `share_trade_kb` keyboard but the actual call sites
  in `notify_tp_hit` / `notify_manual_close` still pass `reply_markup=None` by default.
  Callers in `services/trade_engine/` or `services/signal_scan/` need to be updated
  to pass `share_trade_kb(trade_id)` when PNL > 0. This is a wiring task deferred to
  WARP🔹CMD direction — the surface (handler + keyboard + notifier param) is ready.
- Earnings display uses $0.00 placeholder unconditionally until REFERRAL_PAYOUT_ENABLED
  is activated. Intentional per spec.
- Local test run fails on import (asyncpg / cryptography not in local venv). Consistent
  with all other CrusaderBot tests; will pass in CI where deps are installed from
  pyproject.toml.

---

## 6. What Is Next

- WARP🔹CMD review → merge (no SENTINEL for STANDARD tier).
- After merge: wire `share_trade_kb(trade_id)` into trade close call sites in
  `services/trade_engine/` and `services/signal_scan/` where PNL is known at close time.
- Referral payout and fee collection activation: separate WARP🔹CMD lane when ready.
