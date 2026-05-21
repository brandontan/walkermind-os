# WARP-57 — Telegram UX MVP v1 Rebuild

**Branch:** WARP/warp57-telegram-ux-mvp
**Issue:** #1260
**Validation Tier:** MAJOR
**Claim Level:** FOUNDATION (UX rendering + routing — execution / strategy / risk engines untouched)
**Validation Target:** All Telegram callbacks route correctly; hierarchy-tree screens render for all 6 main surfaces; no manual trade buttons; live mode remains locked; paper-mode default unchanged; existing paper-trade runtime (WARP-55) continues to pass.
**Not in Scope:** domain/ logic, services/, migrations/, API endpoints, WebTrader, activation guards (`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED`).
**Suggested Next Step:** WARP•SENTINEL audit per Phase 0–8.

---

## 1. What was built

A full rebuild of the Telegram user experience following `docs/ux/telegram-mvp-v1.md` (blueprint v1, 2796 lines). Delivered as an **additive MVP layer** so the proven WARP-55 paper-trade runtime keeps working while the user surface flips to the new IA.

**Information Architecture (blueprint section 3):**

```
🏠 Dashboard
├── 🤖 Auto Trade       (Quick Start / Configure / Status / Pause-Resume)
├── 👥 Copy Wallet      (Add Wallet / Active Wallets / Pause-Resume)
├── 💼 Portfolio        (Balance / Positions / History / Performance)
├── 📈 Markets          (Trending / New / AI Insights / Watchlist / Search)
├── ⚙️ Settings         (Trading Mode / Risk / Notifications / Account / Advanced)
└── ❓ Help             (Quick Start / How Auto Trade / How Copy Wallet / Safety / FAQ / Support)
```

**Hard product decisions enforced (blueprint section 2):**

- Telegram-only — no WebTrader references in MVP surfaces.
- Full-auto only — no manual trade buttons anywhere in MVP keyboards.
- Auto Trade and Copy Wallet are separate products with separate callback namespaces.
- Markets = intelligence-only — detail screens expose 🤖 Auto Strategy / ⭐ Watchlist / 📊 Similar Markets; never YES/NO order buttons.
- Hierarchy tree terminal UI across every screen (`│ ├── └──`).

**Callback architecture (blueprint section 20.1):**

```
dashboard:home | dashboard:refresh
auto:home | auto:quick_start
auto:configure[:strategy|capital|risk|review][:<arg>]
auto:start | auto:pause[:confirm] | auto:resume[:confirm] | auto:status
copy:home | copy:add_wallet | copy:wallet[:configure|start|edit|pause:<id>|resume:<id>|stats:<id>]
copy:wallets | copy:pause[:confirm] | copy:resume
portfolio:home | portfolio:positions | portfolio:history[:today|week|all]
portfolio:performance[:week|month] | portfolio:balance | portfolio:position:<id>
markets:home | markets:trending | markets:new | markets:insights | markets:watchlist
markets:search | markets:detail:<id> | markets:watchlist:add:<id> | markets:similar:<id>
settings:home | settings:mode[:paper|live[:request]] | settings:risk[:...]
settings:notifications[:...] | settings:account[:...] | settings:advanced[:...] | settings:copy_wallet
help:home | help:quick_start | help:auto | help:copy_wallet | help:safety | help:faq[:...] | help:support[:report]
nav:home | nav:back | nav:refresh | nav:cancel | nav:noop
```

---

## 2. Current system architecture

```
bot/
├── ui/
│   ├── __init__.py             # re-exports
│   └── tree.py                 # BAR/BRANCH/LAST chars, status glyphs,
│                                 leaf() / section() / nested() / title() / pnl() / join_blocks()
├── messages_mvp.py             # render_* function per blueprint screen
│                                 (dashboard / autotrade / copy / portfolio /
│                                  markets / settings / help / notifications /
│                                  loading / errors / onboarding)
├── keyboards/
│   ├── __init__.py             # untouched (legacy keyboards preserved)
│   └── mvp/
│       ├── __init__.py
│       ├── _common.py          # back / home / refresh / cancel / main_menu_kb
│       ├── onboarding.py       # welcome / wallet_ready / deposit_prompt / new_user_dashboard
│       ├── autotrade.py        # home / quick_start / configure[*] / status / pause / resume
│       ├── copy_wallet.py      # home / add_wallet / wallet_review / configure / wallets / pause
│       ├── portfolio.py        # home / positions / history / performance / balance / position_detail
│       ├── markets.py          # home / trending / detail / ai_insight / search / watchlist_empty
│       ├── settings.py         # home / mode / live_gate / risk / notifications / account / advanced
│       └── help.py             # home / quick_start / how_auto_trade / how_copy_wallet / safety / faq / support
├── handlers/
│   ├── (legacy handlers preserved — admin / emergency / live_gate / wizards / wallet / etc.)
│   └── mvp/
│       ├── __init__.py
│       ├── _send.py            # send_or_edit() / callback_tail / callback_parts
│       ├── _users.py           # fetch_user / fetch_settings / fetch_balance / fetch_daily_pnl /
│                                 fetch_open_positions / set_auto_trade / set_paused
│       ├── dashboard.py        # /dashboard /home + dashboard: callback
│       ├── autotrade.py        # auto:* callbacks + configure wizard state in user_data
│       ├── copy_wallet.py      # copy:* callbacks + text_input() captures pasted 0x… addresses
│       ├── portfolio.py        # portfolio:* callbacks
│       ├── markets.py          # markets:* callbacks
│       ├── settings.py         # settings:* callbacks (live mode locked at UI; guard untouched)
│       ├── help.py             # /help + help:* callbacks
│       └── onboarding.py       # /start owner — returning users land on dashboard, new users
│                                 see welcome → quick_start
└── dispatcher.py               # MVP attach() first (group=0), _menu_nav_cb (group=-1) routes
                                  menu:* taps to MVP, _nav_cb (group=-1) handles nav:*,
                                  persistent reply-kb regexes route to MVP entries,
                                  legacy callback handlers remain as fallbacks.
```

