# WARP•FORGE — clob-page-flatten

Validation Tier: MAJOR (core CLOB integration; dormant — `USE_PYSDK_CLOB` default False)
Claim Level: NARROW INTEGRATION
Validation Target: `PolymarketSdkClient._collect` — flatten the pysdk `Page` wrapper so list/paginator results yield order/trade ROWS, not page-metadata wrappers.
Not in Scope: order placement (proven), funder owner-scoping (PR #1645), shape-agnostic row mapping (PR #1646), GTD/FOK/FAK/market path, LIVE flip, `allow_fills`/`ENABLE_LIVE_TRADING` (stay gated).
Suggested Next Step: re-dispatch `staging-proof-fly.yml` case3 (run #13, nrt, `use_pysdk_clob=true`, `pin_market=false`, `allow_fills=false`, `signature_type=1`) — expect green; then `all-broker` (cases 1–2–4).

## 1. What was built

`_collect` now flattens the pysdk pagination wrapper. The one-shot no-id warning added in PR #1646 named the exact shape on run #12 (sha `f28723ca`):

```
clob-pysdk: open-order map found no id;
type=Page public_attrs=['has_more', 'items', 'next_cursor', 'total_count']
```

The pysdk's `list_open_orders` / `list_account_trades` async-iterate **`Page`** objects — the order/trade rows live in `Page.items`; `has_more`/`next_cursor`/`total_count` are pagination metadata. `_collect` appended the page wrappers themselves, so every downstream `_order_to_dict` / `_model_to_dict` received a `Page` (no id/asset). This is why run #11 returned one all-null "order" (it was a single `Page`) and run #12 still missed, and it is the same latent defect on `get_fills` and market-scoped `cancel_all_orders` (shared paginator) — i.e. cases 1/2/4 would also have failed readback.

Fix: `_collect` detects a page (an `items` sequence AND ≥1 pagination marker) and `extend`s with `Page.items`; a bare order/trade row (no markers) is appended unchanged, so the path is backward-compatible with any SDK version that yields rows directly. `_page_rows` is the page/row discriminator.

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged; RISK before EXECUTION preserved).

`PolymarketSdkClient` is selected only when `USE_REAL_CLOB` and `USE_PYSDK_CLOB` are both set (default dormant). Three layered fixes now cover the full open-order/fills read path on proxy wallets: owner-scoping (find rows under the funder, #1645) → page flattening (this lane, unwrap the `Page`) → shape-agnostic row mapping (extract id/asset from any row shape, #1646). `ClobClientProtocol` surface, breaker, limiter, error taxonomy unchanged.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/integrations/clob/sdk_client.py` — `_collect` flattens `Page.items`; `_page_rows` discriminator + `_PAGE_MARKERS`.
- `projects/polymarket/crusaderbot/tests/test_clob_pysdk.py` — `test_get_open_orders_flattens_page_wrapper`, `test_get_fills_flattens_page_wrapper`.
- `projects/polymarket/crusaderbot/reports/forge/clob-page-flatten.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — 7-section update.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry.

## 4. What is working

- Page wrapper (object + dict form) flattens to its rows; bare row passes through; empty page → `[]`; markers-required guard prevents misclassifying an order as a page. Verified in isolation + `py_compile` clean.
- Applies uniformly to `get_open_orders`, `get_fills`, and market-scoped `cancel_all_orders`.
- Dormant (`USE_PYSDK_CLOB` default False); LIVE path gated.

## 5. Known issues

- Full pytest suite (pydantic + polymarket-client) not runnable in this container (deps unavailable / geoblocked); validated via isolated harness + `py_compile`. Authoritative confirmation = CI (mocked) + the next staging dispatch (real broker).
- The exact row shape inside `Page.items` is now handled by the shape-agnostic mapper (#1646); if a row shape still misses, the one-shot warning will name it (no blind cycle).

## 6. What is next

- Re-dispatch case3 (run #13) — expect green: order rests → `get_open_orders` flattens the page and maps the live id → precondition passes → kill-switch cancel-all clears it → post-kill poll empty.
- Then `all-broker` (cases 1–2–4); confirm signature_type proxy inference; scope the GTD/FOK/FAK/market follow-up. case5 already passed. LIVE flip stays owner-gated.
