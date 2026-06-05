# WARP-74 CLOB v2 — staging-proof outcome + error-mapping hardening

Validation Tier: MAJOR (CLOB execution backend — dormant under `USE_PYSDK_CLOB=False`)
Claim Level: NARROW INTEGRATION (live CLOB v2 order build/sign/POST proven against the real broker; full 5-case green still gated on fresh staging market coordinates)
Validation Target: the live staging-proof dispatch (case3, nrt, `USE_PYSDK_CLOB=1`) + the `RequestRejectedError` → `ClobError` status bucketing in `PolymarketSdkClient._map_error`.
Not in Scope: refreshing the `STAGING_TOKEN_ID`/`STAGING_MARKET_ID` repo secrets (owner-held); GTD/FOK/FAK/market paths; flipping the prod default backend; `ENABLE_LIVE_TRADING`/`allow_fills` (stay gated).
Suggested Next Step: owner refreshes the staging market secrets to a currently-OPEN market, then re-dispatch `staging-proof-fly.yml` (case3 → all-broker) to drive cases 1–4 to green.

---

## 1. What was built / proven

Dispatched the live staging proof against the real Polymarket CLOB for the first
time on the **new CLOB v2 backend** (`USE_PYSDK_CLOB=1`, polymarket-client), from
an isolated Fly machine in **nrt (Tokyo, order-allowed)**, throwaway wallet, no
prod secrets, `allow_fills=0` (no real USDC).

Run #6 (id 27016636308) result — **the migration is validated at the broker boundary**:

- The order was **built → signed → POSTed** and reached the CLOB. The broker
  parsed the v2 `SignedOrder`, looked up the orderbook, and rejected with
  `RequestRejectedError: the orderbook *** does not exist`.
- **`400 order_version_mismatch` is GONE.** That rejection — the entire reason
  for the migration — no longer occurs. The CLOB v2 `SignedOrder` schema produced
  by `AsyncSecureClient.create_limit_order` is **accepted** by the broker.
- The remaining failure is **stale staging data**, not a code defect: the
  configured staging market's orderbook no longer exists (resolved/closed). It
  needs fresh coordinates of a currently-open market.

En route, the live rejection surfaced one real classification defect, now fixed.

## 2. Root cause (error-mapping defect)

`PolymarketSdkClient._map_error` bucketed **HTTP 400 together with 401/403** into
`ClobAuthError`. A 400 (`the orderbook does not exist`, bad price/tick, closed
market) is a **request/validation** rejection, not an authn/authz failure.
Mislabelling it as auth is misleading for operators and risks driving the wrong
remediation (re-auth/credential churn) on what is actually a request-shape or
market-state problem.

## 3. Fix

`projects/polymarket/crusaderbot/integrations/clob/sdk_client.py` — split the
bucket: only **401/403 → `ClobAuthError`**; **400 (and 404/409/422/…) → `ClobAPIError`**
(`status_code` preserved). 5xx → `ClobServerError` unchanged.

## 4. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/integrations/clob/sdk_client.py` — `_map_error`: 400 no longer mapped to `ClobAuthError`.
- `projects/polymarket/crusaderbot/tests/test_clob_pysdk.py` — added `test_map_error_request_rejected_400_is_api_not_auth` (regression guard); existing 403→auth test unchanged.

Created:
- `projects/polymarket/crusaderbot/reports/forge/clob-v2-error-mapping.md` — this report.

## 5. What is working

- Live CLOB v2 order build/sign/POST round-trips to the real broker; schema accepted (no `order_version_mismatch`).
- `signature_type=1` (proxy) wallet drove the order without a client-side signing/inference error.
- `py_compile` clean on both changed files. Mapper unit tests run in CI (polymarket dep not installed in this container).

## 6. Known issues / boundaries

- **Staging market coordinates are stale** — `STAGING_TOKEN_ID`/`STAGING_MARKET_ID`
  point to a market with no live orderbook. Owner action: set them to a currently
  OPEN market, then re-run. The proof cannot reach green until then.
- `signature_type` is inferred by py-sdk from the wallet (advisory only); proxy
  vs Safe selection still to be confirmed once a live order rests successfully.
- GTC-only on this backend (GTD/FOK/FAK/market → `ClobConfigError`): follow-up lane.
- polymarket-client pinned `==0.1.0b3` (beta).

## 7. What is next

1. Owner refreshes the staging market secrets to a currently-OPEN market.
2. Re-dispatch `staging-proof-fly.yml` case3 → confirm a real GTC order rests,
   then the kill switch cancels it; then `all-broker` for cases 1–2–4.
3. Confirm `signature_type` proxy inference once an order rests.
4. Pass all 5 cases (case5 already PASSED) → WARP🔹CMD LIVE decision. `allow_fills`/`ENABLE_LIVE_TRADING` stay gated.
5. Follow-up lane: GTD/FOK/FAK/market-order support.

---

Validation Handoff (NEXT PRIORITY): proof EXECUTION continues — migration validated at broker boundary; remaining blocker is owner-held staging market coordinates. Source: projects/polymarket/crusaderbot/reports/forge/clob-v2-error-mapping.md — Tier: MAJOR (dormant).
