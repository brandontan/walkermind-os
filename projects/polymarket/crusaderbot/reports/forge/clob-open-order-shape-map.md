# WARP•FORGE — clob-open-order-shape-map

Validation Tier: MAJOR (core CLOB integration; dormant — `USE_PYSDK_CLOB` default False)
Claim Level: NARROW INTEGRATION
Validation Target: `PolymarketSdkClient._model_to_dict` / `_order_to_dict` — open-order response-shape mapping so `get_open_orders` never loses the order id/asset regardless of the pysdk model shape.
Not in Scope: order placement (already proven on real broker), funder owner-scoping (PR #1645), GTD/FOK/FAK/market path, LIVE flip, `allow_fills`/`ENABLE_LIVE_TRADING` (stay gated).
Suggested Next Step: re-dispatch `staging-proof-fly.yml` case3 (region nrt, `use_pysdk_clob=true`, `pin_market=false`, `allow_fills=false`, `signature_type=1`) — run #12 — to confirm case3 green; then `all-broker`.

## 1. What was built

Shape-agnostic mapping of the pysdk open-order object in `PolymarketSdkClient`, fixing the final case3 readback failure isolated by the run #11 root-cause diagnostics.

Run #11 (sha `fc6ff3ba`) `-s` diagnostics were decisive:

- `DIAG post_order_resp` → `status:"live"`, `making_amount:"0"`, `taking_amount:"0"`, `trade_ids:[]` → the order **rested, did not fill**. CLOB v2 placement is proven end-to-end (built + signed + posted + ACCEPTED + resting on the real broker).
- `DIAG open_orders_scoped_raw` / `open_orders_unscoped_raw` → **one** order returned (run #10 returned `[]`). The funder owner-scoping fix (PR #1645) is confirmed correct — the order is found under the funder.
- That one order mapped to `{"orderID":null,"order_id":null,"asset_id":null}`. Root cause: `_model_to_dict` reduced the pysdk open-order object to an empty `{}` (no `model_dump`, not a dict, empty `__dict__` — a `__slots__`/attrs/property-based model), so `_order_to_dict` set every id alias to None. `_poll_open_order` matches on `orderID/order_id/id/orderId`, never matched the placed bid, and the precondition assert failed.

The fix makes `_model_to_dict` try, in order: pydantic-v2 `model_dump()` → pydantic-v1/generic `.dict()` → plain dict → dataclass `asdict` → populated `__dict__` → `__slots__` walk over the MRO. `_order_to_dict` then adds a direct `getattr` fallback over candidate id/asset attribute names (covers property/slots models `_model_to_dict` can't enumerate), and logs a one-shot `warning` naming `type(obj).__name__` + public attrs if an id is still not found — so any still-unmapped shape surfaces in ops without another proof cycle.

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged; RISK before EXECUTION preserved).

`get_clob_client()` returns `PolymarketSdkClient` only when `USE_REAL_CLOB` and `USE_PYSDK_CLOB` are both set (default dormant). The `ClobClientProtocol` surface, package CircuitBreaker + RateLimiter, and error taxonomy are unchanged. This lane touches only the response→dict mapping helpers used by `get_open_orders` (and shared by `get_fills`, `get_order`, market-scoped `cancel_all_orders`), so the robustness improvement benefits every list/get path.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/integrations/clob/sdk_client.py` — `_model_to_dict` shape-agnostic (pydantic v1/v2, dict, dataclass, `__dict__`, `__slots__`); `_order_to_dict` getattr id/asset fallback + one-shot no-id warning; `_OID_KEYS`/`_ASSET_KEYS` constants.
- `projects/polymarket/crusaderbot/tests/test_clob_pysdk.py` — `test_get_open_orders_maps_slots_shape` (the run-#11 `__slots__` shape), `test_get_open_orders_maps_property_shape` (property-only/empty `__dict__`).
- `projects/polymarket/crusaderbot/reports/forge/clob-open-order-shape-map.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — 7-section update.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry.

## 4. What is working

- All six model shapes map id/asset correctly, verified in isolation (pydantic v2, pydantic v1 `.dict()`, dataclass, plain dict, `__slots__`, property-only/empty-`__dict__` — the exact run-#11 case).
- `py_compile` clean on both edited files.
- No change to placement, owner-scoping, breaker, limiter, or error mapping.
- Dormant: `USE_PYSDK_CLOB` default False; LIVE path gated.

## 5. Known issues

- Full pytest suite (pydantic + polymarket-client deps) not runnable in this container (deps unavailable / Polymarket geoblocked); validated via isolated shape harness + `py_compile`. Authoritative confirmation is CI (mocked) + the next staging dispatch (real broker).
- `get_fills`/`get_order` against the real pysdk not yet proven live (cases 1/2/4 via `all-broker`); they share the now-hardened `_model_to_dict`, so the same shape defect is pre-empted.

## 6. What is next

- Re-dispatch case3 (run #12) — expect green: order rests, `get_open_orders` now returns the live id, kill-switch cancel-all removes it, post-kill poll empty.
- Then `all-broker` (cases 1–2–4); confirm signature_type proxy inference; scope the GTD/FOK/FAK/market follow-up. case5 already passed. LIVE flip stays owner-gated.
