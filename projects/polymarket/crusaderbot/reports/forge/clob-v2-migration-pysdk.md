# WARP-74 CLOB v2 Migration — polymarket-client backend (implementation)

Validation Tier: MAJOR (execution / capital path)
Claim Level: NARROW INTEGRATION (backend implemented + unit-verified against real polymarket-client; LIVE 5-case staging proof NOT yet run)
Validation Target: order build/sign/post/cancel/get_order/get_open_orders/get_fills via the official `polymarket-client` (CLOB v2 SignedOrder schema), behind the `USE_PYSDK_CLOB` flag, preserving the existing `ClobClientProtocol` + circuit-breaker + rate-limiter + typed-exception contract.
Not in Scope: GTD/FOK/FAK/market-order paths (raise `ClobConfigError`, documented follow-up); flipping the default backend to py-sdk in prod; the live 5-case Fly-Tokyo staging proof; prod `fly.toml` region (close-only `sin`) decision.
Suggested Next Step: dispatch `staging-proof-fly.yml` from `nrt` with `USE_PYSDK_CLOB=1` to run cases 1–4 against the real CLOB, then WARP•SENTINEL before any LIVE flip.

---

## 1. What was built

Owner pivoted the migration target from `py-clob-client-v2` (the prior plan) to the
official unified SDK **`polymarket-client`** (PyPI, `0.1.0b3`, beta). Implemented a
new order backend `PolymarketSdkClient` that delegates order construction/signing/
posting to `polymarket.AsyncSecureClient` — which produces the **CLOB v2 SignedOrder
struct** the broker now requires — while keeping every resilience guarantee the rest
of the system depends on.

Root cause (confirmed earlier): the legacy `ClobAdapter._build_signed_order` hand-built
the EIP-712 order via the archived `py-clob-client` v1. CLOB v2 (~Apr 2026) rejects that
struct with `400 order_version_mismatch`. The v2 `SignedOrder` drops `taker`/`nonce`/
`feeRateBps` and adds `timestamp`/`metadata`/`builder` (verified against the installed
b3 dataclass).

Key design decision: because every `ClobClientProtocol` order method is already `async`,
the network-heavy, stateful `AsyncSecureClient.create()` is hidden behind a **lazy cached
singleton** (`asyncio.Lock`) inside the new client. This keeps the synchronous
`get_clob_client()` factory and all **18 consumers unchanged** — no ripple into
`domain/execution/*`, `domain/risk/kill_switch_exec`, `scheduler`, `bot/handlers`.

Rollout is **config-gated** (`USE_PYSDK_CLOB`, default False) so prod behaviour and the
full test suite are unchanged until the staging proof + SENTINEL validate the new
backend. The staging-proof harness sets the flag to 1.

## 2. Current system architecture (relevant slice)

```
get_clob_client(settings)
  ├─ USE_REAL_CLOB=False ───────────────► MockClobClient            (paper-safe)
  └─ USE_REAL_CLOB=True
       ├─ USE_PYSDK_CLOB=True ──────────► PolymarketSdkClient  ◄── NEW (CLOB v2)
       │     └─ lazy AsyncSecureClient (polymarket-client)
       │          create_limit_order → SignedOrder(v2) → post_order
       │          wrapped per-call by the package CircuitBreaker + RateLimiter
       │          py-sdk errors → ClobError taxonomy; RejectedOrder → raise
       └─ USE_PYSDK_CLOB=False ─────────► ClobAdapter                (legacy v1, unchanged)
```

`PolymarketSdkClient` implements the full `ClobClientProtocol` and exposes the same
ops/factory properties (`address`, `funder`, `signature_type`, `has_builder_credentials`,
`circuit_breaker`, `rate_limiter`). Response models are mapped to the exact dict keys
consumers read (`orderID`/`order_id`/`id`, `status`, `success`, `price`, `asset_id`).

