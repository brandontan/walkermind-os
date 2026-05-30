# safe-close-imbalance-override

## 1. What was built

First behavioural consumer of the Lane D-1 `MarketInventory` foundation. When a `safe_close` `late_entry_v3` candidate fires on a market where the user already holds imbalanced exposure (`|imbalance_usdc| > threshold`), the scanner:

1. Computes inventory via `domain.strategy.inventory.compute_market_inventory`.
2. Identifies the lagging leg (less-exposure side).
3. If the candidate's intended side differs from the lagging leg, rebuilds the candidate via `dataclasses.replace` (SignalCandidate is frozen) with `side=lagging_leg` + `metadata["imbalance_override"]={...}` audit stamp.
4. Switches the open-position dedup from the broad market-wide variant to the new side-aware `_has_open_position_for_side` so the rebalance can actually fire — the standard dedup would block any second market-level entry.

Default OFF (`SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED=false`) — dark-launched like Lane B. Other strategies / presets keep the unmodified broad open-position dedup.

This closes Polybot directive **1.2.1.c** (Safe Close inventory balance check) and is the first lane in the series that allows opposite-side entries on the same market.

## 2. Current system architecture

```text
late_entry_v3 (safe_close preset)
        │ candidate = SignalCandidate(side="yes" or "no")
        ▼
_process_candidate
        │
        ├── 0.    Crash-recovery resume                  (untouched)
        ├── 0a.   Bankroll circuit breaker               (Lane B)
        ├── 1.    Permanent dedup                        (untouched)
        ├── 1a-2. SAFE-CLOSE IMBALANCE OVERRIDE          ← THIS LANE
        │           if cfg.ENABLED
        │               and cand.strategy == late_entry_v3
        │               and active_preset == safe_close:
        │             inv = compute_market_inventory(conn, user, market)
        │             if |inv.imbalance_usdc| > threshold
        │                and cand.side != lagging_leg:
        │                 cand = dataclasses.replace(cand,
        │                     side=lagging_leg,
        │                     metadata={..., "imbalance_override": {...}})
        │                 _imbalance_override_active = True
        ├── 1b.   Open-position dedup                    (override-aware)
        │           if _imbalance_override_active:
        │             _has_open_position_for_side(user, market, side)
        │           else:
        │             _has_open_position_for_market(user, market)  (broad)
        ├── 1c.   Signal freshness gate                  (untouched)
        ├── 3b-0. TOB freshness gate                     (Lane 1)
        ├── 3b-0a. Complete-set edge gate                (Lane A)
        └── ...   strategy gates → engine
```

The override path is fully bypassed when `cfg.ENABLED` is False — the gate runs `if _imb_enabled and ...` so OFF means "no inventory query, no side mutation, no dedup-relax". Deploying with the default flag is a true no-op vs pre-lane behaviour.

## 3. Files created / modified

```text
projects/polymarket/crusaderbot/config.py
projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
projects/polymarket/crusaderbot/tests/test_safe_close_imbalance_override.py  (NEW)
projects/polymarket/crusaderbot/reports/forge/safe-close-imbalance-override.md (NEW)
projects/polymarket/crusaderbot/state/PROJECT_STATE.md
projects/polymarket/crusaderbot/state/CHANGELOG.md
```

