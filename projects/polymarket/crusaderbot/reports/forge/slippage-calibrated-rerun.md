# WARP-83 Phase 2b — Calibrated Slippage Replay Re-run

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: the Sub-Lane A↔B wiring (`resolve_slippage_model` now loads the
merged `domain/research/slippage_estimator.py` via a typed `CalibratedSlippageModel`
adapter) and the calibrated slippage-vs-paper-P&L gate result on current
`paper_real` settled data.
Not in Scope: LIVE-sized slippage modeling (paper sizes are ~$7); fixing the
`domain/research/__init__` dual-root import anomaly (flagged below, left to CMD);
cutover threshold proposals (Sub-Lane C) and per-cell narrative (Sub-Lane D).
Suggested Next Step: WARP🔹CMD review; feed these calibrated numbers into Sub-Lane C
(cutover gate thresholds) and Sub-Lane D (per-cell report).

---

## 1. What was built

Phase 2b reconciles the two parallel WARP-83 lanes after both merged and re-runs the
catastrophic-slippage gate on the **calibrated** estimator instead of the placeholder.

1. **Adapter (`CalibratedSlippageModel`)** in `scripts/replay_with_slippage.py` —
   Sub-Lane A merged a keyword-only factor function `estimate_slippage_bps(**kwargs)
   -> SlippageEstimate`, which does not match the engine's `SlippageModel` Protocol
   (`__call__(SlippageInputs) -> float`). The adapter maps `SlippageInputs` onto the
   estimator kwargs (`size_usdc→stake_usdc`, `orderbook_depth_usdc`, `spread`,
   `entry_price`; `current_price=entry_price` ⇒ zero adverse-move by construction —
   the replay reconstructs entry-time factors only) and returns `total_bps`.

2. **Resilient loader (`_import_estimate_slippage_bps`)** — fixes a real packaging
   defect that would otherwise make the auto-upgrade silently no-op. The
   `domain/research/__init__` package eagerly imports `robustness`, whose
   `from ...database import get_pool` only resolves under the repo/pytest import root,
   NOT under the crusaderbot dir that the script (and the bot) put on `sys.path`. So
   the plain `from domain.research.slippage_estimator import …` raises ImportError at
   the script's own runtime root and `resolve_slippage_model` fell back to
   `DefaultSlippageModel` — defeating the entire calibrated re-run. The loader now:
   (1) tries the normal package import; (2) on failure, loads the estimator leaf
   module directly via `importlib` (registered in `sys.modules` before `exec_module`),
   bypassing the broken `__init__` chain; (3) only then degrades to the default. Every
   step is logged (`slippage_estimator_loaded_direct` / `…_fallback`) — no silent
   failure.

3. **Calibrated gate re-run** — executed against the canonical Supabase project
   (`ykyagjdeqcgcktnpdhes`) by replicating the engine's exact lateral join + the
   calibrated per-trade formula in SQL, because the CC env has no `DATABASE_URL`
   (same method that produced the Sub-Lane B baseline). DB output treated as untrusted.

## 2. Current system architecture

