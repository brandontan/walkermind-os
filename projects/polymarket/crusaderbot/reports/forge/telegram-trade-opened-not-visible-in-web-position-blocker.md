# WARP•R00T — telegram-trade-opened-not-visible-in-web-position-blocker (#1820)

Branch: `WARP/telegram-trade-opened-not-visible-in-web-position-blocker`
Issue: #1820
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Role: WARP•R00T (root-cause + entry-side mode-isolation guard)
Date: 2026-06-13 15:17 Asia/Jakarta

Validation Target: a Telegram `TRADE OPENED` notification must correspond to a WebTrader-visible position; a paper/min-order-fallback trade must not surface as an active trade in a LIVE user's context.

Not in Scope: no strategy rewrite, no native USDC/USDT enablement, no Bridge/pUSD, no withdrawal lifecycle change, no live-guard flip, no real fund movement / live order in tests, no threshold tuning, no market-family expansion.

---

## 1. Root-cause statement

The owner is in `trading_mode='live'` with a tiny balance (`$1.10`). A `late_entry_v3` candidate is sized by the risk gate (Kelly × live balance) to ~`$0.03`. The chain that produces the contradiction:

1. Router `chosen_mode='live'` → `domain/execution/live.py:execute`.
2. `live.execute` computes `shares = size_usdc / limit_price = 0.03 / 0.18 ≈ 0.167`, which is below `LIVE_MIN_ORDER_SHARES = 5`, so it raises `LivePreSubmitError("below CLOB minimum")` **pre-submit** (`live.py:243-248`). This is correct — a sub-minimum order would be broker-rejected.
3. The router catches `LivePreSubmitError` and falls back to paper (`domain/execution/router.py`, the `live_blocked_fallback_paper` design path).
4. `domain/execution/paper.py:execute` inserts a `mode='paper'` position and fires `_notifier.notify_entry(mode="paper", …)` → the Telegram `📋  TRADE OPENED` card + a persisted web alert.
5. The WebTrader portfolio + positions endpoints resolve the user's `trading_mode='live'` and filter `WHERE mode = 'live'` (`webtrader/backend/router.py`). The `mode='paper'` position is excluded → **no open position in the LIVE portfolio**.
6. Net effect: Telegram says a trade opened; WebTrader (live) shows nothing. The `$0.03` size is a real notional (USDC), not a formatting artifact — it is genuinely below the live min-order, which is exactly why it fell back to paper.

This is the **entry-side counterpart of the #1810 exit-side contamination**: a paper lifecycle event surfacing as active trading for a user whose authoritative mode is LIVE. The `position.opened` event (which drives the WebTrader SSE + `notification_service`) carried the same `mode='paper'`, so it would also push an "opened position" the live portfolio can never show.

Code-truth confirmation that the OTHER suspected causes are NOT in play:
- Notification is fired AFTER the DB transaction commits in both engines (`paper.py:40-76` commit, then `notify_entry` at the end) — no pre-commit/orphan emit.
- The notifier header is `"🔴  LIVE TRADE OPENED" if mode == "live" else "📋  TRADE OPENED"` (`services/trade_notifications/notifier.py`) — a paper trade cannot render the LIVE header; this is not a label-styling bug.
- Mode is hardcoded per engine (`paper.execute` → `mode="paper"`, `live.execute` → `mode="live"`); there is no cross-emit path.

## 2. The fix (minimal, symmetric with #1810)

Apply the #1810 mode-isolation guard to the ENTRY path, reusing the exact same single-source-of-truth helpers (`domain/activation/live_mode.get_active_trading_mode` + `paper_event_contaminates_live`).

### `domain/execution/paper.py`
After the position is committed + audited, before `notify_entry`: resolve the user's committed authoritative mode. If `paper_event_contaminates_live(event_mode="paper", active_mode=…)` is True (i.e. the user is now LIVE), suppress the `notify_entry` call, write a diagnostic audit `paper_entry_suppressed_post_live`, and return `open_event_suppressed=True`. Otherwise notify as before. The mode read fails OPEN — a transient DB error never silences a legitimate paper user's TRADE OPENED.