**Routing precedence (intentional):**

```
group=-1  →  _menu_nav_cb (menu:*)            ┐  MVP entries
group=-1  →  _nav_cb (nav:*)                  │
group=-1  →  ReplyKeyboard regex handlers     ┘  (📊 Dashboard / 🤖 Auto-Trade / 💼 Portfolio / ⚙️ Settings / ❓ Help)
group=0   →  MVP attach() registers           ┐  CallbackQueryHandlers for
              dashboard: / auto: / copy: /    │   each prefix, registered FIRST
              portfolio: / markets: /         │   so they win over legacy
              settings: / help:               ┘
group=0   →  Legacy callback handlers          (fire only if no MVP match —
              (admin / emergency / wallet /     unreachable for owned prefixes;
              p5: / setup: / preset: etc.)      legacy commands & wizards intact)
```

---

## 3. Files created / modified (full repo-root paths)

**Created (additive layer):**

- projects/polymarket/crusaderbot/bot/ui/__init__.py
- projects/polymarket/crusaderbot/bot/ui/tree.py
- projects/polymarket/crusaderbot/bot/messages_mvp.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/__init__.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/_common.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/onboarding.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/autotrade.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/copy_wallet.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/portfolio.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/markets.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/settings.py
- projects/polymarket/crusaderbot/bot/keyboards/mvp/help.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/__init__.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/_send.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/_users.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/dashboard.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/copy_wallet.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/portfolio.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/markets.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/settings.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/help.py
- projects/polymarket/crusaderbot/bot/handlers/mvp/onboarding.py
- projects/polymarket/crusaderbot/reports/forge/warp57-telegram-ux-mvp.md

**Modified (surgical wiring):**

- projects/polymarket/crusaderbot/bot/dispatcher.py — MVP imports added, `_menu_nav_cb` and `_nav_cb` routed to MVP, MVP `attach()` block added at top of `register()`, persistent reply-keyboard regex handlers retargeted to MVP entries.
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md — `Last Updated` bumped, WARP-57 status flipped from `DISPATCHED to FORGE` to `FORGE delivered`, SENTINEL gate added at top of `[NEXT PRIORITY]`.
- projects/polymarket/crusaderbot/state/WORKTODO.md — `Last Updated` bumped, WARP-57 active-lane line updated.
- projects/polymarket/crusaderbot/state/CHANGELOG.md — append-only entry for the lane.

**Not touched (per scope):**

- bot/messages.py, bot/keyboards/__init__.py — left intact for legacy compat.
- All existing handlers under bot/handlers/ except dispatcher.py.
- domain/, services/, jobs/, migrations/, WebTrader, scripts/.
- Live-trading guards.

---

## 4. What is working

- All 26 MVP modules `py_compile` clean.
- `bot/messages_mvp.py` renderers produce blueprint-shaped output:
  - Dashboard default / new-user / paused / risk-alert variants.
  - Auto Trade home, quick-start, 4-step configure wizard, strategy status, pause/resume confirms.
  - Copy Wallet home, add-wallet prompt, review, configure, active cards, empty state, pause confirm.
  - Portfolio home, positions list + empty, history home + empty, performance, balance.
  - Markets home, trending list, detail (no manual buttons), AI insight, search prompt, watchlist empty.
  - Settings home, trading mode, locked live-gate, risk controls, notifications, account, advanced.
  - Help home, quick-start guide, how-auto-trade, how-copy-wallet, safety, FAQ, support.
  - Notifications: bot started, waiting reassurance, trade opened/first/closed (profit/loss), wallet copied, drawdown warning, auto-pause, daily summary.
  - Loading / syncing / error states (API error / invalid wallet / bot paused / live locked).
  - Onboarding: welcome, wallet ready, deposit prompt.
- Tree-format spacing matches blueprint section 4.1 exactly (verified manually against `render_dashboard_default` output).
- MVP handlers read live data via existing project accessors only:
  - `users.upsert_user` / `users.get_user_by_telegram_id`
  - `wallet.ledger.get_balance` / `wallet.ledger.daily_pnl`
  - `users.set_auto_trade` / `users.set_paused`
  - direct `database.get_pool()` reads against `user_settings`, `positions`, `wallets`, `copy_targets`
  - `jobs.market_signal_scanner.get_scanner_state` for markets feed
