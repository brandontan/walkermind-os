# SMART STRIKE — spec-vs-reality audit (read-only)

**Role:** WARP•R00T (read-only)
**Linear:** WARP-71
**Branch:** N/A (audit; no code changes, no PR)
**Audit target:** the live `candle_auto` preset wired through `late_entry_v3` + the user-pinned single rules (`close_sweep` / `safe_close` / `flip_hunter`)
**Source of truth (code):** repo at HEAD; not the forge report.
**Verdict at a glance:** SMART STRIKE is **NOT a scoring orchestrator**. It is a fixed-order **claim-first dedup router** over three time-window-disjoint variants of the same `late_entry_v3` engine. Selection is by **rule order + per-rule eligibility gates**, not by a score. Oracle is computed and stamped on candidates but **influences nothing** in selection, gating, or sizing — it is dead-end advisory metadata.

---

## 1. Orchestration — spec vs reality

Operator spec: `market → analyze conditions → score each strategy → pick best → risk-validate → execute`.

| Spec stage | Code location | Match? | Notes |
|---|---|---|---|
| `market` (enumerate candle markets) | `services/signal_scan/signal_scan_job.py:3128` (`_polymarket.get_crypto_window_markets`) + `services/signal_scan/signal_scan_job.py:3134` (`_upsert_crypto_window_markets`) | MATCHES | Per-user candle window pulled in both loops (`run_once` 180s and `run_close_sweep_fast` ~15s). |
| `analyze conditions` (per-market factor calc) | `domain/strategy/strategies/late_entry_v3.py:645` `_evaluate_market` (yes/no books, spread, leg-spread, ask_diff, seconds_left, fav_price) + `domain/strategy/strategies/late_entry_v3.py:155` `_observe_oracle_edge` (advisory) | DIVERGES | "Analyze" exists, but factors are evaluated **per rule**, inside that rule's gate cascade — not as a shared, market-level "conditions snapshot" handed to a scorer. |
| `score each strategy` | **NONE** | **MISSING** | No scoring function. No weights. No best-of comparator. Grep for `score`/`rank` in `signal_scan_job.py` and `late_entry_v3.py` returns zero scoring code (`weight` hit at line 675 is a SQL alias for `capital_allocation_pct`, unrelated). |
| `pick best` | `services/signal_scan/signal_scan_job.py:3566` `_CANDLE_AUTO_RULE_ORDER = ("close_sweep", "safe_close", "flip_hunter")` + `services/signal_scan/signal_scan_job.py:3731-3756` `_scan_late_entry_for_preset` | DIVERGES | Selection is **fixed-precedence dedup by `market_id`**: scan each rule in `_CANDLE_AUTO_RULE_ORDER`; first emitted candidate for a given `market_id` wins (loop: line 3742 `if c.market_id in seen: continue`). Order is hardcoded, NOT condition-driven. The condition→winner outcome the spec describes emerges only because the rules' **entry-window gates are time-disjoint** (`flip_hunter` 60–180s rem, `safe_close` 30–60s rem, `close_sweep` final 35s rem). The router is not making that choice; the per-rule gates are. The only real overlap is ~30–35s where `close_sweep > safe_close` by precedence (see comment `signal_scan_job.py:3561-3565`). |
| `risk-validate` | `services/signal_scan/signal_scan_job.py:2802` `_engine.execute(signal)` → `domain/risk/gate.py:321` `evaluate` (13 gates: caps, kill-switch, pause/auto-trade, role, strategy-availability, daily-loss, drawdown, concurrent, exposure, staleness, dedup, liquidity, edge, market-status + Kelly sizing). Plus pre-engine gates 0a–3f inline in `_process_candidate` (`signal_scan_job.py:2402-2783`: bankroll circuit-breaker, dedup, open-position, TOB-freshness, complete-set-edge, candle-tick-alignment, fill-band, safe-close-direction, robustness, no-live-mark). | MATCHES | Order is correct: candidate emission → pre-gates → `TradeEngine.execute` → 13-step risk gate → execution. |
| `execute` | `domain/risk/gate.py` returns approved `GateResult` → execution proceeds via `TradeEngine`; resume / direct path uses `router_execute` (`signal_scan_job.py:2368`). Final commit through `domain/execution/router.py` (paper/live). | MATCHES | One direct `router_execute` call exists for crash-recovery resume only (`signal_scan_job.py:2367-2400`), gated by `_resume_safety_check` (re-runs the circuit-breaker subset). All normal entries go via `TradeEngine.execute`. |

