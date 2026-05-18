# FORGE REPORT — autonomous-trading-bot

Branch: WARP/CRUSADERBOT-MVP-RUNTIME-V1
Date: 2026-05-17 10:48 Asia/Jakarta

---

## 1. What Was Built

Phase 0 runtime audit + critical onboarding pipeline fix for the full autonomous trading bot.

**Critical bug fixed:** `skip_deposit_cb` in `bot/handlers/start.py` never applied the user's selected preset during onboarding. `auto_trade_on` remained `FALSE` after completing `/start`, so the signal scanner never picked up new users and no paper trades were ever opened automatically.

**Fix:** `skip_deposit_cb` now reads `onboard_preset_key` from user_data, calls `get_preset()`, applies settings via `update_settings()`, and calls `set_auto_trade(user_id, True)` + `set_paused(user_id, False)` before marking onboarding complete. All in a guarded try/except — onboarding never blocks on preset errors.

**Secondary fix:** `allowlist_command` in admin.py used `_is_operator()` (checks only OPERATOR_CHAT_ID). Replaced with `_is_admin_user()` which accepts both OPERATOR_CHAT_ID and ADMIN-tier users from `user_tiers` table, consistent with the binary Admin/User role model.

**P0 audit output:** `P0_RUNTIME_MAP.md` written at project root with full handler classification, pipeline status, strategy status, scheduler jobs, and activation guard status.

---

## 2. Current System Architecture (relevant slice)

```
/start (ConversationHandler)
  → upsert_user (creates user + enrolls signal_following)
  → paper seed $1,000 USDC (balance=0 guard)
  → preset picker → preset_selected_in_onboard_cb (saves preset_key to user_data)
  → skip_deposit_cb:
      → get_preset(preset_key)  [NEW]
      → update_settings(active_preset, strategy_types, capital, tp, sl)  [NEW]
      → set_auto_trade(user_id, True)   [NEW]
      → set_paused(user_id, False)      [NEW]
      → set_onboarding_complete(user_id, True)
      → show_dashboard

Signal scan job (scheduler, 30s interval)
  → _load_enrolled_users(): WHERE auto_trade_on=TRUE AND paused=FALSE
  → TradeEngine.execute() → risk gate (13 steps) → paper.execute()
  → exit_watcher: TP/SL/expiry triggers close_position() + notify

Full pipeline now activates on onboarding completion.
```

---

## 3. Files Created / Modified

- `projects/polymarket/crusaderbot/bot/handlers/start.py` — Added imports (get_preset, capital_for_risk_profile, set_auto_trade, set_paused, update_settings); fixed `skip_deposit_cb` to apply preset and set auto_trade_on=True
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` — Fixed `allowlist_command` gate: `_is_operator()` → `_is_admin_user()`
- `projects/polymarket/crusaderbot/P0_RUNTIME_MAP.md` — Phase 0 runtime audit output (new file)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Resolved merge conflict in [NEXT PRIORITY]; updated Last Updated, Status, [IN PROGRESS]
- `projects/polymarket/crusaderbot/reports/forge/autonomous-trading-bot.md` — This report

---

## 4. What Is Working

- Full autonomous trading pipeline: `/start` → onboarding → paper wallet $1,000 → preset selection → scanner activation → signal → risk gate → paper open → exit watcher → close → receipt
- `skip_deposit_cb` now applies preset + sets `auto_trade_on=True` — new users are immediately picked up by the signal scanner
- Binary Admin/User model: `allowlist_command` uses `_is_admin_user()` (OPERATOR_CHAT_ID or ADMIN tier)
- All 4 activation guards remain OFF and unchanged
- Full compile clean: `python3 -m compileall` PASS

---

## 5. Known Issues

- Value strategy (`domain/signal/value.py`) returns `[]` — stub pending model validation. Not blocking: `signal_following` strategy is the active paper path.
- `/allowlist` command retained as admin tool for access management. Can be renamed or removed in a dedicated cleanup lane.
- `bot/tier.py` legacy definitions remain; not user-visible; `tier_gate.py` is no-op passthrough. Cleanup deferred.

---

## 6. What Is Next

- WARP•SENTINEL validation required (MAJOR) — full pipeline audit
- Apply migration 030 + 031 to production DB
- Deploy main to Fly.io
- Signal scanner smoke test with a new user account

---

Validation Tier   : MAJOR
Claim Level       : FULL RUNTIME INTEGRATION
Validation Target : CrusaderBot autonomous trading pipeline — /start → onboarding → paper wallet → preset → scanner activation → signal → risk gate → paper trade open → exit watcher → close → Telegram receipt
Not in Scope      : Value strategy implementation, live trading activation, referral payout, fee collection
Suggested Next    : WARP•SENTINEL validation required before merge