```
positions (mode=paper, status=closed, pnl_usdc NOT NULL)
   └─ JOIN LATERAL nearest factor_vectors (paper_real, settled, ±10/+60 min)
          │
          ▼
   SlippageInputs ──► resolve_slippage_model()
                          │  loads domain/research/slippage_estimator.estimate_slippage_bps
                          │  (direct importlib load — bypasses domain.research.__init__)
                          ▼
                    CalibratedSlippageModel(x) = total_bps
                          = max(0, spread-1.0)*0.5*1e4   (complete-set spread cost)
                          + 0.02*sqrt(min(size/depth,4))*1e4  (sqrt market impact)
                          + 0                              (no live price in replay)
                          │
                          ▼
   per-trade cost = size_usdc * total_bps/1e4 → adjusted_pnl = paper_pnl - cost
                          │
                          ▼
   aggregate_by_cell → per-cell + overall slippage fraction vs 50% gate
```

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/scripts/replay_with_slippage.py`
  (added `CalibratedSlippageModel` adapter; rewrote `resolve_slippage_model` to use
  the new resilient `_import_estimate_slippage_bps` loader).
- Created: `projects/polymarket/crusaderbot/reports/forge/slippage-calibrated-rerun.md`
  (this report).
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `resolve_slippage_model()` now returns `CalibratedSlippageModel` (verified loaded
  via the direct-importlib path) under the script's own runtime root; degrades to
  `DefaultSlippageModel` only if the estimator leaf is genuinely absent — logged.
- 25/25 tests pass: `tests/test_replay_with_slippage.py` (16) +
  `tests/test_slippage_estimator.py` (9, incl. the +inf-stake clamp).
- **Calibrated gate result (current `paper_real` settled data, n=541, last ~36 h):**

  | Cell | n | avg bps | gross P&L | slippage $ | adj. P&L | slip % |
  |---|---|---|---|---|---|---|
  | btc/5m | 255 | 56.7 | +$269.84 | $10.33 | +$259.52 | 3.8% |
  | eth/5m | 263 | 60.0 | +$121.84 | $11.22 | +$110.62 | 9.2% |
  | btc/15m | 10 | 59.7 | +$4.47 | $0.26 | +$4.21 | 5.8% |
  | eth/15m | 9 | 68.8 | −$22.47 | $0.27 | −$22.73 | 1.2% |
  | sol/15m | 4 | 87.7 | −$10.66 | $0.15 | −$10.81 | 1.4% |
  | **ALL** | **541** | **58.8** | **+$363.02** | **$22.22** | **+$340.80** | **6.1%** |
  | PRIMARY btc+eth/5m | 518 | 58.4 | +$391.68 | $21.55 | +$370.14 | 5.5% |

- **Gate: 6.1% overall ≪ 50% → NO BREACH.** The Sub-Lane B baseline of **150.7%**
  (catastrophic) was a `DefaultSlippageModel` artifact: it computed spread cost as
  `(spread/entry_price)*1e4`, treating the complete-set `spread` (≈1.01) as a
  price-unit spread → ~20,000 bps. The calibrated estimator correctly reads `spread`
  as the complete-set sum and charges only the excess over 1.0 (~52 bps avg), plus a
  sqrt-impact term (~6 bps avg). Current data empirically confirms the estimator's
  complete-set assumption: `spread` avg 1.0104, min 1.009, max 1.05.

## 5. Known issues

- **Paper sizing is tiny (~$7 avg).** The dominant calibrated component is the
  **size-independent** complete-set spread cost (~52 bps); the **size-dependent**
  sqrt-impact term is only ~6 bps because $7 against a 7k–16k USDC book is a
  negligible participation ratio. At LIVE sizing (Kelly-0.25 of real capital) the
  impact term grows as `sqrt(size/depth)` — e.g. ~45 bps at $500 and ~141 bps at
  $5,000 on a $10k book. **The 6.1% gate result is valid for current paper sizing
  only; it is NOT a LIVE-sizing clearance.** Sub-Lane C must re-evaluate the gate at
  realistic LIVE notional.
- **`domain/research/__init__` dual-root import anomaly (pre-existing, out of lane).**
  `robustness.py` uses `from ...database import get_pool`, which resolves only under
  the repo/pytest root, not the crusaderbot runtime root. The whole `domain.research`
  package is therefore un-importable as a side-effect under the bot's own `sys.path`.
  Worked around here (direct leaf load); flagged for a dedicated CMD-scoped fix rather
  than touching the Monte-Carlo plane from this lane.
- Replay window is the last ~36 h of regenerated `paper_real` data (the old uppercase
  `BTC/5m`/`ETH/5m` set referenced by the baseline has aged out / been replaced; cells
  are now lowercase `btc/5m`, `eth/5m`). The `--from-db` script path itself is still
  unexercised in CC (no `DATABASE_URL`); an operator `--from-db` run is the confirming
  follow-up.

## 6. What is next

- WARP🔹CMD review of the calibrated gate result (NARROW INTEGRATION / STANDARD).
- Sub-Lane C: cutover gate thresholds — re-run this formula at **LIVE-realistic
  notional**, not paper $7, before proposing thresholds.
- Sub-Lane D: per-cell slippage report using these calibrated per-cell numbers.
- Operator confirming run: `python scripts/replay_with_slippage.py --days 7
  --cells BTC/5m,ETH/5m --from-db` against a real `DATABASE_URL` to exercise the
  script's own loader end-to-end.