Credential mapping: `private_key`→`create(private_key=)`, `funder_address`→`wallet=`,
env/derived L2 creds→`credentials=ApiKeyCreds(apiKey,secret,passphrase)` (optional — py-sdk
derives when absent), builder creds→`api_key=BuilderApiKey(...)`.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/integrations/clob/sdk_client.py` — `PolymarketSdkClient` (new backend).
- `projects/polymarket/crusaderbot/tests/test_clob_pysdk.py` — unit tests (py-sdk mocked).
- `projects/polymarket/crusaderbot/reports/forge/clob-v2-migration-pysdk.md` — this report.

Modified:
- `projects/polymarket/crusaderbot/config.py` — add `USE_PYSDK_CLOB: bool = False`.
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py` — import/export `PolymarketSdkClient`; `USE_PYSDK_CLOB` branch in `get_clob_client`.
- `projects/polymarket/crusaderbot/pyproject.toml` — `py-clob-client` → `polymarket-client==0.1.0b3`; `eth-account>=0.13,<1`; `websockets>=13.0,<14.0` (satisfy polymarket-client constraints).

## 4. What is working

- `polymarket-client==0.1.0b3` installs clean on Python 3.11; API surface introspected against the **installed** build (not just `main`).
- All changed Python files `py_compile`-clean.
- Isolated logic tests pass against the **real** polymarket-client exception classes (run outside the heavy package init): accepted-order→dict mapping; `RejectedOrder`→`ClobAPIError`; non-GTC→`ClobConfigError`; open-order id/asset aliasing; `get_fills` order-id filtering (incl. `maker_orders[].order_id`); `get_order` status; global `cancel_all`; error mapping (`RateLimitError`→`ClobRateLimitError`, `RequestRejectedError(403)`→`ClobAuthError`).
- Factory remains backward-compatible: with `USE_PYSDK_CLOB=False` (default) `get_clob_client` returns `ClobAdapter`, so `tests/test_clob_factory.py` and the ~20 existing clob test files are untouched.

## 5. Known issues / boundaries

- **Cannot run the full `pytest` suite or the live staging proof in this container** — project runtime deps (fastapi/asyncpg/redis/etc.) and `STAGING_*` secrets are not provisioned here. Verification done = install + introspection + isolated logic tests + py_compile. The 5-case real-broker proof is the gating step and runs in CI (Fly Tokyo) under SENTINEL.
- **`signature_type` is advisory** under this backend: `AsyncSecureClient.create()` has no `signature_type` param and infers the proxy type from `wallet`. `POLYMARKET_SIGNATURE_TYPE` is logged but not enforced — must confirm py-sdk selects the correct proxy (type 1 magic-link vs type 2 Safe) for the staging/prod wallet during the proof.
- **GTC-only**: `post_order` raises `ClobConfigError` for GTD/FOK/FAK (py-sdk market orders use a different arg shape). Sufficient for the proof (resting GTC); market/FOK path is a follow-up lane.
- **beta dependency** pinned to `==0.1.0b3`; bump only with a fresh staging proof.
- Legacy `ClobAdapter` retained (still the backend when `USE_PYSDK_CLOB=False`, and source of `_trade_matches_order` reused by the new client). Not a shim — it is a distinct, selectable backend.

## 6. What is next

1. Dispatch `staging-proof-fly.yml` from `nrt` with `USE_PYSDK_CLOB=1` (+ existing `STAGING_*`) → run cases 1–4 against the real CLOB; confirm `order_version_mismatch` is gone and signature-type inference is correct.
2. Keep `allow_fills`/`ENABLE_LIVE_TRADING` gated; pass all 5 cases.
3. WARP•SENTINEL MAJOR validation before any LIVE flip; then WARP🔹CMD decides flipping `USE_PYSDK_CLOB` default + removing the legacy v1 path.
4. Follow-up lane: GTD/FOK/FAK/market-order support on the py-sdk backend.

---

Validation Handoff (NEXT PRIORITY): WARP•SENTINEL validation required for CLOB v2 polymarket-client backend before LIVE. Source: projects/polymarket/crusaderbot/reports/forge/clob-v2-migration-pysdk.md — Tier: MAJOR.