**Bottom line:** what runs is `enumerate window markets → for each rule in fixed order, evaluate per-market gates → dedup by market_id → for each survivor: pre-gates → 13-gate risk → execute`. The orchestrator the spec describes (scoring + best-pick) does **not** exist. The 30–35s overlap and time-disjoint windows make the precedence dedup *look* like a stage-aware selector, but that mapping is hardcoded order + time-window gates, not factor scoring.

---

## 2. The 3 strategies + AUTO routing + user-pin

| Spec element | Code location | Match? | Notes |
|---|---|---|---|
| `close_sweep` defined | `domain/preset/presets.py:120-131` (Preset), params at `services/signal_scan/signal_scan_job.py:3429-3436` + `_resolve_preset_params close_sweep` branch `signal_scan_job.py:3506-3522` | MATCHES | All three rules route to a single engine: `LateEntryV3Strategy` (`domain/strategy/strategies/late_entry_v3.py:309`). Rules differ only in scan-param bundles (window, fav-price band, underdog_mode, force-exit). |
| `safe_close` defined | `domain/preset/presets.py:132-143`, params `signal_scan_job.py:3437-3444` + `_resolve_preset_params safe_close` `signal_scan_job.py:3523-3531` | MATCHES | |
| `flip_hunter` defined | `domain/preset/presets.py:144-155`, params `signal_scan_job.py:3445-3453` + `_resolve_preset_params flip_hunter` `signal_scan_job.py:3532-3549` (timeframe-aware: 5m vs 15m) | MATCHES | |
| AUTO routes between all 3 | `services/signal_scan/signal_scan_job.py:3731-3756` `_scan_late_entry_for_preset` when `active_preset == "candle_auto"` | DIVERGES from "scoring" wording | Routing is **claim-first by `_CANDLE_AUTO_RULE_ORDER`**, not scored. Sub-rule scan failure isolated (`try/except continue`, line 3738-3740). |
| User pins one rule | `domain/preset/presets.py:108-155` (all four presets `is_activatable`) + Telegram picker `bot/handlers/presets.py` + WebTrader `webtrader/frontend/src/pages/AutoTradePage.tsx` Smart Strike sub-picker | MATCHES | The single-rule presets are first-class and selectable on both surfaces. AUTO is `candle_auto` (the recommended default — `presets.py:213 RECOMMENDED_PRESET`). |
| `near resolve → Close Sweep` example | `signal_scan_job.py:3432` `entry_window_sec=35.0` (final 35s) + dedup precedence `signal_scan_job.py:3566` | MATCHES (by accident of order + gate) | Achieved via fixed precedence + time-disjoint windows, not condition scoring. |
| `calm → Safe Close` example | `signal_scan_job.py:3438` `min_ask_diff=0.01` (low lean acceptable), `entry_window_sec=60.0`, `min_entry_sec=30.0`, `force_exit_at_rem_sec=30.0` | DIVERGES | "Calm" is not measured (no volatility input). The preset just opens earlier in the window with a looser lean threshold; nothing reads market-volatility to route here. |
| `aggressive → Flip Hunter` example | `signal_scan_job.py:3445-3453` `underdog_mode=True`, `fav_price_min=0.10`, `fav_price_max=0.36`, `entry_window_sec=180.0`, `min_entry_sec=60.0`, `force_exit_at_rem_sec=0.0` (hold to settlement) | DIVERGES | "Aggressive" / "momentum" is not measured. Flip Hunter unconditionally enters the cheap side in 60–180s rem when the cheap-side price + ask-diff gates pass; no momentum / repricing signal is computed. |

---

## 3. The 7 factors — used-in-scoring / used-as-gate / computed-but-unused / absent