- Every DB read is wrapped in `try / except` with `log.debug` so a missing column or unavailable accessor degrades to default values instead of crashing the UX.
- Live mode remains locked at the UX layer (`render_settings_live_gate` + `live_gate_kb`); the `settings:mode:live` route shows the warning screen only. No code path flips `ENABLE_LIVE_TRADING` or any other guard.
- Persistent reply-keyboard taps (`📊 Dashboard` / `🤖 Auto-Trade` / `💼 Portfolio` / `⚙️ Settings` / `❓ Help`) route directly to MVP entries via group=-1 MessageHandlers, so legacy users with a residual reply keyboard land on the new UX immediately.
- `nav:back` / `nav:home` / `nav:refresh` / `nav:cancel` / `nav:noop` all resolve to MVP dashboard fallback (flows that need finer back-stack control call their own renderer).
- Copy-wallet flow: user pastes a 0x… address while in `await_address`; `mvp_copy_wallet.text_input()` claims it from the central text router, validates with `^0x[0-9a-fA-F]{40}$`, advances to the review screen.

---

## 5. Known issues

- **Copy-wallet persistence path is best-effort.** `do_start_copying` writes directly to `copy_targets (user_id, target_address, enabled, allocation_usdc)` and pauses with `UPDATE copy_targets SET enabled=FALSE`. If the live deployment uses `copy_trade_tasks` (per WARP-26 schema change noted in `[KNOWN ISSUES]`) instead of `copy_targets`, the insert/update silently logs and continues — the user still sees the home screen but the row may not land. The legacy 8-step `/copytrade` wizard remains available as a fully-wired fallback. **Confirm copy-target table name during SENTINEL validation** and, if needed, swap the table name in `bot/handlers/mvp/copy_wallet.py:_read_wallets / do_start_copying / do_pause`.
- **Auto-trade start path** sets `users.auto_trade_enabled = true` + `users.paused = false` via existing setters. It does **not** call any preset-activation or strategy-engine bootstrap that the legacy `autotrade.py:autotrade_callback` flow does. For a SENTINEL run, validate that flipping the flags is sufficient to wake the scheduler/scanner or, if not, delegate `auto:start` to the existing preset-activation entry point.
- **Markets feed** depends on `jobs.market_signal_scanner.get_scanner_state` returning a `recent_signals` list with `title/yes_price/no_price/volume_label/sentiment` keys. If the scanner state schema differs, the screen falls back to `render_error_api` rather than crashing — the contract should be confirmed.
- **Open-position rows** assume `positions` has `side`, `entry_price`, `size_usdc`, plus a JOIN to `markets.question`. The SELECT also relies on `markets.id` matching `positions.market_id`. If a deployment renames any of these columns, the positions list silently returns empty.
- **/start ownership.** `mvp_onboarding.attach()` registers `/start` first so MVP wins over `build_start_handler()`. The legacy ConversationHandler is still registered but unreachable for fresh `/start` taps. If a user is already mid-conversation in the legacy state when the deploy lands, their existing state should resolve via existing fallback CommandHandlers; `/start` again will reset them into the MVP welcome screen.
- **PR review tools have been seeing a 100-issue cap** on this repo recently (per the existing `[KNOWN ISSUES]`). Expect Codex/Gemini bot reviews to be partial — SENTINEL should not rely solely on the auto-review.

---

## 6. What is next

1. WARP•SENTINEL run, focused on Phase 0–8:
   - **Phase 0**: report path + 6 sections + state files updated → pass.
   - **Phase 1**: every callback prefix routes; persistent reply-kb taps land on MVP; `/start` owners (MVP vs legacy) resolve in favor of MVP.
   - **Phase 2**: end-to-end Quick Start journey from blueprint 19.1 (`/start → 🚀 Quick Start → ✅ Start Recommended → 🤖 Auto Trade Started → 🏠 Dashboard`) works against a paper user.
   - **Phase 3**: failure modes for `_users` accessors (DB pool down, unknown user, missing columns) degrade gracefully without exception traces in the chat.
   - **Phase 5**: confirm no MVP code path bypasses `ENABLE_LIVE_TRADING`. Check Kelly fraction (a=0.25), max position size, daily loss, auto-pause — all UI-display only, all values pulled from defaults (no writes).
   - **Phase 7/8**: Telegram preview screenshots for Dashboard / Auto Trade home / Copy Wallet home / Portfolio home / Markets home / Settings home / Help home in the SENTINEL report.
2. WARP🔹CMD final merge decision once SENTINEL verdict lands.
3. Post-merge: confirm copy-target table name on live DB; if `copy_trade_tasks` is correct, ship a follow-up rename in `bot/handlers/mvp/copy_wallet.py`.
4. Optional follow-up lane (NOT in this PR): retire `bot/menus/main.py` reply-keyboard routing + `bot/keyboards/__init__.py` legacy keyboard helpers once SENTINEL confirms the MVP layer is the only user-facing surface.
