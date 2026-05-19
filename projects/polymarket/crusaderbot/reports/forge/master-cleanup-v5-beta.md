# WARP•FORGE Report — master-cleanup-v5-beta

Branch : WARP/master-cleanup-v5-beta
Task   : WARP-26 Master Cleanup & Sync (V5 Beta Readiness)
Date   : 2026-05-19 09:21 (Asia/Jakarta)

---

## 1. What Was Built

Three targeted fixes resolving critical V5 beta readiness blockers:

**Task 1 — Copy Trade Engine Sync (CRITICAL)**
`CopyTradeStrategy._load_active_copy_targets` now queries `copy_trade_tasks`
instead of the legacy `copy_targets` table. Field mapping applied:
`target_wallet_address` → `wallet_address`. Dedup migrated from
`copy_trade_events` (legacy) to `copy_trade_tasks`-aligned
`copy_trade_idempotency (user_id, task_id, leader_trade_id)`.
Sizing logic replaced: `leader_bankroll_estimate` / `scale_size` removed;
`copy_mode` (fixed/proportional) + `copy_amount`/`copy_pct` used instead.
`copy_direction` (buys_only/buys_and_sells) respected in `_normalise_side`.
`min_trade_size` floor enforced per task row.

**Task 2 — Analysis Engine Reasoning Injection**
`SignalCandidate` gains `reasoning: str = ""` field (backward-compatible
default). All three active strategies populate it:
- CopyTrade: "CopyTrade: Mirroring {task_name} ({wallet[:8]}…). Mode=…, Size=$…."
- SignalFollowing: "Signal: {feed_name} candidate — market {id[:8]}… conf=X%." (feed_name fallback = 'feed')
- MomentumReversal: "Momentum: YES oversold — 24h drop X%, price Y, conf=Z%."
Note: `confidence` already existed as a required field on `SignalCandidate`
(added in an earlier phase). Only `reasoning` was missing; no duplicate added.

**Task 3 — Tactical Terminal UX Width**
`DIV = "━" * 32` was already set by WARP-28. All 12 remaining hardcoded
26-char inline dividers across `bot/messages.py` replaced with 32-char.
Full divider standardization complete.

---

## 2. Current System Architecture