| Factor | Status | Code location | Notes |
|---|---|---|---|
| **Liquidity** | **gate** | `domain/risk/gate.py:476-483` (step 11, `market_liquidity < min_liq` reject). `domain/strategy/strategies/late_entry_v3.py:777` computes `clob_liquidity = _book_depth_usdc(yes_book) + _book_depth_usdc(no_book)` and stamps it; `_build_trade_signal` (`signal_scan_job.py:1775`) injects it into `market_liquidity` so the gate uses live CLOB depth (Gamma's field is zero for candle markets). | Not scored. Hard pass/fail. User can override floor via `user_min_liquidity` (`gate.py:477`). |
| **Spread** | **gate** | `late_entry_v3.py:806-811` (`MAX_SPREAD=1.05` complete-set sum); per-leg gate `late_entry_v3.py:755-770` (`max_leg_spread`, **close_sweep-only**, no-op for other rules); `_gate_complete_set_edge` (`signal_scan_job.py:2711-2719`); `_gate_tob_freshness` (`signal_scan_job.py:2701-2709`). | Multiple spread-shaped gates. None score. |
| **Volatility** | **computed-but-unused** | `domain/strategy/oracle.py` `sigma_for_asset` consumed at `late_entry_v3.py:201` for `compute_fair_value`; result fed into oracle advisory metadata (`oracle_fair_up`, `oracle_edge_up/down`). | Sigma feeds **only** the advisory observation. Nothing reads the advisory output (see §4). Effectively absent from selection / gates / sizing. |
| **Momentum** | **gate (proxy) / absent (true)** | Proxy: `late_entry_v3.py:795-805` `ask_diff = abs(yes_ask - no_ask) ≥ min_ask_diff` ("late lean"). Flip-stop exit at `FLIP_STOP_PRICE` (`late_entry_v3.py:62`). | The "ask lean" is a static instantaneous threshold, not a momentum signal. No rate-of-change / rolling-history momentum computed (`oracle_trend_align_flag` exists in advisory metadata but `trend` is explicitly noted as not evaluated this chunk — `late_entry_v3.py:208-211`). |
| **Time-to-resolution (TTL)** | **gate** | `late_entry_v3.py:707-720` (`_seconds_to_close` vs `entry_window_sec` upper, `min_entry_sec` lower). Per-rule window is the primary driver of which rule fires (and thus the de-facto "router"). `force_exit_at_rem_sec` (per-rule, stamped to metadata) also feeds the **exit** path via `domain/execution/exit_watcher.py` + `late_entry_v3.evaluate_exit` (`late_entry_v3.py:484-499`). | The factor most resembling the spec's intent: TTL gates per-rule entry windows; the precedence dedup then picks the latest-stage rule on the only real overlap (`close_sweep > safe_close` at ~30–35s). |
| **Orderbook Depth** | **gate** | Same as Liquidity: `clob_liquidity` from book depth feeds gate step 11. Bids/asks (TOB) read at `late_entry_v3._evaluate_market` via `pm.get_book` (`late_entry_v3.py:728-738`); `_gate_tob_freshness` rejects stale TOB. | Depth → liquidity gate. Not separately scored. |
| **Oracle** | **computed-but-unused (advisory-only)** | Producer: `late_entry_v3.py:155-242` `_observe_oracle_edge` (stamps `oracle_edge_status`, `oracle_price`, `oracle_price_to_beat`, `oracle_delta`, `oracle_fair_up`, `oracle_edge_up`, `oracle_edge_down`, `oracle_distance`, `oracle_trend_align_flag`, `oracle_edge_would_pass`). Wired in only via `_build_oracle_edge_cfg` (`signal_scan_job.py:3651-3690`) when `ORACLE_EDGE_GATE_ENABLED` + `ORACLE_ENABLED`. Comment line 233-234: "ADVISORY ONLY — not enforced this chunk". | **See §4 — critical.** |

---

## 4. ORACLE — does it influence anything?

**No.** Oracle output is **producer-only**: computed, logged, stamped to candidate metadata, then dropped.

| Question | Code evidence |
|---|---|
| Where is `would_pass` produced? | `domain/strategy/strategies/late_entry_v3.py:211` `would_pass = dist_ok and edge_ok`; stamped into `SignalCandidate.metadata["oracle_edge_would_pass"]` at line 235. |
| Does anything READ `oracle_edge_would_pass`? | **No production reader.** Grep `oracle_edge_would_pass` returns: producer at `late_entry_v3.py:235`, two tests (`tests/test_oracle_edge_wiring.py:77,95,104`), and state/report mentions. Zero hits anywhere in `services/`, `domain/`, `bot/`, `webtrader/`, `scheduler.py`, `main.py` outside the producer. |
| Does anything READ the other `oracle_*` keys? | Same dead end — grep `oracle_distance|oracle_fair_up|oracle_edge_up|oracle_edge_down|oracle_price_to_beat|oracle_symbol` shows the producer file, tests, and forge/state docs only. **No gate, no sizing, no router branch reads them.** |
| Is oracle referenced in the **scoring** path? | No scoring path exists (§1). Oracle is not in `_CANDLE_AUTO_RULE_ORDER` selection (`signal_scan_job.py:3731-3756`); the AUTO loop does not branch on any oracle field. |
| Is oracle referenced in the **selection** path? | No. `_scan_late_entry_for_preset` (`signal_scan_job.py:3731-3756`) selects strictly by precedence + dedup. The oracle `edge_cfg` is passed to `_scan_one_late_entry` (`signal_scan_job.py:3702`) only so the producer can stamp metadata. |
| Where is `OracleEdgeConfig` constructed? | `signal_scan_job.py:3651-3690` `_build_oracle_edge_cfg` — gated by env (`ORACLE_EDGE_GATE_ENABLED`); fail-soft to `None`. Per-preset distance/edge bands at `signal_scan_job.py:3597-3601` `_CANDLE_PRESET_EDGE` (Kreo-aligned numbers, fed only into the advisory observation). |
| Sentinel confirmation | `reports/sentinel/candle-oracle.md:57-59` explicitly notes: "Grep across services/domain/webtrader/bot/jobs for any consumer of `oracle_edge_would_pass`/`oracle_edge_*` → ONLY a comment in signal_scan_job:3594; NO code gates/branches on it. The advisory observation cannot reject, resize, or…" |

**Implication for WARP-66:** there is **no oracle hook in scoring or selection** to reconcile with — because there is **no scoring**, and the AUTO router is a precedence dedup. The only existing oracle integration point is the advisory `_observe_oracle_edge` stamp inside `_evaluate_market` (`late_entry_v3.py:870-877`). If WARP-66 introduces an oracle-based capital gate, it has a clean insertion point and is **not** in conflict with a parallel path — but it must decide whether to:

1. flip the advisory `oracle_edge_would_pass` into a hard reject inside `_evaluate_market` (kills the candidate before pre-gates), or
2. add a new pre-gate in `_process_candidate` (between `_gate_fill_band` and `_engine.execute`, before risk), or
3. fold an `edge_bps`-derived value into `GateContext.edge_bps` so gate step 12 fires.

All three are clean; none collide with an existing oracle path because none exists outside the producer.

---

## 5. Risk validation — gates, ordering

Confirmed: risk validation sits **AFTER selection, BEFORE execution**. Order at the per-candidate level (`_process_candidate`, `services/signal_scan/signal_scan_job.py:2259`):

| # | Gate | File:line |
|---|---|---|
| 0 | Crash-recovery resume (re-runs CB subset) | `signal_scan_job.py:2288-2400` |
| 0a | Bankroll circuit-breaker | `signal_scan_job.py:2402-2494` |
| 1 | Permanent dedup (`execution_queue`) | `signal_scan_job.py:2496-2507` |
| 1a-2 | Safe-close imbalance override (dark-launched) | `signal_scan_job.py:2509-~2700` |
| 3b-0 | TOB freshness | `signal_scan_job.py:2701-2709` |
| 3b-0a | Complete-set edge | `signal_scan_job.py:2711-2719` |
| 3b-i | Candle tick-alignment | `signal_scan_job.py:2727-2735` |
| 3c | Fill-band re-check | `signal_scan_job.py:2737-2745` |
| 3d | Safe-close direction concentration | `signal_scan_job.py:2747-2755` |
| 3e | Robustness gate (env-flagged) | `signal_scan_job.py:2762-2771` |
| 3f | No live mark → skip | `signal_scan_job.py:2778-2783` |
| 4 | **13-step risk gate (inside `TradeEngine.execute`)** | `domain/risk/gate.py:321-590` |
| 5 | Execute / record in `execution_queue` | `signal_scan_job.py:2819+` |

Of the operator-named gates (spread / liquidity / risk / daily-loss / drawdown):

| Spec gate | Code | Match? |
|---|---|---|
| Spread | `late_entry_v3.py:806` (`MAX_SPREAD=1.05`), `late_entry_v3.py:755-770` (`max_leg_spread` for close_sweep), `_gate_tob_freshness`, `_gate_complete_set_edge` | MATCHES (multiple layered gates) |
| Liquidity | `domain/risk/gate.py:476-483` step 11 | MATCHES |
| Risk (Kelly + per-trade cap) | `gate.py:499-510` (`K.KELLY_FRACTION ≤ 0.25` enforced, `max_pos_size = balance * max_pos_pct * kelly`) | MATCHES (CLAUDE.md hard rule: a=0.25 only) |
| Daily-loss | `gate.py:402-412` step 5 (`effective_daily_loss`: most-restrictive of system floor, profile cap, user override) | MATCHES |
| Drawdown | `gate.py:415-423` step 6 (`_max_drawdown_breached`, halts ≥ MAX_DRAWDOWN_HALT=8% or user cap) + bankroll circuit-breaker `signal_scan_job.py:2456` as a softer first line | MATCHES |
| Kill switch | `gate.py:342-353` step 1 | MATCHES |
| Concurrent / exposure | `gate.py:425-453` steps 7–8 | MATCHES |
| Idempotency / dedup window | `gate.py:464-471` step 10 + `signal_scan_job.py:2496-2507` step 1 | MATCHES |
| Market status / Kelly sizing | `gate.py:494-` step 13 | MATCHES |

Ordering confirmed: **selection (rule precedence dedup) → pre-gates → risk gate (13 steps) → execute**. No risk gate runs before selection. No execution runs before the gate. RISK-before-EXECUTION boundary holds.

---

## 6. WARP-66 integration point

| Question | Answer |
|---|---|
| Where does the gate "flip" for WARP-66? | `_evaluate_market` (`domain/strategy/strategies/late_entry_v3.py:645`) emits the candidate; `signal_scan_job._scan_late_entry_for_preset` (`signal_scan_job.py:3731-3756`) collects + dedups across rules; `_process_candidate` (`signal_scan_job.py:2259`) runs pre-gates → `_engine.execute` (`signal_scan_job.py:2802`) → `domain/risk/gate.evaluate` (`gate.py:321`). |
| Order relative to scoring + risk + execute | There is **no scoring** to insert before. WARP-66 has three viable insertion points: (a) inside `_evaluate_market` (reject before metadata emit), (b) as a new pre-gate inside `_process_candidate` between `_gate_fill_band` and `_engine.execute`, or (c) feeding `GateContext.edge_bps` so step 12 fires. Option (b) keeps "selection → risk → execute" semantics cleanest and is consistent with the existing pre-gate stack. |
| Existing "oracle hook in scoring" to reconcile? | **None.** `_observe_oracle_edge` (`late_entry_v3.py:155`) is the only oracle touchpoint and is producer-only (no consumer in selection or gating). No parallel path exists. WARP-66 should explicitly choose to either (i) start reading `oracle_edge_would_pass` (and remove the "ADVISORY ONLY" comment) or (ii) build its own gate consuming the same `OracleEdgeConfig`. Doing both creates a parallel path and divergence risk. **Pick one.** |
| Capital gate flip risk | The 13-step risk gate already enforces Kelly=0.25 hard cap and full position/exposure/daily-loss/drawdown ceilings. Adding an oracle reject as a pre-gate is additive (deny-only) and cannot enable capital. Promoting the oracle observation in `_evaluate_market` is also deny-only. Either keeps WARP-66 safe-by-construction. |

---

## 7. Spec-vs-reality map (rollup)

| # | Spec element | Code location | Status | Note |
|---|---|---|---|---|
| 1 | "orchestrator over 3 strategies" | `_scan_late_entry_for_preset` `signal_scan_job.py:3731` | DIVERGES | Claim-first dedup by `_CANDLE_AUTO_RULE_ORDER`, not orchestration. |
| 2 | "score each strategy" | — | **MISSING** | No scoring code exists. |
| 3 | "pick best" | `_CANDLE_AUTO_RULE_ORDER` precedence + dedup loop `signal_scan_job.py:3742-3755` | DIVERGES | Fixed precedence (`close_sweep > safe_close > flip_hunter`); first to claim a `market_id` wins. |
| 4 | 3 strategies (close_sweep / safe_close / flip_hunter) | `domain/preset/presets.py:120,132,144` + `LateEntryV3Strategy` `late_entry_v3.py:309` | MATCHES | All three route to one engine; differ only in scan-param bundles. |
| 5 | AUTO uses all 3 | `signal_scan_job.py:3731-3756` | MATCHES (mechanically) | "Uses" by sequential scan + dedup, not by scoring. |
| 6 | User pins one | `domain/preset/presets.py:204-211 VISIBLE_PRESET_ORDER` + `bot/handlers/presets.py` + `webtrader/.../AutoTradePage.tsx` | MATCHES | First-class single-rule selection on both surfaces. |
| 7 | "near resolve → close sweep" | `signal_scan_job.py:3432` `entry_window_sec=35.0` + precedence | MATCHES (emergent) | By window + order, not condition-routing. |
| 8 | "calm → safe close" | `signal_scan_job.py:3437-3444` | DIVERGES | No "calm" measure (no volatility input); just a different time window + looser lean. |
| 9 | "aggressive → flip hunter" | `signal_scan_job.py:3445-3453` | DIVERGES | No "aggressive"/momentum measure; just cheap-side entry in earlier rem window. |
| 10 | Factor: Liquidity | `gate.py:476-483` + `late_entry_v3.py:777` | gate | Hard floor + CLOB depth override. |
| 11 | Factor: Spread | `late_entry_v3.py:806`, `:755-770`, `_gate_tob_freshness`, `_gate_complete_set_edge` | gate | Layered, multiple shapes. |
| 12 | Factor: Volatility | `late_entry_v3.py:201` `sigma_for_asset` | computed-but-unused | Feeds only the dead-end advisory observation. |
| 13 | Factor: Momentum | `late_entry_v3.py:795` `ask_diff ≥ min_ask_diff` proxy; `oracle_trend_align_flag` advisory | gate (proxy) / absent (true) | No rolling momentum / repricing signal. |
| 14 | Factor: TTL | `late_entry_v3.py:707-720` + `force_exit_at_rem_sec` | gate | The **de-facto selection driver** via per-rule windows. |
| 15 | Factor: Orderbook Depth | `late_entry_v3.py:777` + `gate.py:476-483` | gate | Routed into liquidity. |
| 16 | Factor: Oracle | producer `late_entry_v3.py:155-242` only | **computed-but-unused** | No consumer. ADVISORY ONLY by explicit comment. |
| 17 | Risk validation BEFORE execution | `signal_scan_job.py:2802` → `gate.py:321` | MATCHES | 13-step gate inside `TradeEngine.execute`. |
| 18 | Risk validation AFTER selection | `_process_candidate` runs after `_scan_late_entry_for_preset` dedup | MATCHES | Order holds. |

---

## 8. Headline findings — call-outs

1. **SMART STRIKE is not a scoring orchestrator.** It is a precedence-dedup router (`close_sweep > safe_close > flip_hunter`) where the per-rule **TTL window gates** do the actual routing work. The condition→strategy mapping in the spec is **emergent from time-disjoint windows**, not from any factor scoring. If the spec's intent is a real scorer (multi-factor pick best), it has to be **built**; it does not exist.
2. **Oracle is dead-end advisory.** Stamped into candidate metadata; no production consumer (grep-verified). Confirmed by `reports/sentinel/candle-oracle.md:57-59`. Anything in the spec or roadmap that assumes "oracle influences selection" is currently inaccurate.
3. **Volatility is computed (sigma) but only consumed by the oracle advisory.** It does **not** gate, score, size, or route. Treat as absent in operational terms.
4. **Momentum is not measured.** `ask_diff` is an instantaneous lean threshold; there is no rolling momentum / repricing signal.
5. **TTL is the load-bearing factor.** It both gates entry per rule and (via fixed precedence on the only real overlap window) decides which rule wins. WARP-66 should respect this — promoting oracle to a gate must not invert the TTL-driven selection.
6. **Risk-before-execution is intact** (CLAUDE.md hard rule). The 13-step gate runs inside `TradeEngine.execute`; pre-gates layered before it; no execution path bypasses both.
7. **WARP-66 has a clean insertion point.** No existing oracle hook in scoring or selection to reconcile with. Pick **one** integration shape — either (a) flip the existing advisory `oracle_edge_would_pass` into a hard reject inside `_evaluate_market`, or (b) add a new pre-gate in `_process_candidate` — but not both. Do not build a parallel oracle path.
8. **`safe_close` direction-concentration cap is silently bypassed for `candle_auto`** (already flagged in `reports/forge/candle-auto-router.md:98-101`). Out of WARP-66 scope but worth keeping on the risk roadmap.

---

## 9. Validation metadata

- **Validation Tier:** N/A (read-only audit; no runtime change)
- **Claim Level:** N/A
- **Validation Target:** read-only spec-vs-reality map for SMART STRIKE; precondition for WARP-66 design
- **Not in Scope:** code changes, PR, test runs, EV / backtest of the rules, fixing the documented LIVE-only gaps (`live.py` `strategy_metadata` non-persistence; `_gate_safe_close_direction` key on `active_preset`)
- **Suggested Next Step:** WARP🔹CMD decision — (i) accept the precedence-dedup router as the canonical SMART STRIKE shape (and update the spec wording to match), OR (ii) commission a real scoring orchestrator over the 7 factors. Either way, finalize WARP-66's oracle-gate insertion shape (advisory→reject inside `_evaluate_market`, or new pre-gate in `_process_candidate`) before any capital-gate flip.
