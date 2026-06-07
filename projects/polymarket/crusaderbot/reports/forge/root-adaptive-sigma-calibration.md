# WARP•R00T FORGE REPORT — root-adaptive-sigma-calibration (WARP-70)

Branch: `WARP/root-adaptive-sigma-calibration`
Role: WARP•R00T (owner greenlit 2026-06-08 — "bangun sekarang, shadow-first")
Validation Tier: **STANDARD** (shadow/advisory; NO capital path, NO gate change)
Claim Level: FOUNDATION
Validation Target: An online per-(asset,TF) sigma calibrator that consumes the full candle-observation stream, is bounded/smoothed/cold-start-safe, and a shadow runner proving adaptive-vs-static calibration — with ZERO runtime/gate effect.
Not in Scope: wiring adaptive sigma into the live oracle gate (deferred to the future WARP-66 capital-path lane); adapting the edge-threshold cutoff; positions-table input (forbidden by design).
Suggested Next Step: run the shadow runner on the deploy env to accrue the static-vs-adaptive log; when it converges and beats static, a separate lane swaps the oracle sigma source (static→adaptive) with zero gate-logic change.

---

## 1. What was built

WARP-70 — adaptive **online** sigma calibration, shadow-first. The oracle
fair-value model (`oracle/fair_value.py`) prices candles with a PER ASSET static
`sigma` per sqrt-second; a static sigma goes stale as realized vol shifts regime.
This builds an online estimator that tracks realized vol from the candle stream,
proven in shadow before it ever touches capital.

- **`domain/research/sigma_calibrator.py`** (pure, no I/O):
  - `SigmaCalibrator` — per-`(asset, timeframe)` EWMA of realized variance-per-second
    (`r²/T` from each settled candle's open→close return), `sigma_adaptive = sqrt(EWMA)`.
  - Safety invariants baked in: **bounded** (clamped to `[0.33×, 3.0×]` the per-asset
    prior — an outlier can't swing the gate), **smoothed** (slow EWMA `alpha=0.05`),
    **cold-start** (returns the static prior until `≥ min_samples=30` per cell),
    **observable** (`observe()` returns a `SigmaUpdate` audit record: sample, before/
    after sigma, n, using_prior).
  - `gaussian_nll()` — the calibration metric (Gaussian negative log-likelihood of the
    realized return under `N(0,(σ√T)²)`); lower = better-calibrated sigma.
- **`scripts/sigma_calibration_shadow.py`** (read-only shadow runner):
  - Replays settled `factor_vectors` rows (the full candle stream — EVERY candle,
    traded or not; NEVER the positions table) chronologically through the calibrator,
    **predict-THEN-update** (the adaptive NLL for a candle uses the sigma held BEFORE
    that candle — honest out-of-sample), and reports per-cell + overall
    adaptive-vs-static avg NLL + the converged adaptive sigma.
  - `--data-source paper_real` (default), `--alpha`, `--min-samples`. Writes nothing,
    gates nothing.

### Selection-bias guard (the non-negotiable constraint)
The calibrator trains on `factor_vectors` (a row per observed candle, independent of
execution), NOT `positions`. Training on only the bot's executed candles would be
selection-biased (gate tightens → sample skews → sigma drifts → self-poisoning).
This source is fully decoupled from the trade/gate decision.

## 2. Current system architecture

Additive + dormant. Nothing in the runtime imports the calibrator yet; the oracle
gate still reads the static `DEFAULT_SIGMA_PER_SQRT_SEC`. The shadow runner is a
standalone CLI. No config flag was added (the runner is CLI-parameterised) — the
runtime `ADAPTIVE_SIGMA_ENABLED` toggle belongs to the future lane that actually
swaps the oracle sigma source, so no dead config ships here.

## 3. Real-data signal (shadow, paper_real, computed via SQL)

The static priors already over-estimate realized vol in the current regime — the
exact staleness WARP-70 exists to fix (both well inside the adaptive band):

| cell | static prior σ | realized implied σ | n | drift |
|---|---|---|---|---|
| btc/5m | 0.00010 | 0.00008369 | 249 | prior ~19% high |
| eth/5m | 0.00013 | 0.00011571 | 245 | prior ~12% high |

(15m/SOL paper_real still thin — 11–14 rows — so they stay on the cold-start prior
until they accrue ≥30.)

## 4. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/research/sigma_calibrator.py` (new)
- `projects/polymarket/crusaderbot/scripts/sigma_calibration_shadow.py` (new)
- `projects/polymarket/crusaderbot/tests/test_sigma_calibrator.py` (new)
- state: PROJECT_STATE.md, CHANGELOG.md

## 5. What is working

- 11 hermetic tests pass (variance/NLL math, cold-start, hard band clamp, EWMA
  smoothing-vs-outlier, audit record, degenerate skips, constructor validation,
  and an end-to-end shadow eval where adaptive beats static when vol diverges).
- ruff + py_compile clean.
- Shadow runner cannot execute from CC (no DATABASE_URL); runs on the deploy env.
  Real-data staleness above was derived via the management SQL path.

## 6. Known issues

- Shadow numbers (adaptive-vs-static NLL) accrue on the deploy env — not yet run live.
- 15m/SOL cells are below cold-start threshold on paper_real.
- The live static→adaptive swap is intentionally a separate, gated lane (shadow-first).

## 7. What is next

Run `python -m crusaderbot.scripts.sigma_calibration_shadow` on deploy to log the
adaptive-vs-static comparison over time; once adaptive converges and scores lower
NLL, a follow-up lane points the oracle sigma source at the calibrator (zero
gate-logic change). Keep the edge-threshold cutoff static (riskiest piece, deferred).
