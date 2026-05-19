# WARP•FORGE Report — dashboard-corruption-fix

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: bot/handlers/dashboard.py, domain/strategy/strategies/copy_trade.py, domain/strategy/types.py, bot/messages.py
Not in Scope: runtime behaviour changes, new features, DB migrations
Suggested Next Step: WARP🔹CMD review + merge → redeploy on Fly.io

---

## 1. What was built

Emergency repair of 3 Base64-corrupted source files and 1 HUD calibration fix.

Corrupting commits (`31c97ab`, `b37f7bc`, `f8e9116`) replaced 951 lines of valid Python with Base64 blobs.
The Base64 content was undecodable due to encoding corruption — files restored from pre-corruption git state.
`messages.py` DIV width updated from 26 to 32 for full-width Telegram column support.

---

## 2. Current system architecture

No architectural change. Pipeline unchanged: DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING.

dashboard.py is the Telegram handler entry point for /start and menu:dashboard callbacks.
copy_trade.py is the STRATEGY layer CopyTradeStrategy scanner (no order placement, no risk bypass).
types.py holds frozen dataclasses consumed by all strategy implementations.
messages.py holds all Telegram HTML template builders using parse_mode=HTML + <pre> blocks.

---

## 3. Files created / modified

Modified (restored from pre-corruption git state):
- projects/polymarket/crusaderbot/bot/handlers/dashboard.py (was 1-line Base64 blob, restored to 351 lines)
- projects/polymarket/crusaderbot/domain/strategy/strategies/copy_trade.py (was 1-line Base64 blob, restored to 462 lines)
- projects/polymarket/crusaderbot/domain/strategy/types.py (was 1-line Base64 blob, restored to 138 lines)

Modified (calibration fix):
- projects/polymarket/crusaderbot/bot/messages.py:40 — DIV = "━" * 26 → "━" * 32

No files created. No migrations.

---

## 4. What is working

- python3 -m compileall exits 0 — zero compilation errors across entire project
- dashboard.py: correct auto_trade_on references via user.get("auto_trade_on", False) — no KeyError risk
- copy_trade.py: queries copy_trade_tasks table, uses wallet_address column — schema-aligned
- types.py: SignalCandidate + ExitDecision + MarketFilters + UserContext dataclasses intact
- messages.py: DIV = "━" * 32, all financial blocks wrapped in <pre> tags with parse_mode=HTML

---

## 5. Known issues

- Branch `claude/fix-dashboard-sync-hoy6O` violates CLAUDE.md WARP/{feature} naming rule.
  The session config declared this branch — WARP🔹CMD must decide whether to merge as-is or
  cherry-pick to a proper WARP/ branch.
- Restored files are from pre-corruption state (before the v5 "sync" commits).
  If those sync commits intended to introduce new content, a separate lane is required.

---

## 6. What is next

- WARP🔹CMD review required — merge unblocks bot deployment
- After merge: Fly.io redeploy to restore /start and Dashboard to working state
- Verify in Telegram: /start returns wide Dashboard without crash
