# Forge Report — close-sweep-pipeline-fix

Branch : WARP/close-sweep-pipeline-fix
Date   : 2026-05-25 04:29

---

## 1. What was built

Four bugs in the Close Sweep / Late Entry V3 entry pipeline were fixed. These
bugs caused the strategy to produce zero fills in production despite correct
deployment (PRs #1325–#1332).

**BUG 1 — CRITICAL (market_id vs conditionId mismatch)**
`_evaluate_market()` set `market_id = m.get("id")` (Gamma's UUID) but the
markets table PK is `conditionId`. `_process_candidate._load_market(cand.market_id)`
keyed on conditionId — using the UUID caused every candidate to be discarded as
`skipped_market_not_synced`. Fix: `market_id = condition_id` (conditionId used
as canonical DB key, with fallback chain conditionId > condition_id > conditionID).

**BUG 2 — CRITICAL (get_live_market_price uses singular conditionId)**
`get_live_market_price()` in `integrations/polymarket.py` used
`?conditionId=` (singular) which Gamma silently ignores — it returns the default
market list (first row = an unrelated market). The same root cause as the
settlement bug fixed in `get_market()` (PR #1326) but never applied to the
price endpoint. TP/SL evaluations and P&L calculations were pricing positions
against wrong markets. Fix: `?condition_ids=` (plural) + validate returned
conditionId matches before caching.

**BUG 3 — HIGH (active flag kills candle markets)**
`if not m.get("active") or m.get("closed")` rejected any market with
`active=False`. Polymarket sets `active=False` on candle markets shortly before
resolution while the CLOB book still has liquidity. Fix: skip the `active` gate
for slugs containing `"updown"` (crypto candle marker); rely on `closed` +
`acceptingOrders` instead.

**BUG 4 — MEDIUM (zero telemetry on rejections)**
Every gate returned `None` silently. With 0 candidates there was no log of which
gate rejected which market. Fix: `_evaluate_market` now returns a
`(candidate, reject_reason)` tuple; `scan()` accumulates per-gate reject counts
and logs a `scan_summary` at INFO; each gate logs slug + values at DEBUG;
`run_close_sweep_fast` logs `close_sweep_fast_tick` at INFO when 0 candidates
are produced.

**Config vars added:** `LATE_ENTRY_MIN_ASK_DIFF`, `LATE_ENTRY_WINDOW_SEC`,
`LATE_ENTRY_FLIP_STOP` allow runtime tuning via `fly secrets set` without a
code deploy.

---

## 2. Current system architecture (relevant slice)

```
close_sweep_fast_scan (every 15s)
  └─ run_close_sweep_fast()
       ├─ get_crypto_window_markets() → Gamma /events
       ├─ _upsert_crypto_window_markets() → DB markets table (key = conditionId)
       └─ LateEntryV3Strategy.scan()
            └─ _evaluate_market()
                 ├─ BUG1 FIX: market_id = conditionId (not Gamma UUID)
                 ├─ BUG3 FIX: active gate skipped for "updown" candle slugs
                 ├─ BUG4 FIX: per-gate debug logs + scan_summary at INFO
                 └─ → SignalCandidate → _process_candidate → paper.execute

exit_watcher (every tick)
  └─ get_live_market_price()
       └─ BUG2 FIX: condition_ids (plural) + conditionId validation before cache
```

---

## 3. Files created / modified

```
projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py  [modified]
projects/polymarket/crusaderbot/integrations/polymarket.py                    [modified]
projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py       [modified]
projects/polymarket/crusaderbot/config.py                                     [modified]
projects/polymarket/crusaderbot/tests/test_late_entry_v3.py                   [modified]
projects/polymarket/crusaderbot/reports/forge/close-sweep-pipeline-fix.md     [created]
projects/polymarket/crusaderbot/state/PROJECT_STATE.md                        [modified]
projects/polymarket/crusaderbot/state/CHANGELOG.md                            [modified]
```

---

## 4. What is working

- `py_compile` clean on all 5 production files
- `_evaluate_market` returns `(candidate, reject_reason)` — scan loop aggregates gate counts
- `scan()` logs `late_entry_v3 scan_summary` at INFO with markets/eligible/candidates/gate_rejects
- Successful candidates log slug, side, fav_price, ask_diff, seconds, size at INFO
- `close_sweep_fast_tick` logged at INFO when 0 candidates (was silent)
- `get_live_market_price` now uses `condition_ids=` + validates returned conditionId
- `active=False` no longer rejects candle (updown) markets
- `market_id = condition_id` — candidates now use the correct DB key
- Config vars (`LATE_ENTRY_MIN_ASK_DIFF`, `LATE_ENTRY_WINDOW_SEC`, `LATE_ENTRY_FLIP_STOP`) read at runtime from `get_settings()`; defaults unchanged (0.05 / 35.0 / 0.48)
- 3 new tests added: `test_market_id_uses_condition_id`, `test_candle_market_active_false_not_skipped`, `test_non_candle_market_active_false_is_skipped`
- Existing tests unaffected (thresholds default to same values)

---

## 5. Known issues

- Live fill confirmation requires Fly.io deploy + observation of candle cycles
- Profitability of late-lean entries remains unvalidated (deferred from WARP-LAF)
- Full pytest not exercised in this container (asyncpg/telegram deps absent)

---

## 6. What is next

- WARP🔹CMD review (STANDARD — no SENTINEL required)
- Fly.io redeploy after merge
- Post-deploy: monitor `late_entry_v3 scan_summary` in Fly logs + check
  `SELECT * FROM positions WHERE strategy_type='late_entry_v3' ORDER BY opened_at DESC LIMIT 10`
- If `low_ask_diff` dominates: `fly secrets set LATE_ENTRY_MIN_ASK_DIFF=0.01`

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : Close Sweep entry pipeline (late_entry_v3 scan → _process_candidate → paper.execute) + exit price source (get_live_market_price)
Not in Scope      : Risk gate logic, settlement math, Telegram UX, WebTrader, live trading guards
Suggested Next    : WARP🔹CMD review + Fly.io redeploy
