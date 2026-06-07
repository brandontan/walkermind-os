# WARP-83 Sub-Lane B — Slippage Replay Engine

Branch: WARP/slippage-replay-engine
Role: WARP•FORGE
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: scripts/replay_with_slippage.py — the replay/aggregation/gate math and the dependency-injection seam (SlippageModel Protocol + DefaultSlippageModel + resolve_slippage_model fallback), proven by tests/test_replay_with_slippage.py. The DB loader's SQL join shape is verified against the canonical Supabase schema and a live row count (read-only), but the script's own --from-db path is NOT exercised in CC (no DATABASE_URL in this env).
Not in Scope: Sub-Lane A's slippage estimator (built in parallel, absent on this branch — consumed only via a graceful import); any change to ev_comparator / scorer_trainer / orchestrator (scope lock); §1.7 cutover logic; new orderbook capture; new dependencies; any LIVE decision (this engine flags, it does not decide).
Suggested Next Step: WARP🔹CMD review of the >50% gate breach finding (below). After Sub-Lane A merges, a CMD-gated follow-up wires resolve_slippage_model to the calibrated estimator and re-runs the gate on the real model.

---

## 1. What was built

A standalone slippage replay engine: `projects/polymarket/crusaderbot/scripts/replay_with_slippage.py`.

It re-runs the last N days of settled `paper_real` trades through a slippage model and computes the slippage-adjusted P&L per trade, aggregated per cell (`asset/timeframe`, e.g. `BTC/5m`). Purpose: quantify how much paper P&L survives realistic execution cost before any LIVE viability claim.

Core capabilities:

- CLI: `--days N --cells BTC/5m,ETH/5m --from-db` (plus `--data-source`, default `paper_real`).
- Dependency injection of the slippage model (see §2) so the engine is decoupled from Sub-Lane A, which is being built on a parallel branch and does NOT exist here.
- A self-contained `DefaultSlippageModel` reference implementation so the script runs standalone today.
- Per-trade slippage-adjusted P&L + per-cell aggregation + a >50% catastrophic LIVE-viability gate.
- Untrusted-DB hardening: per-field coercion, NaN/inf/NULL guards, per-row skip+log, fail-soft DB read.

## 2. Current system architecture

Injection seam (the decoupling requirement):

- `SlippageInputs` (frozen dataclass) — per-trade features (side, entry_price, size_usdc, liquidity_usdc, spread, volatility_sigma, orderbook_depth_usdc), shaped to the `positions × factor_vectors` join.
- `SlippageModel` (runtime-checkable `Protocol`) — any callable `SlippageInputs -> float` (slippage in basis points).
- `DefaultSlippageModel` — transparent reference impl: `bps = base(5) + 0.5·spread_bps + 80·(size/depth) + 50·vol`, clamped to `[0, 1000]` bps. Conservative, NOT calibrated.
- `resolve_slippage_model()` — `try: from domain.research.slippage_estimator import build_slippage_model` with a typed fallback to `DefaultSlippageModel`. The fallback is LOGGED (`slippage_estimator_fallback`, structlog INFO) — never silently swallowed — so the engine auto-upgrades the moment Sub-Lane A merges, and a missing/broken estimator is visible in run output (separate `slippage_estimator_import_error` / `slippage_estimator_build_failed` warnings on the unexpected paths).

Data flow:

```
positions (mode=paper, status=closed, pnl_usdc NOT NULL, opened_at within N days)
   └─ JOIN LATERAL nearest-by-time factor_vectors (data_source=paper_real, settled=TRUE, market_id match, opened_at within capture window)
        └─ _record_from_row (untrusted coercion) → replay_trade(model) → ReplayTradeRecord
             └─ aggregate_by_cell → {cell: CellAggregate}
                  └─ overall_gate → render_report (per-cell table + gate verdict)
```

Replay math: slippage is charged once on entry as a cost on the position notional — `cost = size_usdc · bps/10_000`; `adjusted_pnl = paper_pnl − cost`. Slippage is strictly non-negative (a worse fill), so it can only reduce P&L; a model returning negative bps is clamped to 0 and logged.

