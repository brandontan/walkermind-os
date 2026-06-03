# WARP•FORGE — playbook-sharp-money (WARP-53 Phase-2b)

Role: WARP•FORGE (under the WARP•R00T PLAYBOOK epic, WARP-53)
Validation Tier: **MAJOR** (PLAYBOOK strategy/runtime — sports trading signal feeding the risk gate)
Claim Level: **NARROW INTEGRATION** (paper-only; gated by `PLAYBOOK_STRATEGY_ENABLED`)
Validation Target: the native Sharp Money signal — DB-backed sharp-wallet flow source +
activated `SharpMoneyModule` + strategy wiring — emits correct claims into the **unchanged**
risk gate / execution path.
Not in Scope: risk gate, execution router, Kelly/position caps, `ENABLE_LIVE_TRADING`
(all untouched); external feeds (Injury/Public Fade), backtest, Monte-Carlo, WebSocket
(later phases); LIVE trading (paper only, owner-gated).
Suggested Next Step: WARP•SENTINEL MAJOR validation before merge.

---

## 1. What was built

WARP-53 Phase-2b — promotes **Sharp Money** from a Phase-1 no-claim stub to a live
**native** module, per the blueprint (§2.2 / Phase-2b): "on-chain accumulation; no
external dependency, reusing the copy-trade chain monitor."

The signal formula (`signals.sharp_money_reading`) already existed; this lane wired its
data source and activated the module:

- **Native sharp-flow source** (`domain/playbook/sharp_flow.py`, NEW) — `fetch_sharp_flows`
  is a single batched, DB-backed read (no new scan-loop network calls): top-tier sharp
  wallets from `leaderboard_stats` (`win_rate >= 0.65 AND total_pnl > 0`) ⨝ their recent
  trades in `heisenberg_realtime_trades` over a 24h lookback, aggregated per market to
  *signed* USDC (YES/buy/long = +size_usdc, NO/sell/short = −size_usdc) and total flow.
  Fail-soft: any error → `{}`, scan loop never breaks.
- **`SharpMoneyModule.evaluate`** (`domain/playbook/modules.py`) — claims when
  `seconds_to_event > 24h` (the *opposite* window to Closing Edge, so the two never
  compete on one market) AND sharp flow ≥ `$500` floor AND sharp-imbalance confidence
  ≥ `0.20`. Side = sign of the imbalance; confidence blends the sharp reading with the
  module's weighted feed score; carries TP/SL + observability metadata. Added
  `sharp_signed_usdc` / `sharp_total_flow_usdc` fields to `MarketSnapshot` (default 0.0 —
  keeps `evaluate_snapshot` pure and Phase-1 callers/tests unchanged).
- **Strategy wiring** (`domain/strategy/strategies/playbook.py`) — `_fetch_sports_snapshots`
  batch-fetches sharp flows for the scan's condition_ids and attaches them via
  `dataclasses.replace`; `evaluate_snapshot` feeds them into `compute_signal_bundle`.

Router precedence was already correct (`sharp_money` ranked ahead of `closing_edge`); no
router change needed — activating `evaluate` is sufficient.

## 2. Current system architecture

