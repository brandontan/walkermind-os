# Forge Report — close-sweep-clob-liquidity

Branch : WARP/ONA
Date   : 2026-05-25 05:56

---

## 1. What was built

Fixed a silent gate 11 rejection that blocked every `late_entry_v3` fill even
after WARP-47 (BUG1–4) was deployed.

**Root cause — gate 11 liquidity mismatch**

`domain/risk/gate.py` step 11 enforces:

```python
min_liq = max(profile["min_liquidity"], K.MIN_LIQUIDITY)  # aggressive → 10_000
if ctx.market_liquidity < min_liq:
    return GateResult(False, "insufficient_liquidity", 11)
```

`market_liquidity` in `TradeSignal` is populated from `market.get("liquidity_usdc")`
(the DB-cached value). `_upsert_crypto_window_markets` writes this from Gamma's
`liquidity` field on the `/events?slug=` response. Gamma does not track liquidity
for 5m/15m candle markets — the field is near-zero or absent. Every candidate
therefore arrived at gate 11 with `market_liquidity ≈ 0 < 10_000` and was
rejected silently (no scan_runs row, no Telegram notification).

**Fix**

`_evaluate_market` in `late_entry_v3.py` already fetches both CLOB books to
compute `yes_ask` / `no_ask`. A new `_book_depth_usdc()` helper sums bid-side
depth (price × size) for one book. Combined YES + NO bid depth is stored in
`SignalCandidate.metadata["clob_liquidity"]`.

`_build_trade_signal` in `signal_scan_job.py` now reads `clob_liquidity` from
metadata and uses it as `market_liquidity` when it is positive, falling back to
`market.get("liquidity_usdc")` for all other strategies. No other code path is
affected.

---

## 2. Current system architecture (relevant slice)

```
run_close_sweep_fast (every 15s)
  └─ LateEntryV3Strategy.scan()
       └─ _evaluate_market()
            ├─ get_book(yes_token) + get_book(no_token)   [already fetched]
            ├─ _best_ask(yes_book), _best_ask(no_book)
            ├─ _book_depth_usdc(yes_book) + _book_depth_usdc(no_book)  [NEW]
            └─ SignalCandidate.metadata["clob_liquidity"] = combined depth  [NEW]
  └─ _process_candidate()
       └─ _build_trade_signal()
            └─ market_liquidity = clob_liquidity if > 0 else liquidity_usdc  [NEW]
  └─ TradeEngine.execute()
       └─ gate 11: market_liquidity >= 10_000  ← now uses real CLOB depth
```

---

## 3. Files created / modified

```
projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py  [modified]
projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py       [modified]
projects/polymarket/crusaderbot/reports/forge/close-sweep-clob-liquidity.md   [created]
projects/polymarket/crusaderbot/state/PROJECT_STATE.md                        [modified]
projects/polymarket/crusaderbot/state/CHANGELOG.md                            [modified]
```

---

## 4. What is working

- `_book_depth_usdc()` sums bid price × size; returns 0.0 on any failure
- `clob_liquidity` stored in candidate metadata for every `_evaluate_market` call
- `_build_trade_signal` uses `clob_liquidity` when positive, DB value otherwise
- No change to gate logic, risk constants, or any other strategy
- `py_compile` clean on both modified files
- 21/21 `test_late_entry_v3` pass
- 1753/1753 full suite pass (1 pre-existing skip, 0 failures)

---

## 5. Known issues

- CLOB book depth is a proxy for liquidity, not the official Gamma figure. For
  candle markets it is the only available real-time signal. For non-candle
  markets the DB value is used unchanged.
- Profitability of late-lean entries remains unvalidated (deferred from WARP-LAF).

---

## 6. What is next

- WARP🔹CMD review + Fly.io redeploy
- Post-deploy: monitor `scan_outcome outcome=accepted` in Fly logs and check
  `SELECT * FROM positions WHERE strategy_type='late_entry_v3' ORDER BY opened_at DESC LIMIT 10`
- If fills still zero after one full candle cycle: add `fly secrets set LATE_ENTRY_MIN_ASK_DIFF=0.02`
  and observe one more cycle before lowering further

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : late_entry_v3 → _build_trade_signal → gate 11 liquidity path
Not in Scope      : Risk gate logic changes, settlement, Telegram UX, live trading guards
Suggested Next    : WARP🔹CMD review + Fly.io redeploy