### `services/trade_engine/engine.py`
The `position.opened` event emit (which drives the WebTrader SSE bridge + `notification_service`) is now gated on `not raw.get("open_event_suppressed")`. So when the paper engine suppressed the entry, the engine also skips the open event — Telegram, SSE, and the portfolio query all tell the same story.

The paper position row itself is unchanged — still `mode='paper','open'`, still ledger-debited inside the transaction. It is valid paper accounting and shows in paper mode; it simply no longer masquerades as an active trade in the user's LIVE context.

## 3. Why suppress (not relabel / not block execution)

- **Issue done-criteria**: "Dust/min-order-failed events cannot be represented as opened trades" and "Paper/internal/mocked events cannot leak as live active Telegram trades." Suppression satisfies both directly.
- **Not blocking the paper fallback**: the router's `live_blocked_fallback_paper` is a tested, deliberate execution design. Changing it (e.g. refusing to create a paper position on a below-min live order) is an execution-path change out of scope for a notification-truth fix and explicitly disallowed by the issue's "do not weaken preflight/min-order/risk" constraint.
- **Symmetry with #1810**: the issue requires preserving #1810 mode-isolation guarantees; using the same predicate + audit-action naming convention keeps the paper↔live isolation coherent across entry and exit.

## 4. Files created / modified

- `projects/polymarket/crusaderbot/domain/execution/paper.py` (entry mode-isolation guard + `open_event_suppressed` flag)
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py` (gate `position.opened` emit on the flag)
- `projects/polymarket/crusaderbot/tests/test_telegram_web_position_truth.py` (new — 6 behaviour/safety tests)
- `projects/polymarket/crusaderbot/reports/forge/telegram-trade-opened-not-visible-in-web-position-blocker.md` (this report)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md` (repo-truth sync)

No live engine / risk gate / strategy / migration / config touched. No live-guard flip. No min-order / Kelly / preflight weakened.

## 5. Validation evidence

- New `tests/test_telegram_web_position_truth.py` — 6 passed:
  - paper entry for a now-LIVE user → `notify_entry` NOT called, `open_event_suppressed=True`, `paper_entry_suppressed_post_live` audited, paper position still written;
  - control: paper user → `notify_entry` fires, no suppression;
  - fail-open: a raising mode read still emits the entry notification;
  - engine source-pin: `position.opened` emit gated on `not _open_event_suppressed`;
  - guard reuses the #1810 helpers + `event_mode="paper"` + auditable suppression + fail-open;
  - the paper position write (`INSERT INTO positions … 'paper','open'` + ledger debit) is unchanged by the guard.
- Full suite: `pytest projects/polymarket/crusaderbot/tests/` → 3699 passed, 15 skipped.
- `ruff check` + `python3 -m py_compile` clean on the touched Python. Secret / mojibake / BOM scans clean.
- Branch verified exactly `WARP/telegram-trade-opened-not-visible-in-web-position-blocker`.

## 6. Safety invariant statement

No real live order placed; no real fund movement. No live-guard flip (`USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` / `RISK_CONTROLS_VALIDATED` / `SECURITY_HARDENING_VALIDATED` untouched). `LIVE_MIN_ORDER_SHARES=5`, Kelly 0.25, slippage 5%, risk gate, and the per-user balance / $5 gate are all unchanged — the live order was correctly rejected; this lane only stops the paper fallback from misreporting it. No strategy / preset / migration changed. No historical order / position row mutated, no failed order hidden (the paper position persists and is auditable; the suppression is itself an audit row). #1810 exit-side mode isolation preserved (the new guard is its symmetric entry-side counterpart, same helpers). No PII in any new code / test / report.

## 7. What is next

WARP🔹CMD first-pass; merge under WARP•R00T final-gate on CI green. A deeper product question — whether a genuinely-live user's below-min-order candidate should fall back to paper at all, or be dropped with an explicit "order too small for live" Telegram note — is a follow-up the owner can scope; this lane keeps the existing execution behavior and only fixes the runtime-truth mismatch.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: entry-side Telegram/WebTrader/position runtime-truth consistency.
Not in Scope: execution-path / risk / strategy / live-guard changes; real fund movement.
Suggested Next Step: WARP🔹CMD first-pass → R00T final-gate merge on CI green.
