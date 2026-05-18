# WARP•FORGE Report — crusaderbot-price-fetch-fix

**Branch:** WARP/CRUSADERBOT-PRICE-FETCH-FIX
**Date:** 2026-05-17 18:30 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `integrations/polymarket.get_live_market_price()`
**Not in Scope:** Any other function, live trading path, ENABLE_LIVE_TRADING guard

---

## 1. What was built

Fixed `get_live_market_price()` in `integrations/polymarket.py`.

Root cause: the function called `GET /markets/{conditionId}` as a URL path segment.
Gamma API returns `422 Unprocessable Entity` for hex conditionIds passed as path segments.

Fix applied:
- Changed Gamma fetch to `GET /markets?conditionId={market_id}` (query param form).
- Response is a list; function now extracts `markets[0]` and caches that dict.
- Added CLOB `/price?token_id={tokenId}&side=buy` as primary price source (live order-book, more accurate for TP/SL).
- Gamma `outcomePrices` retained as fallback when CLOB is unavailable or tokenId absent.

---

## 2. Current system architecture

Price resolution order for `get_live_market_price(market_id, side)`:

```
1. Cache hit (lp:{market_id}) → market_data dict
   OR
   Gamma GET /markets?conditionId={market_id} → market_data = response[0]
   → set_cache(lp:{market_id}, market_data, ttl=30)

2. Extract token_id from market_data["tokens"][0 if YES else 1]

3. If token_id present:
   CLOB GET /price?token_id={token_id}&side=buy → return price if valid

4. Fallback:
   market_data["outcomePrices"][0 if YES else 1] → return price if valid

5. Any step fails → return None (exit_watcher falls back to entry_price)
```

Cache key `lp:{market_id}` is shared across sides — one Gamma HTTP round-trip per market per 30 s tick regardless of position count.

---

## 3. Files created / modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/integrations/polymarket.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/crusaderbot-price-fetch-fix.md` |
| Updated  | `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` |
| Updated  | `projects/polymarket/crusaderbot/state/CHANGELOG.md` |

---

## 4. What is working

- `GET /markets?conditionId=` resolves the 422 — Gamma returns a list with the matching market dict.
- CLOB `/price` provides live order-book mid-price for TP/SL accuracy.
- Fallback to Gamma `outcomePrices` preserved — no regression for markets without CLOB liquidity.
- Cache structure unchanged (market dict, TTL 30 s) — `exit_watcher` call path unaffected.
- `None` return on any failure path preserved — `exit_watcher` fallback to `entry_price` logic unchanged.
- `ENABLE_LIVE_TRADING` guard not touched.

---

## 5. Known issues

- `get_market()` (line 81) still uses `GAMMA/markets/{market_id}` path-segment form — that function is called with slugs or IDs in a different code path and is out of scope for this fix.
- CLOB `/price` returns `side=buy` price; for NO-side positions this is the buy price of the NO token, which is `1 - YES_buy`. This is consistent with Gamma `outcomePrices[1]` and correct for TP/SL purposes.

---

## 6. What is next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/crusaderbot-price-fetch-fix.md`
Tier: STANDARD

Suggested next step: deploy and confirm `get_live_market_price` no longer produces 422 log lines in Fly.io production logs.
