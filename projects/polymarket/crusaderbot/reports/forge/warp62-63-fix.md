# Forge Report — warp62-63-fix

**Branch:** `WARP/warp62-63-fix`
**Issues:** #1273 (WARP-62) + #1274 (WARP-63)
**Date:** 2026-05-22 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** MECHANICAL
**Flagged by:** WARP•SENTINEL core-audit-2026-05-21 (F-001 + F-002)

---

## 1. What was built

**WARP-62 — P0: threading removal from StrategyRegistry**

Replaced the double-checked locking singleton pattern in `domain/strategy/registry.py` with a module-level eager initialisation. `import threading` removed. `_singleton` and `_singleton_lock` class attrs removed. `instance()` now returns the module-level `_DEFAULT_REGISTRY`. `_reset_for_tests()` reassigns `_DEFAULT_REGISTRY` via `global` keyword. Python's module import system provides the one-time initialisation guarantee; no lock needed for a single-process asyncio application.

**WARP-63 — P1: CopyTradeStrategy.scan() migrated to copy_trade_tasks**

Updated `domain/signal/copy_trade.py` to read from `copy_trade_tasks` (canonical execution table) instead of `copy_targets` (legacy). Column mapping applied:
- `target_wallet_address` → `wallet_address`
- `scale_factor` (multiplier) → `copy_amount` (fixed USDC amount)
- `last_seen_tx` tracking removed — column does not exist in `copy_trade_tasks`

The `last_seen_tx` UPDATE write to `copy_targets` is also removed. Deduplication at the execution layer (via `orders.idempotency_key`) remains the canonical guard.

9 hermetic tests added for the new read path (`tests/test_warp63_copytrade_strategy_scan.py`): 5 source-level assertions + 4 behavioural tests (empty path, zero-size skip, wallet fetch error recovery, SQL argument verification). No DB, no broker.

---

## 2. Current system architecture

```
DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING
                        |
            StrategyRegistry.instance()
            (module-level eager singleton — no threading)
                        |
            CopyTradeStrategy (domain/strategy/strategies/copy_trade.py)
            CopyTradeStrategy (domain/signal/copy_trade.py — scheduler)
                        |
            Both now read copy_trade_tasks (canonical)
            copy_targets: legacy wizard-only writes; no domain reads remain
```

No pipeline stage skipped. RISK before EXECUTION unchanged. ENABLE_LIVE_TRADING guard untouched.

---

## 3. Files created / modified (full repo-root paths)

**Modified**
- `projects/polymarket/crusaderbot/domain/strategy/registry.py` — threading removed, eager init
- `projects/polymarket/crusaderbot/domain/signal/copy_trade.py` — copy_targets → copy_trade_tasks

**Created**
- `projects/polymarket/crusaderbot/tests/test_warp63_copytrade_strategy_scan.py` — 9 hermetic tests
- `projects/polymarket/crusaderbot/reports/forge/warp62-63-fix.md` — this file

**State files updated**
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What is working

- `domain/strategy/registry.py`: `import threading` removed. `StrategyRegistry.instance()` returns `_DEFAULT_REGISTRY`. `_reset_for_tests()` reassigns module global. All 9 inline logic checks pass:
  - `instance()` returns same object on repeated calls
  - `_reset_for_tests()` creates a fresh empty registry
  - `threading` string absent from source file
- `domain/signal/copy_trade.py`: `copy_targets` absent from source. `copy_trade_tasks`, `wallet_address`, `copy_amount` all present. `last_seen_tx` absent.
- 9/9 WARP-63 hermetic tests pass:
  - Source-level guards (5 tests)
  - Empty task path (1 test)
  - Zero-size trade skip (1 test)
  - Wallet fetch error recovery (1 test)
  - SQL argument verification — query targets `copy_trade_tasks`, passes `user["id"]` (1 test)

---

## 5. Known issues

- `domain/signal/copy_trade.py` has a pre-existing `SignalCandidate` field mismatch (uses `size_usdc`, `strategy_type`, `extra`, `price` — old field names not present in canonical `SignalCandidate` from `domain.strategy.types`). This was introduced by WARP-26 which migrated the canonical type but left this file using old names. The field mismatch is out of scope for WARP-63 (which targets SQL migration only). Behavioural tests that would reach `SignalCandidate` construction are deferred to the follow-up lane that resolves this pre-existing break.
- `copy_trade_tasks` has no `last_seen_tx` column. Per-trade deduplication now relies entirely on the execution layer (`orders.idempotency_key`). Signal-level dedup (previously done by stopping at the cached tx hash) is removed. Duplicate signal candidates may be emitted across successive scans, but the execution idempotency key (`{user_id}:{market_id}:{side}:{src_tx[:32]}`) in `scheduler.py:270` prevents duplicate orders.

---

## 6. What is next

- WARP🔹CMD review required.
- On merge: re-run WARP•SENTINEL core audit (WARP/sentinel-core-audit-2026-05-21) to confirm F-001 + F-002 closed and score moves above 85 for APPROVED verdict.
- Follow-up: fix `domain/signal/copy_trade.py` `SignalCandidate` field mismatch (pre-existing) in a separate lane.

---

**Validation Target:** `StrategyRegistry.instance()` threading-free; `CopyTradeStrategy.scan()` in `domain/signal/copy_trade.py` reads `copy_trade_tasks` using canonical columns; `copy_targets` no longer referenced in domain strategy scan paths.

**Not in Scope:** strategy logic, execution path, risk gate, activation guards, legacy wizard handlers (`bot/handlers/setup.py`, `bot/handlers/copy_trade.py`), `copy_targets` table drop, SignalCandidate field alignment in `domain/signal/copy_trade.py`.

**Suggested Next Step:** WARP🔹CMD review → merge → WARP•SENTINEL re-run to close the BLOCKED verdict.
