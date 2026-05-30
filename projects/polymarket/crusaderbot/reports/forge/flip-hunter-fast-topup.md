# flip-hunter-fast-topup

## 1. What was built

Post-fill "complete the set" loop for `safe_close` and `flip_hunter` presets. After a successful lead entry leaves the user's per-market exposure imbalanced (`|imbalance_usdc| >= FAST_TOPUP_MIN_USDC`), the scanner synthesises a TradeSignal for the lagging leg and runs it through `TradeEngine.execute`. Cooldown per `(user, market)` prevents the same pair from spinning top-ups within `FAST_TOPUP_COOLDOWN_SECONDS`.

This closes Polybot directive **1.5** + **1.3.2** (fast top-up after fill). For our paper engine fills are always complete, so "partial fill" collapses to "after every successful entry" — the top-up acts as the second half of the directive's intended dual-leg pair when only one side was originally placed.

**Default OFF** (`FLIP_HUNTER_FAST_TOPUP_ENABLED=false`) — dark launch like Lane B + D-2.

## 2. Current system architecture

```text
late_entry_v3 (safe_close / flip_hunter preset)
        │
        ▼
_process_candidate
        ├── ...all existing gates...
        ├── 1a-2. Imbalance override (Lane D-2)
        ├── 1b. Side-aware dedup     (Lane D-2)
        ├── ...
        ├── 4. _engine.execute  ────────► success ─┐
        └── 5. _insert_execution_queue              │
                       │                            │
                       └─► FAST TOP-UP ◄────────────┘
                            (this lane)
                            │
                            ▼
                       _maybe_fire_fast_topup
                            │ config-gated
                            │ preset-scoped (safe_close|flip_hunter)
                            │ cooldown-gated (per user+market)
                            ▼
                       _fetch_market_inventory_for_override
                            │ same helper as D-2 (single patchable surface)
                            ▼
                       if |imbalance_usdc| >= threshold
                          and just_filled_side != lagging:
                          ┌──────────────────────────────┐
                          │ Synthesise TradeSignal:      │
                          │   side=lagging               │
                          │   size=min(|imb|, lead_size) │
                          │   price=live_or_fallback     │
                          │   strategy_type=fast_topup   │
                          └──────────────┬───────────────┘
                                         ▼
                                   _engine.execute
                                         │
                                         ├── approved → scan_outcome=fast_topup_fired
                                         └── rejected → scan_outcome=fast_topup_rejected
                                         │ (cooldown stamped either way)
```

Why direct `_engine.execute` rather than recursive `_process_candidate`?
- The top-up is reactive, not predictive — TOB freshness gate, complete-set edge gate, safe-close direction limit don't apply.
- The 13-step risk gate inside `TradeEngine.execute` (Kelly, daily loss, position cap, kill switch, etc.) still runs.
- Cleaner control flow: no recursion risk, no need for an `is_fast_topup` skip flag on the scan gates.
- Idempotency key is distinct (`fast_topup:{user}:{market}:{monotonic_ms}`) so the engine's duplicate guard treats it as a new commitment.

## 3. Files created / modified

```text
projects/polymarket/crusaderbot/config.py
projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
projects/polymarket/crusaderbot/tests/test_flip_hunter_fast_topup.py  (NEW)
projects/polymarket/crusaderbot/reports/forge/flip-hunter-fast-topup.md  (NEW)
projects/polymarket/crusaderbot/state/PROJECT_STATE.md
projects/polymarket/crusaderbot/state/CHANGELOG.md
```

### `config.py`
Three new knobs:
- `FLIP_HUNTER_FAST_TOPUP_ENABLED: bool = False` (dark launch)
- `FAST_TOPUP_MIN_USDC: float = 5.0` (validator: > 0, finite — 0 / NaN / Inf rejected at load)
- `FAST_TOPUP_COOLDOWN_SECONDS: float = 15.0` (validator: > 0, finite — 0 would let the same pair spin top-ups continuously)

