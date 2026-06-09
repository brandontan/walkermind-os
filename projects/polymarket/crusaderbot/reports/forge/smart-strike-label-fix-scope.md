# WARP-78 — realized-EV label fix: scoping design (build-ready)

- Role: WARP•R00T
- Validation Tier: MINOR (scoping/design doc — no code change)
- Claim Level: FOUNDATION
- Purpose: design the Phase-0 prerequisite — fix the biased `open_to_close` label —
  so a Phase-2 EV-comparator trains on a label that reflects what each rule actually
  realizes. Build is the immediate follow-on lane.
- Branch: `WARP/root-label-fix-scope`

---

## 1. Problem (from Phase 0 diagnosis, #1654)

`factor_vectors` settles ONE realized label per candle —
`realized_outcome / realized_delta` with `outcome_source='open_to_close'` — and the
trainer + A/B apply it to **all three** rules. But the rules do not share a horizon:

| Rule | Real exit (from `exit_watcher` tests) | open→close label correct? |
|---|---|---|
| `flip_hunter` (Mode A) | **holds to settlement** | ✅ exact |
| `close_sweep` | force-exit at rem ≤ **~8s** | ≈ yes (8s ≈ close) |
| `safe_close` | force-exit at rem ≤ **~30s** | ❌ ~30s early |

So the label is **biased mainly against `safe_close`** (judged 30s late) and is a
structural reason `close_sweep ≡ safe_close` in the data: with one open→close label
the two favorite rules get identical win/EV labels, even though their exits differ.
A horizon-aware label both (a) prices each rule at its real exit and (b) **breaks the
degeneracy** (close-8s vs close-30s give close_sweep and safe_close distinct labels).

Note the refinement vs the Phase-0 framing: the bias is **smaller than "all favorite
rules"** — close_sweep ≈ close, flip_hunter = close, only safe_close is materially
early. The fix is still worth doing (it de-degenerates the rules and de-biases
safe_close), but it is a correctness refinement, not a regime change.

## 2. Design (recommended — Option A: multi-horizon underlying labels)

Keep the existing open→close label; **add** the underlying price/outcome at each
favorite rule's force-exit horizon, computed at settlement from the SAME oracle
price ring (`oracle.price_at(symbol, epoch)`) the current backfill already uses.

- New columns on `factor_vectors` (additive, nullable; migration 085):
  - `realized_close_sweep_outcome` / `_delta` — underlying at `close_epoch − CLOSE_SWEEP_EXIT_LEAD_SEC` (~8s)
  - `realized_safe_close_outcome` / `_delta` — underlying at `close_epoch − SAFE_CLOSE_EXIT_LEAD_SEC` (~30s)
  - `flip_hunter` uses the existing open→close label (hold-to-settlement) — no new column.
  - (Equivalent compact alternative: store `price_at_close_minus_8s` + `price_at_close_minus_30s` and derive outcomes downstream. Pick during build.)
- `backfill_factor_settlement` computes these alongside the open→close label (one
  extra `price_at` per horizon; rows already gate on the ring window).
- The trainer / A/B (`scorer_trainer.rule_won` / `scorer_ab`) select the
  **rule-appropriate** label: favorite rules → their horizon outcome; flip_hunter →
  open→close. This is the EV label Phase 2 trains on.

Config (single source of truth — mirror the exit watcher, do NOT hardcode a second
copy): `CLOSE_SWEEP_EXIT_LEAD_SEC` and `SAFE_CLOSE_EXIT_LEAD_SEC` derived from the
exit-watcher thresholds (close_sweep ~8s, safe_close ~30s) — confirm exact values
against `exit_watcher.py` at build time.

### Why not Option B (true binary-market exit price)
The *most* correct label is the binary's **market mid** at the force-exit instant
(realized PnL of a sell = `exit_mid − entry_price`, not a binary 0/1). But the
binary mid history is only in the in-process `MomentumTracker` (recent window, not
persisted), so it is not reconstructable at settlement. Option A's
**underlying-direction-at-horizon** is the faithful, computable proxy (same basis
the market resolves on) and is a strict improvement over open→close. Option B is a
later upgrade if/when binary-mid history is persisted.

## 3. Scope / safety

- Additive + SHADOW: new nullable columns, computed in the existing settlement
  backfill; no selection/sizing/gate/runtime change. `SCORER_ACTIVE` stays False.
- Provenance-aware: the EV evaluation should filter to `data_source='paper_real'`
  rows (post-cutover, real-CLOB) once enough accrue — ties to WARP-77 Phase 1.4/1.2.
- Idempotent migration (085) + rollback (non-auto-run subdir), per the 083/084 pattern.

## 4. Acceptance (for the build lane)

- Every settled row gets the favorite-horizon labels populated where the oracle ring
  has the horizon tick (NULL when aged out — honest, like the existing open→close).
- `close_sweep` and `safe_close` labels are **distinct** on rows where the underlying
  moved between close-30s and close-8s (degeneracy broken).
- Trainer/A/B consume the rule-appropriate label; re-run the EV A/B on `paper_real`
  rows and report whether the favorite/underdog EV picture changes vs the open→close
  read. Gate any cutover on a significance test (per Phase 0 §6).

## 5. Risks

- **Horizon accuracy:** force-exit fires at the first scan tick after the rem
  threshold, so the real exit is `threshold + up-to-one-scan-interval` early. Use the
  threshold as the nominal lead and document the ≤1-tick slack; it does not bias
  direction.
- **Ring coverage:** close-30s/close-8s ticks must be in the oracle ring at
  settlement (they are well within the 30-min window for 5m/15m candles).
- **Small effect size:** because close_sweep≈close, the biggest practical change is
  safe_close + the de-degeneration. Manage expectations — this de-biases the label,
  it does not manufacture an edge.

## 6. Recommendation → CMD

Approve the Option-A build as the next WARP-78 lane (`WARP/root-realized-ev-label`):
migration 085 + horizon labels in the settlement backfill + trainer/A/B consumption
+ tests, all additive/shadow. Then re-run the EV A/B on `paper_real` rows as the
input to the Phase-2 EV-comparator design. This sequences correctly: **label fixed →
Volatility/Momentum real (done) → EV-comparator (Phase 2)**.

- Suggested Next Step: CMD greenlight → build `WARP/root-realized-ev-label` (Option A).