No architectural change to the pipeline. PLAYBOOK still routes
`Market → Quality → Signals → Router → SignalCandidate → (unchanged) risk gate → execution`.
Phase-2b only makes the existing `sharp_money` feed non-zero (one batched DB read in the
async snapshot assembly) and lets the already-registered `SharpMoneyModule` claim. Risk,
execution, Kelly, and the live-trading guard are untouched.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/playbook/sharp_flow.py` — NEW, DB-backed source
- `projects/polymarket/crusaderbot/domain/playbook/modules.py` — `SharpMoneyModule.evaluate`
  + tunables + `MarketSnapshot` sharp-flow fields
- `projects/polymarket/crusaderbot/domain/playbook/__init__.py` — docstring (DB-read note)
- `projects/polymarket/crusaderbot/domain/strategy/strategies/playbook.py` — flow fetch + wiring
- `projects/polymarket/crusaderbot/tests/test_playbook_sharp_money.py` — NEW (14 tests)
- `projects/polymarket/crusaderbot/reports/forge/playbook-sharp-money.md` — this report
- State: `state/PROJECT_STATE.md` · `state/WORKTODO.md` · `state/CHANGELOG.md`

## 4. What is working

- **127 tests pass** (14 new Sharp Money + 31 existing PLAYBOOK engine + 82 signal-scan).
  `ruff check` clean; `py_compile` clean; import smoke confirms router order
  `(injury_alpha, sharp_money, closing_edge, public_fade)`.
- Module logic pinned: YES/NO from imbalance sign; no-claim on TTL inside 24h, flow below
  the $500 floor, confidence below 0.20, and zero default flow (Phase-1 backward compat).
- Router pinned: routes `sharp_money` far from the event with strong sharp flow; Closing
  Edge still claims near the event and abstains far from it (mutually exclusive windows).
- Source pinned: aggregation, batched `ANY($1)` query, `leaderboard_stats` + `win_rate`
  top-tier scoping, fail-soft on error, zero-total skip.
- **Codex P1 fixed:** the snapshot window only covered ≤2h (Closing Edge), so a TTL>24h
  module could never see a market — Sharp Money was DOA in the live path. Added a Sharp
  Money **far band** (24h–72h) to the shared `select_sports_markets_in_window` (so those
  markets are also upserted → candidates resolve), **flow-gated before any orderbook
  fetch** (one cheap batched DB query; only far markets with real sharp flow get book
  reads, capped at 20) so scan-loop cost stays bounded. Near band keeps its 2h cap / 40.
  +2 window tests (far band included, beyond-72h excluded).
- **Codex P2 fixed:** `_build_trade_signal` only applies per-module TP/SL via
  `applied_tp_pct` / `applied_sl_pct` (else the user's profile defaults), which PLAYBOOK
  never stamped — so the module envelope (Sharp 30/15, Closing 25/12) was silently
  replaced by generic TP/SL. `evaluate_snapshot` now stamps those keys from the winning
  module (mirrors the candle_auto router); also repairs the latent Closing Edge gap.
  +2 tests (sharp 30/15, closing 25/12).
- **Codex P1 (signed-flow direction) fixed:** the stored `side` column is
  `side or direction or outcome` upstream — ambiguous — so classifying a `BUY` (of the
  NO token) as YES-accumulation could **flip the emitted trade direction**. Replaced the
  in-SQL sign with a unit-tested Python `yes_accumulation_signed(outcome, action, …)` =
  outcome_sign × action_sign (outcome from `raw->>'outcome'`, as the copy-trade path
  relies on); ambiguous rows count toward *total* magnitude only, never the signed sum,
  so a directionally-unknown book can never flip the side. +9 direction/aggregation tests.

## 5. Known issues

- Signed flow derives direction from `raw->>'outcome'` × buy/sell action (Codex P1 fix),
  the same `outcome` field the copy-trade path relies on. Rows missing a determinable
  outcome+action count toward total magnitude only, so the signal is conservatively
  dampened rather than mis-signed; the V2 backtester can recalibrate the tunables.
- Tunables (`win_rate ≥ 0.65`, 24h lookback, $500 floor, 0.20 confidence) are first-pass,
  blueprint-aligned, and flagged for backtest calibration (Phase-2c).
- Live efficacy depends on `leaderboard_stats` + `heisenberg_realtime_trades` being populated
  (copy-trade sync running) — when empty, Sharp Money simply abstains (Closing Edge unaffected).
- `graphify update` not run — the `graphify` CLI is unavailable in this container.

## 6. What is next

- WARP•SENTINEL MAJOR validation → merge (WARP•FORGE does not merge) → Fly redeploy.
- Phase-2c backtest framework to calibrate the Sharp Money tunables and prove +EV.

---

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION (paper-only, `PLAYBOOK_STRATEGY_ENABLED`-gated)
- Validation Target: native Sharp Money source + module + strategy wiring
- Not in Scope: risk/execution/Kelly/live-guard, external feeds, backtest, LIVE
- Suggested Next Step: WARP•SENTINEL MAJOR validation before merge