```text
copy_trade_tasks (DB) ←── NEW source for CopyTradeStrategy
    │  wallet_address, copy_mode, copy_amount, copy_pct,
    │  copy_direction, min_trade_size, status='active'
    ↓
CopyTradeStrategy.scan()
    ├─ fetch_recent_wallet_trades(wallet_address)
    ├─ _already_mirrored(user_id, task_id, tx_hash)
    │       └─ copy_trade_idempotency (user_id, task_id, leader_trade_id)
    ├─ _normalise_side(trade, copy_direction)
    ├─ sizing: copy_mode='fixed' → copy_amount capped at cap_usdc
    │          copy_mode='proportional' → copy_pct * available_balance
    └─ SignalCandidate(reasoning=…)

SignalCandidate (domain/strategy/types.py)
    + reasoning: str = ""   ← NEW field

All strategies populate reasoning before emitting candidates.
Messages pipeline: all dividers = 32-char ━ (uniform width).
```

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/types.py`
  Added `reasoning: str = ""` to `SignalCandidate` dataclass.

- `projects/polymarket/crusaderbot/domain/strategy/strategies/copy_trade.py`
  `_load_active_copy_targets`: queries `copy_trade_tasks`, correct fields.
  `_already_mirrored`: uses `copy_trade_idempotency`.
  `scan()`: wallet_address, copy_mode/copy_pct sizing, copy_direction, reasoning.
  `_normalise_side`: respects copy_direction param.
  Removed `scale_size` import (no longer needed).

- `projects/polymarket/crusaderbot/domain/strategy/strategies/signal_following.py`
  `scan()`: wraps evaluator results, injects reasoning when absent.

- `projects/polymarket/crusaderbot/domain/strategy/strategies/momentum_reversal.py`
  `_evaluate_market`: reasoning field set at SignalCandidate construction.

- `projects/polymarket/crusaderbot/bot/messages.py`
  All 12 hardcoded 26-char ━ dividers replaced with 32-char (uniform).

---

## 4. What Is Working

- `python3 -m compileall` PASS on all 5 modified files.
- Copy Trade strategy will now pick up tasks created via the 8-step wizard
  and WebTrader CopyTradePage (both write to `copy_trade_tasks`).
- Dedup aligned with monitor service — both use `copy_trade_idempotency`.
- `copy_direction=buys_and_sells` now supported: SELL YES→NO, SELL NO→YES.
- Every `SignalCandidate` emitted by all three strategies carries a
  human-readable `reasoning` string for trade notification display.
- Telegram message width: all dividers unified at 32-char ━.

---

## 5. Known Issues

- `evaluate_publications_for_user` (signal_evaluator.py) does not yet set
  `reasoning` on the candidates it builds — signal_following.py handles
  this by wrapping and injecting post-hoc. Clean fix requires updating the
  evaluator; deferred as out-of-scope for WARP-26.
- `copy_trade_events` table and legacy `copy_targets` table remain in DB
  (historical rows, no FK violation). Cleanup deferred to a dedicated
  schema migration lane.
- Reasoning strings are English-only. i18n is post-MVP scope.

### Post-merge CI fixes (same branch)

- `test_copy_trade.py` — 8 test functions used legacy `target_row` schema
  (`target_wallet_address`, `scale_factor`, `trades_mirrored`); `_already_mirrored`
  calls used 2-arg signature; metadata assertions checked `copy_target_id`.
  All updated to new schema (`wallet_address`, `copy_mode`, `copy_amount`, etc.)
  and 3-arg `_already_mirrored(user_id, task_id, tx_hash)`.
- `test_signal_following.py` — `test_strategy_scan_delegates_to_evaluator`
  built expected candidate without `reasoning`; updated to include the injected
  reasoning string so the equality assertion holds. Subsequent CI pass revealed
  the expected string `"Signal: Heisenberg feed breakout …"` did not match the
  code template (`"{feed_name} candidate"`). Corrected to
  `"Signal: feed candidate — market mkt_1… conf=70%."` (metadata carries no
  `feed_name` key → default `'feed'` fallback applies).
- `copy_trade.py` — `rm_mirror` mode (persisted by Telegram wizard and WebTrader
  router) fell into the fixed-amount else branch, ignoring leader trade size.
  Added explicit `rm_mirror` path: uses `mirror_size_direct` (same as proportional
  with no pct), capping at the user's position cap. Unknown modes now log a warning
  and skip rather than silently mis-sizing.
- `copy_trade.py` — `proportional` mode with `copy_pct=0` or `None` fell through
  to the else branch and would have triggered the unknown-mode warning. Now
  explicitly validated: skips with a warning when `pct <= 0`.
- `_normalise_side` — unvalidated `side` and `copy_direction` inputs could produce
  silent incorrect routing. Now guards both fields before any logic executes.

---

## 6. What Is Next

Validation Tier   : MAJOR
Claim Level       : FULL RUNTIME INTEGRATION
Validation Target : Copy Trade scan loop reads copy_trade_tasks; dedup via
                    copy_trade_idempotency; SignalCandidate.reasoning
                    populated on all three active strategies; messages.py
                    divider width 32-char throughout.
Not in Scope      : signal_evaluator.py reasoning, copy_targets DB cleanup,
                    migration for copy_trade_idempotency backfill,
                    i18n of reasoning strings.
Suggested Next    : WARP•SENTINEL validation required before merge.
                    Source: projects/polymarket/crusaderbot/reports/forge/master-cleanup-v5-beta.md
                    Tier: MAJOR
