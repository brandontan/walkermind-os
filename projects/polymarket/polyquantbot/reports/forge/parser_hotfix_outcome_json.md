# parser_hotfix_outcome_json

**Date:** 2026-04-03  
**Branch:** feature/forge/parser-hotfix-outcome-json  
**Status:** COMPLETE ✅

---

## 1. What Was Built

Fixed market parsing failure caused by the Gamma API returning
`outcomePrices`, `outcomes`, and `clobTokenIds` as **JSON-encoded strings**
(e.g. `"[\"0.545\", \"0.455\"]"`) rather than native Python lists.

The original `extract_market_data` called `float(prices[0])` where `prices[0]`
was the literal character `[`, causing:

```
could not convert string to float: '['
```

This made every market fail validation, producing `no_valid_markets` warnings
and zero signals on every tick.

---

## 2. Current System Architecture (relevant path)

```
Gamma API (raw JSON)
        │
        ▼
get_active_markets()            core/market/market_client.py
        │  list[dict] — outcomePrices may be JSON-encoded strings
        ▼
ingest_markets()                core/market/ingest.py
        │  applies parse_market() to each market
        ▼
parse_market()                  core/market/parser.py
        │  uses safe_json_load() for string → list deserialization
        │  validates prices / outcomes / token_ids
        │  returns: market_id, p_market, prices[], outcomes[], token_ids[]
        ▼
trading_loop (normalised_markets)
```

---

## 3. Files Created / Modified

| File | Action | Description |
|------|--------|-------------|
| `core/utils/json_safe.py` | **Created** | `safe_json_load()` — deserialises JSON-encoded strings; handles None / malformed / already-parsed values |
| `core/utils/__init__.py` | **Created** | Package init; exports `safe_json_load` |
| `core/market/parser.py` | **Created** | `parse_market()` — full field extraction with JSON-string support; validates all edge cases |
| `core/market/ingest.py` | **Created** | `ingest_markets()` — batch parser; logs `markets_skipped_invalid`; never crashes |
| `core/logging/logger.py` | **Created** | `log_invalid_market()`, `log_market_parse_warning()` — structured JSON log helpers |
| `core/logging/__init__.py` | **Created** | Package init; exports log helpers |
| `core/market/market_client.py` | **Modified** | `extract_market_data()` updated to use `safe_json_load`; imports from `core.utils.json_safe` |
| `core/market/__init__.py` | **Modified** | Exports `parse_market`, `ingest_markets` in addition to existing symbols |
| `core/pipeline/trading_loop.py` | **Modified** | Ingestion loop replaced with `ingest_markets()` call; keeps `extract_market_data` import for backward compat |
| `tests/test_parser_hotfix_outcome_json.py` | **Created** | 21 tests (PH-01–PH-21); 21/21 pass |

---

## 4. What's Working

- **`safe_json_load`**: Handles all input types (JSON string, native list, None, malformed, int, dict)
- **`parse_market`**: Correctly parses the Gamma API's JSON-encoded string fields
- **`extract_market_data`**: No longer crashes on JSON-encoded `outcomePrices`
- **`ingest_markets`**: Applied in `trading_loop`; logs skipped markets as warnings
- **`trading_loop`**: Uses `ingest_markets()` instead of manual loop over `extract_market_data`
- **21 tests** covering all edge cases: all pass

---

## 5. Sample Payloads

### Input (raw Gamma API — JSON-encoded strings)
```json
{
  "id": "0xabc123...",
  "outcomePrices": "[\"0.545\", \"0.455\"]",
  "outcomes": "[\"Yes\", \"No\"]",
  "clobTokenIds": "[\"id1\", \"id2\"]"
}
```

### Output (parsed)
```json
{
  "market_id": "0xabc123...",
  "p_market": 0.545,
  "prices": [0.545, 0.455],
  "outcomes": ["Yes", "No"],
  "token_ids": ["id1", "id2"]
}
```

---

## 6. Known Issues

None introduced by this fix.

---

## 7. What's Next

- Monitor signal generation rate in paper trading to confirm `no_valid_markets` warnings are gone
- Remove `market_raw_sample` debug log once production data structure is confirmed stable
- Wire `outcomes` and `token_ids` fields into signal engine if needed for position labelling