Gate: `overall_gate` divides total modeled slippage by the summed ABSOLUTE per-cell gross paper P&L (so opposite-signed cells don't cancel and mask erosion). Per-cell `slippage_fraction` divides by `|gross|` for that cell (zero-gross cell → fraction 0, never breaches). Breach threshold `SLIPPAGE_PNL_GATE_FRAC = 0.50`. A breach flags prominently in the report and exits non-zero (3), but the engine never decides.

Safety posture: read-only, PAPER data only, no order placement, never touches `ENABLE_LIVE_TRADING`. asyncio-only DB access via the existing `database.get_pool`/`pool.acquire`. Full type hints. structlog throughout. The DB read and per-row parse are fail-soft.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/scripts/replay_with_slippage.py`
- `projects/polymarket/crusaderbot/tests/test_replay_with_slippage.py`
- `projects/polymarket/crusaderbot/reports/forge/slippage-replay-engine.md`

Modified:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (7 sections, surgical)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (one appended line)

No modification to ev_comparator / scorer_trainer / orchestrator / §1.7 / capture / deps — scope locks honored.

## 4. What is working

- 9 synthetic tests pass: `python -m pytest projects/polymarket/crusaderbot/tests/test_replay_with_slippage.py -q` → 9 passed.
  - Winning trade exact adjusted-P&L (100bps on 200 USDC → cost 2.00 → adj 8.00).
  - Losing trade exact adjusted-P&L (50bps on 400 USDC → cost 2.00 → adj -7.00).
  - Multi-cell aggregation exact (BTC/5m + ETH/5m gross/slippage/adjusted/fraction asserted).
  - Gate breach (600bps on 100 USDC, paper 10 → frac 0.60 > 0.50 → BREACH true).
  - Negative-bps clamp, zero-gross-cell no-breach, cell normalize/parse, default-model bounds.
- `ruff check` clean on both new files.
- DI fallback verified at runtime: running the script with Sub-Lane A absent logs `slippage_estimator_fallback` and uses `DefaultSlippageModel`.
- Join shape verified against canonical Supabase schema `ykyagjdeqcgcktnpdhes` (read-only): 391 joinable settled paper_real rows over the full history; 372 over the last 7 days for BTC/5m+ETH/5m.

## 5. Known issues

- **>50% GATE BREACH on the DEFAULT reference model (ADVISORY — escalate, do not decide).** A 7-day `paper_real` replay (BTC/5m + ETH/5m, 372 trades), computed with the engine's `DefaultSlippageModel` formula, shows:

  | cell | n | gross paper P&L | modeled slippage | adjusted P&L | per-cell slip frac (/\|gross\|) |
  |---|---|---|---|---|---|
  | BTC/5m | 185 | +$93.18 | $138.33 | -$45.15 | 148% |
  | ETH/5m | 187 | +$90.99 | $139.27 | -$48.29 | 153% |
  | OVERALL | 372 | +$184.17 | $277.60 | **-$93.43** | **150.7%** |

  Modeled slippage EXCEEDS gross paper P&L → adjusted P&L goes NEGATIVE → engine `overall_gate` fraction 150.7% > 50% → BREACH. Per the STOP/FLAG condition this is CATASTROPHIC for LIVE viability IF it holds on the calibrated model. CAVEAT: `DefaultSlippageModel` is an uncalibrated conservative placeholder, so this is NOT a final verdict — it must be re-run on Sub-Lane A's estimator and escalated to WARP🔹CMD.
- Real-data replay was run via Supabase MCP (replicating the engine's exact join + default-model formula in SQL) because the CC env has no `DATABASE_URL`; the script's own `--from-db` path was therefore not exercised end-to-end in CC. A CC/operator `--from-db` run is the confirming follow-up.
- Sub-Lane A wiring is contract-based, not yet integration-tested against the real module (it does not exist on this branch). `resolve_slippage_model` expects a `build_slippage_model()` factory returning a `SlippageModel`-compatible callable; if Sub-Lane A's public API differs, a thin adapter is the follow-up.

## 6. What is next

- WARP🔹CMD reviews the gate-breach finding (§5) and decides escalation. Do NOT decide LIVE viability from this advisory default-model run.
- After Sub-Lane A merges: CMD-gated follow-up to confirm the auto-upgrade (resolve_slippage_model picks up `domain.research.slippage_estimator`), reconcile the factory API if needed, and re-run the gate on the calibrated estimator with a real `--from-db` run.

---

Handoff (NEXT PRIORITY in PROJECT_STATE):
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/slippage-replay-engine.md
Tier: STANDARD
