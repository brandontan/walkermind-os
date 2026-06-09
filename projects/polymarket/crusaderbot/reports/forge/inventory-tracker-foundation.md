# inventory-tracker-foundation

## 1. What was built

New `domain/strategy/inventory.py` module that aggregates per-`(user, market)` open exposure from the existing `positions` table. Surfaces a frozen `MarketInventory` dataclass with `yes_size_usdc / no_size_usdc / yes_count / no_count` + derived properties `imbalance_usdc`, `imbalance_pct`, `total_size_usdc`, `is_empty`.

Foundation lane — **observation only, no execution-layer change**. The Polybot directive's full §5 spec (`MarketInventory` for dual-leg arb) is designed to support a strategy that holds both YES and NO legs simultaneously and rebalances via fast top-ups. CrusaderBot's current execution model is single-leg per candidate with `_has_open_position_for_market` blocking second entries on a market for 24h. Building the data structure now lets follow-up lanes wire it in as thin gate insertions:

1. **Safe Close direction override** (directive 1.2.1.c) — when `imbalance_pct` exceeds threshold, force the candidate side to the lagging leg.
2. **Flip Hunter Mode A fast top-up** (directive 1.5 + 1.3.2) — chase the opposite leg immediately after a partial fill.
3. **Cross-strategy exposure cap** (directive #6 §6) — sum `total_size_usdc` across the user's open markets for a portfolio-level position cap.

## 2. Current system architecture

```text
                positions (existing)
                       │
                       │  user_id + market_id
                       │  status ∈ {open, pending_settlement}
                       ▼
domain.strategy.inventory.compute_market_inventory(conn, user_id, market_id)
                       │  GROUP BY LOWER(side)
                       │  SUM(size_usdc) per side
                       │  COUNT(*) per side
                       ▼
              MarketInventory
                       │  imbalance_usdc = yes_size_usdc - no_size_usdc
                       │  imbalance_pct  = imbalance_usdc / total_size_usdc
                       ▼
        (consumed by future lanes — none in this PR)
```

No DB schema change. No existing call path modified. The module is importable but currently unwired — that's intentional so the foundation can land + be reviewed in isolation.

## 3. Files created / modified

```text
projects/polymarket/crusaderbot/domain/strategy/inventory.py         (NEW)
projects/polymarket/crusaderbot/tests/test_inventory_tracker.py      (NEW)
projects/polymarket/crusaderbot/reports/forge/inventory-tracker-foundation.md  (NEW)
projects/polymarket/crusaderbot/state/PROJECT_STATE.md
projects/polymarket/crusaderbot/state/CHANGELOG.md
```

### `domain/strategy/inventory.py`
- `MarketInventory` frozen dataclass with the 4 raw fields + 4 derived properties.
- `compute_market_inventory(conn, user_id, market_id) -> MarketInventory` async helper.
- `_LIVE_POSITION_STATUSES = frozenset({"open", "pending_settlement"})` — only these contribute. Closed positions are intentionally excluded because their cost basis is already realised against the user's bankroll; including them would double-count.
- Defensive: unknown side labels (corruption) are ignored silently rather than crashing the scan tick.

### `tests/test_inventory_tracker.py`
13 tests:
- 5 dataclass invariants (yes-heavy + no-heavy + balanced imbalance math, empty-pct sentinel, frozen-dataclass pin)
- 8 aggregation contract tests (yes+no rows, yes-only, no-only, no-rows-returns-empty, side-label normalisation, unknown-side-ignored, decimal-precision via string coercion, status filter SQL pin, live-status constant pin)

## 4. What is working

- `ruff check .` + `py_compile` clean on both new files.
- Frozen dataclass prevents accidental mutation by downstream callers.
- Decimal-via-string coercion avoids `Decimal + float` deprecation warnings.
- SQL aggregation pinned by call-signature assertion: future edits that drop the `status = ANY(...)` filter or widen the live-status set surface immediately.
- Empty-inventory shortcut (`_empty_inventory(...)`) gives callers a stable shape so they never need to branch on `inv is None`.

## 5. Known issues

- Tests cannot run in this remote container (no `fastapi / structlog`); CI is the authoritative runner.
- The module is currently unwired — no strategy reads it yet. That's by design (foundation lane), but it does mean the module gets zero production traffic until Lane D-2.
- Aggregation runs at most one query per `(user, market)` call. Future wiring at scan-time should consider caching: the dedup gate (`_has_open_position_for_market`) already runs per candidate, so callers can fold the inventory query into the same DB round-trip if hot-path latency matters.
- "Background sync every 5s" (directive §5 Polybot spec) is NOT implemented — it becomes meaningful only with dual-leg execution, and the per-call query is fast enough for the single-leg consumer pattern Lane D-2/3 will use.

## 6. What is next

- **Lane D-2** `WARP/R00T/safe-close-imbalance-override` (directive 1.2.1.c) — when Safe Close fires a candidate for a market with `|imbalance_pct| > threshold`, override the side to the lagging leg. Requires relaxing the dedup gate for opposite-side entries on the same market — biggest behavioural change in the inventory series and where I'd want operator sign-off before starting.
- **Lane D-3** `WARP/R00T/flip-hunter-fast-topup` (directive 1.5 + 1.3.2) — post-partial-fill loop that chases the opposite leg via TAKER order. Depends on D-2's dedup-relax precedent.
- **Lane D-4** `WARP/R00T/dual-leg-execution` — full simultaneous YES+NO entry for Close Sweep (directive 1.1.2.c). Most architectural; requires execution-engine work; comes last.

---

**Validation Tier**: STANDARD
**Claim Level**: FOUNDATION
**Validation Target**: dataclass invariants + SQL aggregation contract (status filter, side normalisation, decimal precision).
**Not in Scope**: strategy wiring, dedup-gate changes, dual-leg execution, background sync loop, market-expiry reset.
**Suggested Next Step**: WARP🔹CMD review + merge → no operator action needed (module is unwired, zero production impact) → operator decides whether Lane D-2 dedup-gate relaxation is in scope before I start it.
