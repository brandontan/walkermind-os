# WARP•R00T — Stop-loss capped to the configured risk profile (paper)

Branch: WARP/ROOT/sl-cap-risk-profile
Trigger: owner — paper portfolio screenshot: two candle trades closed "SL HIT"
at -72.5% and -50.0% while the risk profile SL is set to 20%. "SL melebihi
setting risk profile" (the stop blew past the user's setting).
Date: 2026-06-04 Asia/Jakarta

## 0. Diagnosis (code-evidence)

Screenshot: Bitcoin Up/Down 2:00-2:15PM closed SL HIT -$3.37 (72.5% of a $4.65
stake); Ethereum Up/Down -$2.33 (50.0%). Both PAPER, both 15-min crypto candles.

Single SL producer confirmed: `domain/execution/exit_watcher.evaluate` (it is the
only site that emits `ExitReason.SL_HIT` — `services/trade_engine/engine.py` only
references it in a docstring). The SL branch fired correctly (`ret <= -applied_sl_pct`)
but recorded the exit fill at `cur` — the freshly-fetched live mark — NOT the stop
price. On a fast 15-min candle the mark gaps far past the stop between polls (the
fast candle loop runs every ~5s; `CLOSE_SWEEP_EXIT_INTERVAL`), so by the time the
SL is detected the favored token has already collapsed (≈0.50 → ≈0.14). Paper PnL
is computed straight from that fill (`paper.close_position`:
`ret_pct = (exit_price - entry)/entry`), so a 20% stop realised -72.5%.

Not a resolution: the marks (~0.14 / ~0.25) sit between the `_RESOLUTION_PRICE_EPS`
(0.02) bounds, so they were honestly labelled SL_HIT, not RESOLUTION_LOSS.

Root cause: the configured SL is a RISK PROMISE (max loss), but the realised fill
was the gapped mark, letting a single fast candle blow through the user's risk
profile.

## 1. What was built

`exit_watcher.evaluate` SL branch now bounds the realised loss to the configured
stop, mode-aware and honest:

- PAPER → exit fill capped at the stop-threshold price
  `entry × (1 - applied_sl_pct)` (`exit_fill = max(cur, sl_threshold_price)`; at an
  SL trigger `cur ≤ threshold`, so this fills at the stop). Realised loss ==
  the user's setting, never worse. Standard backtest "stop fills at stop price"
  convention — a modelling choice, not fabricated data.
- LIVE → keeps the real mark `cur` (unchanged). A real SELL must be marketable (a
  limit at the higher stop price would sit unfilled — `live.close_position` posts
  the SELL AT `exit_price`), and fabricating a capped fill would misstate
  real-money PnL. Live slippage is reported honestly.
- RESOLUTION (mark gapped to ~0/1) → real terminal value, an honest ~-100%
  RESOLUTION_LOSS ("you lost the bet"), never capped (unchanged).

TP path is untouched (a TP overshoot is a windfall, not a risk-profile breach).

## 2. Current system architecture (relevant slice)

```
exit_watcher.run_once (30s global + ~5s candle fast loop)
  -> _fetch_live_price (CLOB /midpoint) = cur
  -> evaluate(position, live_price=cur):
       ret = (cur - entry)/entry                 [side-own frame, unchanged]
       SL trip: ret <= -applied_sl_pct
         resolved (cur ~0/1) -> RESOLUTION_LOSS @ cur        (uncapped)
         paper               -> SL_HIT @ max(cur, entry*(1-sl))  (CAP)
         live                -> SL_HIT @ cur                  (honest slippage)
  -> _act_on_decision -> submit_close_with_retry(exit_price=fill)
       paper.close_position: pnl = size * (fill - entry)/entry
```

No change to the risk gate, Kelly, the $10k liquidity floor, poll cadence, the
TP/force/strategy/horizon branches, or `ENABLE_LIVE_TRADING`. The fix touches only
the SL exit-fill price.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/execution/exit_watcher.py
  (SL branch: paper cap at stop threshold; live keeps real mark; resolution uncapped)
- projects/polymarket/crusaderbot/tests/test_exit_watcher.py
  (new paper-cap YES + NO tests; live-no-cap test; run_once SL alert assertion
  updated 0.32→0.36 to the capped fill)
- projects/polymarket/crusaderbot/tests/test_realtime_fill_price.py
  (_StubPosition gains `mode`; SL test rewritten to paper-cap/live-mark semantics;
  source-pin updated to the new SL threshold wiring)

## 4. What is working

- 89 SL/exit/fill/notification tests pass (test_exit_watcher, test_realtime_fill_price,
  test_tpsl_from_profile, test_trade_notifications); broad selection 467 pass.
  ruff + py_compile clean on the changed source.
- New tests prove the invariant: a paper SL that gaps to -72.5% / -60% realises
  exactly -20% (filled at the stop price); live keeps the real -30% mark; the
  None-mark path falls back to the stop threshold; resolution stays uncapped.

## 5. Known issues

- LIVE slippage is intentionally NOT capped (see §1). Bounding live loss to the
  exact stop requires a real stop-limit / faster detection (separate lane); today
  live reports honest fills.
- The 6 unrelated collection failures in the broad run are `ModuleNotFoundError:
  web3` / apscheduler in this dev env (scheduler import) — pre-existing env gaps,
  present on main, not caused by this change. CI has those deps.
- Existing open positions are unaffected (the cap applies at exit-decision time).

## 6. What is next

- WARP•SENTINEL (MAJOR — capital/realised-PnL path) or owner merge → Fly redeploy
  → paper-observe that candle SL closures now realise ≈ the configured SL%.
- Optional follow-up: live stop-limit / tighter candle SL detection so live loss
  also tracks the configured stop.

---

Validation Tier   : MAJOR (execution / realised-PnL / capital path)
Claim Level       : FULL RUNTIME INTEGRATION (changes the SL exit fill + booked paper PnL)
Validation Target : evaluate() SL branch — paper fill capped at entry*(1-sl);
                    live keeps real mark; resolution uncapped; TP unchanged
Not in Scope      : live stop-limit; poll cadence; TP fills; risk gate / Kelly /
                    liquidity floor; resolution labelling
Suggested Next    : WARP•SENTINEL / owner merge → Fly → paper-observe SL == setting
