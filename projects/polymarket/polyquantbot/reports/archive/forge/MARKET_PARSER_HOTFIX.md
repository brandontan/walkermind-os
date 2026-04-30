# MARKET_PARSER_HOTFIX

**Agent:** FORGE-X  
**Date:** 2026-04-03  
**Branch:** feature/forge/market-parser-hotfix  

---

## 1. Root Cause

`generate_signals()` in `core/signal/signal_engine.py` reads two keys from
each market dict:

```python
market_id = str(market.get("market_id", ""))
p_market   = float(market.get("p_market", 0.0))
```

However, `get_active_markets()` returns raw Gamma API dicts where the
equivalent data is stored under **different key names**:

| Needed key | Actual API key(s) |
|---|---|
| `market_id` | `id` or `conditionId` |
| `p_market`  | `outcomePrices[0]` or `prices[0]` |

Because neither key existed in the raw dicts:

- `market_id` defaulted to `""` (empty string)
- `p_market`  defaulted to `0.0`

A `p_market` of `0.0` satisfies `p_market <= 0`, which caused every market to
hit the `invalid_p_market` skip branch — **zero signals were ever generated**.

---

## 2. Raw API Sample (representative shape)

```json
{
  "id": "0xabc123...",
  "conditionId": "0xabc123...",
  "question": "Will X happen?",
  "outcomePrices": ["0.72", "0.28"],
  "tokens": [
    { "outcome": "Yes", "price": "0.72" },
    { "outcome": "No",  "price": "0.28" }
  ],
  "volume": 150000,
  "liquidity": 45000,
  "active": true
}
```

---

## 3. Parser Logic

### New function: `extract_market_data(market: dict)`

Location: `core/market/market_client.py`

```python
def extract_market_data(market: dict) -> dict | None:
    try:
        market_id = market.get("id") or market.get("conditionId")
        prices = market.get("outcomePrices") or market.get("prices")
        if not prices or len(prices) == 0:
            return None
        p_market = float(prices[0])
        if not (0 < p_market < 1):
            return None
        if not market_id:
            return None
        return {"market_id": str(market_id), "p_market": p_market}
    except Exception as exc:
        log.warning("market_parse_error", error=str(exc))
        return None
```

Rules enforced:
- `p_market` must be strictly in `(0, 1)` — rejects `0.0` and `1.0`
- `market_id` must be non-empty
- Any exception is caught and logged; never raises silently

---

## 4. Before vs After

### Before

```
trading_loop_tick
market_feed count=87
signal_debug market_id="" p_market=0.0 ...
signal_skipped reason="invalid_p_market" (× 87)
signals_generated count=0
```

### After

```
trading_loop_tick
market_feed count=87
market_raw_sample data={...}   ← first 3 raw dicts logged
market_valid market_id="0xabc..." p_market=0.72
market_valid market_id="0xdef..." p_market=0.45
...
signal_debug market_id="0xabc..." p_market=0.72 edge=0.031 ...
signal_generated market_id="0xabc..." edge=0.031 ev=0.044
signals_generated count=5
trade_loop_executed market_id="0xabc..." side=YES
```

---

## 5. Sample Valid Market (parsed output)

```json
{
  "market_id": "0xabc123...",
  "p_market": 0.72,
  "conditionId": "0xabc123...",
  "question": "Will X happen?",
  "outcomePrices": ["0.72", "0.28"],
  "volume": 150000,
  "liquidity": 45000
}
```

---

## 6. Files Created / Modified

| File | Change |
|---|---|
| `core/market/market_client.py` | Added `extract_market_data()` function |
| `core/market/__init__.py` | Exported `extract_market_data` |
| `core/pipeline/trading_loop.py` | Raw debug log (first 3 markets); apply `extract_market_data` filter; log valid markets; pass normalised markets to `generate_signals` |
| `reports/forge/MARKET_PARSER_HOTFIX.md` | This report |

---

## 7. What's Working

- `extract_market_data()` safely extracts `market_id` and `p_market` from raw Gamma API dicts
- Invalid markets (missing prices, `p_market` outside `(0,1)`, empty `market_id`) are skipped with no crash
- First 3 raw market dicts are logged per tick for live debugging
- Each valid parsed market is logged as `market_valid`
- Normalised markets are merged with original fields so downstream code retains `bid`/`ask`/`liquidity` etc.
- `generate_signals()` now receives dicts with the correct `market_id` and `p_market` keys

---

## 8. Known Issues

None identified.

---

## 9. What's Next

- Remove the `market_raw_sample` debug log once production data is confirmed stable
- Validate that `liquidity_usd` key is also present in normalised dicts (mapped from `liquidity` field)