### `config.py`
- Two new knobs:
  - `SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED: bool = False` (dark launch)
  - `SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC: float = 5.0` (USDC cost basis, NOT shares — our position model tracks cost basis; the directive's "20 shares" maps to ~$5 in paper given typical $0.20–$0.80 entries)
- New `validate_safe_close_imbalance_threshold` field validator:
  - Rejects non-finite (NaN / ±Inf) — gate uses `> threshold`, NaN comparisons are False so NaN would silently disable.
  - Rejects `<= 0` — zero would override on any non-zero imbalance which collapses to "always override," a noise amplifier rather than a guardrail.

### `services/signal_scan/signal_scan_job.py`
- New helper `_has_open_position_for_side(user_id, market_id, side) -> bool` — side-aware variant; does NOT include the 24h closed window because the override is specifically opening a NEW opposite-side position and a recently-closed same-side position is no reason to block.
- New step 1a-2 in `_process_candidate` between dedup (step 1) and open-position-dedup (step 1b). Reads config lazily; on config-read failure fails CLOSED (override disabled) — a broken config never silently opens the dedup-relax branch.
- Override path uses `dataclasses.replace(cand, side=lagging_side, metadata={..., "imbalance_override": {...}})` — SignalCandidate is `frozen=True` so direct attribute mutation would raise `FrozenInstanceError`.
- The existing step 1b is override-aware: when the override fired, swaps the dedup to `_has_open_position_for_side`. Otherwise the broad `_has_open_position_for_market` is unchanged.
- New `import dataclasses.replace as _dc_replace` at module level.

### `tests/test_safe_close_imbalance_override.py`
14 tests:
- 4 source pins (override path present, scope to safe_close + late_entry_v3, override-aware dedup branch, `_dc_replace` usage instead of attribute mutation)
- 3 config tests (default OFF, threshold default 5.0, parametrized rejection of `0 / -1.0 / nan / inf / -inf`)
- 7 behavioural integration (disabled-passes-unchanged, enabled-flips-side-when-imbalanced, no-flip-below-threshold, no-flip-when-already-on-lagging, no-flip-for-close-sweep, no-flip-when-empty-inventory, side-aware-dedup-blocks-same-lagging-side)

## 4. What is working

- `ruff check` + `py_compile` clean on all 3 modified files.
- Override path correctly uses `dataclasses.replace` not attribute assignment (would have raised `FrozenInstanceError` at runtime if dropped).
- Side-aware dedup invocation gated on `_imbalance_override_active` flag — other candidates unchanged.
- Config read failure path: fails CLOSED (override disabled) so a broken config never silently opens the dedup-relax branch.
- Default OFF posture means deploying this lane is a true no-op — operator picks when to flip the flag.

## 5. Known issues

- Tests cannot run in this remote container (no `fastapi / structlog`); CI is the authoritative runner.
- Per-candidate inventory query adds one DB round-trip when the override flag is ON. The query has a 5s timeout (from Lane D-1) and is indexed (`idx_positions_user`); per-tick cost should be negligible vs the existing scan latency.
- The "already on lagging side" case (`test_enabled_override_no_flip_when_already_on_lagging_side`) currently blocks the entry via broad dedup. That's a conservative choice: if the user already holds YES-heavy + the scanner picked NO, we could let the rebalance through, but doing so requires routing through the same dedup-relax path as the actual override case. Deferred — easy to add as a follow-up if production observation shows it's wanted.
- "Fast top-up" (directive 1.2.1.4) is NOT in this lane — that's the post-fill chase loop. Lane D-3 work.

## 6. What is next

- **Operator action**: deploy with default OFF, observe `scan_outcome=imbalance_override_applied` rate via existing telemetry for 24-48h, then flip `SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED=true` once we've confirmed the override fires at a sane cadence (not on every tick, not never).
- **Lane D-3** `WARP/R00T/flip-hunter-fast-topup` — post-partial-fill loop that chases the opposite leg via TAKER order. Depends on the dedup-relax precedent set here.
- **Lane D-4** `WARP/R00T/dual-leg-execution` — full simultaneous YES+NO entry for Close Sweep. Largest delta; comes last.

---

**Validation Tier**: MAJOR
**Claim Level**: NARROW INTEGRATION
**Validation Target**: signal_scan_job step 1a-2 (new gate); side-aware dedup; SignalCandidate replace-not-mutate; config validator; scoped firing.
**Not in Scope**: fast top-up loop (Lane D-3), dual-leg simultaneous entry (Lane D-4), already-on-lagging-side soft-pass.
**Suggested Next Step**: WARP🔹CMD review + merge → deploy with default OFF → 24-48h paper soak → operator flips to true.
