# WARP•FORGE REPORT — onboarding-polish

**Validation Tier:** STANDARD
**Claim Level:** PRESENTATION
**Validation Target:** /start flow UX + /help categorized command reference
**Not in Scope:** Trading logic, DB schema changes, changing existing command behavior
**Suggested Next Step:** WARP🔹CMD review → merge

---

## 1. What was built

Redesigned the first-time onboarding `/start` flow for CrusaderBot to a clean 2-step sequence
(Welcome → Mode Select) replacing the previous 5-step flow (Welcome → FAQ → Wallet → Style → Deposit).

Redesigned `/help` with organized categories (TRADING / PORTFOLIO / SETTINGS / ADMIN), with ADMIN
section gated to operator-only visibility.

Added 5 user-friendly command aliases: `/scan`, `/pnl`, `/close`, `/trades`, `/mode`.

---

## 2. Current system architecture

### /start flow (new)

```
/start
  ├── Returning user (onboarding_complete=True)
  │     ├── ALLOWLISTED+ → dashboard
  │     └── BROWSE → welcome back message
  └── New user
        └── ONBOARD_WELCOME
              [🚀 Get Started] → onboard:get_started
              └── ONBOARD_MODE
                    [📄 Start Paper Trading] → onboard:mode_paper
                    │     → set_onboarding_complete(), paper confirmation + [📊 View Dashboard]
                    │     → END
                    └── [💰 Setup Live Trading] → onboard:mode_live
                          → live redirect (/enable_live) → END

[📊 View Dashboard] = standalone CallbackQueryHandler (onboard:view_dashboard) → dashboard
```

### /help (new)

```
TRADING   : /scan, /positions, /close, /pnl
PORTFOLIO : /chart, /insights, /trades
SETTINGS  : /mode, /referral, /status
ADMIN     : /admin, /ops_dashboard, /killswitch, /jobs, /auditlog (operator only)
```

---

## 3. Files created / modified

**Modified:**
- `projects/polymarket/crusaderbot/bot/keyboards/onboarding.py` — replaced 5 old keyboards with 3 new: `get_started_kb`, `mode_select_kb`, `paper_complete_kb`
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — new 2-step ConversationHandler; new `help_handler` with categories; new `view_dashboard_cb` standalone handler
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — added 5 command aliases; added `onboard:view_dashboard` CallbackQueryHandler
- `projects/polymarket/crusaderbot/tests/test_phase5h_onboarding.py` — full rewrite for new flow; 15 hermetic tests

**Created:**
- `projects/polymarket/crusaderbot/reports/forge/onboarding-polish.md` — this report

---

## 4. What is working

- New welcome screen with feature bullets and `[🚀 Get Started]` button
- Mode selection: Paper vs Live
- Paper activation: marks `onboarding_complete`, shows $10,000 virtual confirmation + `[📊 View Dashboard]`
- Live redirect: shows `/enable_live` instruction
- `[📊 View Dashboard]` callback routes to existing dashboard handler
- `/help` organized into 4 categories; ADMIN hidden from non-operators
- Command aliases: `/scan` → signals, `/pnl` → dashboard, `/close` → positions, `/trades` → my_trades, `/mode` → settings
- Returning user routing unchanged
- Referral deep-link logic preserved
- 15 hermetic tests: 15 passed, 0 failed

---

## 5. Known issues

- `qrcode` dep in `pyproject.toml` is now unused (was for old wallet QR in onboarding); can be cleaned up in a separate lane if wallet QR is also unused elsewhere. Non-blocking.

---

## 6. What is next

WARP🔹CMD review → merge decision (no SENTINEL required — Tier: STANDARD)
