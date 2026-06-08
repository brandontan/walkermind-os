# WARP-97 — CLOB v2 cutover: py-clob-client-v2 order backend

Role: WARP•R00T
Branch: WARP/clob-v2-cutover
Validation Tier: MAJOR (execution path / order backend)
Claim Level: NARROW INTEGRATION (new backend behind the existing protocol seam, default-OFF; unit-tested; broker proof deferred to the WARP-74 staging harness)
Validation Target: a py-clob-client-v2-backed `ClobClientProtocol` implementation selectable via `USE_CLOB_V2`
Not in Scope: flipping the runtime default to v2 (gated OFF), deleting the legacy `polymarket-client`/`py-clob-client`-v1 paths, live-broker validation, ENABLE_LIVE_TRADING / risk / strategy code
Suggested Next Step: validate `ClobV2Client` against the real broker via the WARP-74 staging harness (`allow_fills=false`); on green, flip `USE_CLOB_V2=1` and retire the hybrid in a follow-up

---

## 1. What was built

Owner directive: install `py-clob-client-v2` + `polymarket-client`, study both,
recommend + set up the best. Both were installed and studied; **`py-clob-client-v2`
(stable 1.0.1) was chosen** and a new `ClobClientProtocol` implementation,
`ClobV2Client`, was built and wired behind a `USE_CLOB_V2` flag (default OFF).

Why v2 over polymarket-client (0.1.0b4): v2 is a **stable 1.x**, a **single
package** (order build + sign + post + cancel + reads + builder/RFQ), builds the
**v2 order struct natively** (`OrderArgsV2`/`SignatureTypeV2` → removes the
`order_version_mismatch` root cause WARP-74 fought), returns **clean dicts** (so
none of the polymarket-client Page-flatten/shape-map/funder-scope workarounds are
needed), supports **all order types** (GTC/GTD/FOK/FAK — the current pysdk path
only did GTC), and has **first-class builder attribution** (`BuilderConfig` +
per-order `builder_code`) matching the CrusaderBot Builder Program the owner set
up. polymarket-client is richer (async, full-platform) but still 0.1 beta and was
exactly the path needing the bolt-ons — too risky for the money path now.

## 2. Current system architecture

```
get_clob_client(settings) -> ClobClientProtocol
  USE_REAL_CLOB=False                      -> MockClobClient        (paper, default)
  USE_REAL_CLOB=True, USE_CLOB_V2=True      -> ClobV2Client   [NEW]  (py-clob-client-v2)
  USE_REAL_CLOB=True, USE_PYSDK_CLOB=True   -> PolymarketSdkClient   (proven, still active default)
  USE_REAL_CLOB=True (else)                 -> ClobAdapter          (legacy v1)
```

`ClobV2Client` (sync SDK wrapped in `asyncio.to_thread`, built once behind a
lock): `signature_type=2` GNOSIS_SAFE + `funder` + optional `BuilderConfig`;
shares the package CircuitBreaker + RateLimiter; maps the v2 exception taxonomy
onto `ClobError`; reuses `_trade_matches_order`; emits the exact dict shape
(`orderID`/`order_id`/`id`/`asset_id` aliases) the lifecycle/reconcile consumers
read. Selection precedence: `USE_CLOB_V2` > `USE_PYSDK_CLOB` > `ClobAdapter`.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/integrations/clob/v2_client.py` — `ClobV2Client`
- `projects/polymarket/crusaderbot/tests/test_clob_v2.py` — 9 tests (protocol surface + dict-shape + error mapping + factory selection)

Modified:
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py` — import/export + `USE_CLOB_V2` factory branch
- `projects/polymarket/crusaderbot/config.py` — `USE_CLOB_V2` (default False) + `POLYMARKET_BUILDER_CODE` / `POLYMARKET_BUILDER_ADDRESS` (env-driven)
- `projects/polymarket/crusaderbot/pyproject.toml` — add `py-clob-client-v2>=1.0.1`
- `state/PROJECT_STATE.md`, `state/CHANGELOG.md`

## 4. What is working

- `ClobV2Client` protocol surface (post/cancel/cancel-all/get_order/get_open_orders/get_fills/aclose): **9/9 unit tests pass** against a fake SDK client (no network), incl. accepted-order normalization, rejection-raises, id/asset aliasing, market-vs-global cancel routing, and 429→RateLimit / 400→APIError mapping.
- Factory returns `ClobV2Client` when `USE_REAL_CLOB`+`USE_CLOB_V2`; **default path byte-unchanged** (Mock in paper; PolymarketSdkClient when `USE_PYSDK_CLOB`).
- Package imports clean; 559 clob/live/execution regression tests pass; ruff clean.
- Builder creds + builder code/address flow from env → `BuilderConfig` (secrets in `.env`/Fly only, never repo).

## 5. Known issues

- **Broker-unvalidated:** the v2 order build/sign/post + readback shapes are proven only against a *fake* client here. Real-broker behavior (the thing WARP-74's staging proof exists for) is NOT yet validated — hence `USE_CLOB_V2` defaults OFF.
- **GTD unsupported** in `ClobV2Client.post_order` (needs an explicit expiration the protocol doesn't carry) — raises `ClobConfigError`; GTC/FOK/FAK supported. Follow-up.
- The legacy `polymarket-client` + `py-clob-client` v1 + the orphaned dead path in `integrations/polymarket.py` are **retained**, not deleted — removal is the post-staging-proof retirement lane.

## 6. What is next

1. Run the WARP-74 staging harness (5 reconcile cases, `allow_fills=false`) against `USE_CLOB_V2=1` from a Polymarket-permitted egress; confirm build+sign+POST+accept + open-order/fill readback.
2. On green: set `USE_CLOB_V2=1` (real path cutover) — live trading still independently gated by `ENABLE_LIVE_TRADING`.
3. Retirement lane: delete `sdk_client.py` + `adapter.py` v1 order-building + the orphaned `polymarket.py` legacy CLOB path, drop `polymarket-client` + `py-clob-client` from pyproject, simplify the proxy-read workarounds.

Operator env (Fly secrets, never repo): `POLYMARKET_BUILDER_API_KEY/SECRET/PASSPHRASE`, `POLYMARKET_BUILDER_CODE` (`0xa76bf0…2fbebd`), `POLYMARKET_BUILDER_ADDRESS` (`0xe82c…441e`), and the existing `POLYMARKET_PRIVATE_KEY` / `POLYMARKET_FUNDER_ADDRESS`.

Validation Handoff (NEXT PRIORITY):
```
WARP🔹CMD: validate ClobV2Client via the WARP-74 staging harness (allow_fills=false)
before flipping USE_CLOB_V2=1. Source: reports/forge/clob-v2-cutover.md  Tier: MAJOR
```