### `services/signal_scan/signal_scan_job.py`
- New module-level state `_fast_topup_last_at: dict[str, float]` keyed by `f"{user_id}:{market_id}"`.
- New `_fast_topup_reset_for_tests()` helper for test isolation.
- New `_fast_topup_key(user_id, market_id)` helper.
- New `_FAST_TOPUP_ELIGIBLE_PRESETS = frozenset({"flip_hunter", "safe_close"})` scope constant.
- New `_maybe_fire_fast_topup(*, row, market, just_filled_side, just_filled_size_usdc, log)` async helper. On config-read failure: log + bail. Cooldown checked WITHOUT a DB hit. Inventory reuses `_fetch_market_inventory_for_override` from D-2 so there's a single patchable surface for tests.
- Wired at success branch of `_process_candidate` (gated on `inserted` so concurrent-tick dedup skips never trigger a top-up).
- Top-up size: `min(|imbalance|, just_filled_size)` so we never escalate beyond the original commitment.
- Top-up price: live mark for the lagging side, with fallback to `market.no_price` / `market.yes_price` (binary invariant) when the live RPC fails.
- Cooldown is stamped on EVERY engine result (approved + rejected) so a rejection feedback loop doesn't immediately re-fire the same attempt.

### `tests/test_flip_hunter_fast_topup.py`
25 tests:
- 4 source-level pins (helper exists, wired at success path, reads all 3 knobs, eligible-preset set pinned)
- 4 config tests (default OFF, defaults 5.0/15.0, parametrized rejection of `0 / -1.0 / nan / inf / -inf` per knob)
- 10 behavioural (disabled-does-not-fire, enabled-fires-to-lagging, no-fire-below-threshold, no-fire-for-close-sweep, no-fire-when-just-filled-was-lagging, no-fire-on-empty-inventory, cooldown-blocks-second-topup, cooldown-stamps-even-on-rejected, topup-size-capped-at-lead-size, fallback-to-market-price-on-live-fetch-fail)

## 4. What is working

- 25/25 tests pass locally; 56/56 prior lane tests (D-2 + D-1 + BNB) still pass (no regression).
- `ruff check` + `py_compile` clean on all modified files.
- Default OFF posture means deploying this lane is a true no-op vs current behavior.
- Fast-topup helper is fully patchable for downstream tests (uses module-level `_engine.execute` + `get_live_market_price` + `_fetch_market_inventory_for_override`).

## 5. Known issues

- Cooldown state is in-process; a Fly restart clears every (user, market) pair. Acceptable — next eligible entry re-arms the cooldown.
- The top-up's `signal_ts=now` and synthetic `idempotency_key` mean it doesn't link back to a `signal_publication` row. By design — fast top-ups are reactive and have no upstream publication.
- The 30-60s window check from directive 1.2.1.4 is NOT enforced here. CrusaderBot's paper engine has no concept of "candle window" at top-up time; the lead entry's strategy already filtered for the right window. If we ever need a stricter "skip if too close to expiry" check, it would slot in as a market-row `end_date_iso` comparison inside the helper.

## 6. What is next

- **Operator action**: deploy with `FLIP_HUNTER_FAST_TOPUP_ENABLED=false` (default), watch the `scan_outcome` log for any `imbalance_override_applied` rate from D-2, then flip BOTH `D-2` and `D-3` flags when paper stats look right.
- **Lane D-4** `WARP/R00T/dual-leg-execution` — simultaneous YES+NO entry at scan time for Close Sweep (directive 1.1.2.c). Largest remaining lane.

---

**Validation Tier**: MAJOR
**Claim Level**: NARROW INTEGRATION
**Validation Target**: helper present, scoped to eligible presets, cooldown enforced, top-up size capped, live-price fallback, engine.execute called with correct signal, regression suite green.
**Not in Scope**: simultaneous dual-leg entry (Lane D-4), candle-window re-check, persistent cooldown across restarts.
**Suggested Next Step**: WARP🔹CMD review + merge → deploy with default OFF → operator flips with D-2 simultaneously once paper stats validate both.
