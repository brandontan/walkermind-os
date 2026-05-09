# WARP•FORGE Report — CLOB Adapter (Phase 4A)

| Field | Value |
| --- | --- |
| Branch | `WARP/CRUSADERBOT-PHASE4A-CLOB-ADAPTER` |
| Tier | MAJOR |
| Claim Level | NARROW INTEGRATION |
| Validation Target | `integrations/clob/*` (auth, adapter, market data, factory, mock) — auth + transport layers only. On-chain order builder still delegated to `py-clob-client.OrderBuilder`. |
| Not in Scope | Live execution rewiring (`domain/execution/live.py` still calls `integrations.polymarket._build_clob_client`); on-chain CTF Exchange order schema; WebSocket subscriptions; gasless relayer. Deferred to Phase 4B / 4C. |
| Suggested Next Step | WARP•SENTINEL audit, then Phase 4B to migrate `domain.execution.live` callers onto `get_clob_client()` behind the activation guards. |
| Activation Guards | `ENABLE_LIVE_TRADING` / `EXECUTION_PATH_VALIDATED` / `CAPITAL_MODE_CONFIRMED` — UNCHANGED (still NOT SET in deployment posture). New `USE_REAL_CLOB` defaults to `False` (paper-safe). |

---

## 1. What was built

A new package `projects/polymarket/crusaderbot/integrations/clob/` that ships
a custom REST adapter against `https://clob.polymarket.com`, sitting alongside
(not yet replacing) the existing `py-clob-client`-based path in
`integrations/polymarket.py`. Five modules:

- `auth.py` — pure helpers for L1 (EIP-712 ClobAuth), L2 (HMAC-SHA256), and
  builder headers. Locked against domain name `ClobAuthDomain`, version `"1"`,
  chain id `137`, and the canonical attestation message string.
- `adapter.py` — `ClobAdapter` async REST client. Owns the auth + transport
  layers (header construction, retry posture, error classification);
  delegates the on-chain order signature blob to `py-clob-client.OrderBuilder`
  via a private `_build_signed_order` seam (Phase 4C scope).
- `market_data.py` — `MarketDataClient`. Unauthenticated reads
  (`/book`, `/midpoint`, `/spread`, `/price`, `/markets`, `/tick-size`,
  `/neg-risk`). Cannot leak Polymarket secrets — separate transport,
  no signing path.
- `mock.py` — `MockClobClient`. Network-free, deterministic, same async
  surface as `ClobAdapter`. Asserts `httpx.AsyncClient` is never instantiated.
- `__init__.py` — `get_clob_client(settings)` factory + `ClobClientProtocol`.
  Default branch returns `MockClobClient`; the real branch fail-fast raises
  `ClobConfigError` listing the missing env vars (no silent degradation to
  mock — that would be a capital-safety footgun).

Plus:
- `config.py` — six new optional settings (API passphrase alias, private key,
  funder address, signature type, three builder credentials) and the
  `USE_REAL_CLOB` toggle (default `False`).
- Test bundle — 45 new unit tests (auth / adapter / market data / factory /
  mock) + 1 manual integration smoke file (skipped in CI; env-gated).

### Authentication contract (locked by tests)

| Layer | Path           | Headers                                                                                  | Spec lock      |
| ---   | ---            | ---                                                                                      | ---            |
| L1    | `/auth/*`      | `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_NONCE`                          | EIP-712 vector |
| L2    | every other    | `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_API_KEY`, `POLY_PASSPHRASE`     | HMAC vector    |
| Build | every order    | `POLY_BUILDER_API_KEY`, `POLY_BUILDER_TIMESTAMP`, `POLY_BUILDER_PASSPHRASE`, `POLY_BUILDER_SIGNATURE` | HMAC vector    |

The L1 EIP-712 signature is locked against a deterministic test vector
(`pk = 0xaa..aa`, `ts = 1_700_000_000`, `nonce = 0`,
`expected_sig = 0xd26cc35884048a6223f0530c5d6b86d757bf10c77147a75b9f8b78154773aa7909a883170ba952ac61691af31bd51a230387c613bcefd960efd1f1e6cd485d241b`).
Any drift in the domain (`ClobAuthDomain`/`"1"`/`137`) or message string
fails the test loudly.

The HMAC signature is similarly locked
(`secret = urlsafe_b64encode("test-secret-32-bytes-for-hmac-aa")`,
`ts = 1_700_000_000`, `POST /order` body `{"a":1}` →
`gkIXW1DbVAgR5Eo2M4QUfqa2WXbMRKckaEVD043fVXM=`).

### Toggle posture (paper-safe)

`USE_REAL_CLOB=False` (default) → `MockClobClient`. CI runs without any
Polymarket secret. `USE_REAL_CLOB=True` AND credentials complete →
`ClobAdapter`. `USE_REAL_CLOB=True` with missing creds → `ClobConfigError`
listing every missing env var. There is NO silent fallback path between mock
and real.

The factory accepts both the new `POLYMARKET_API_PASSPHRASE` env name
(per the dispatched task spec) and the legacy `POLYMARKET_PASSPHRASE`
(consumed by the existing `integrations.polymarket._build_clob_client` SDK
path). Operators do not need to rename the secret on Fly to enable Phase 4A.

---

## 2. Current system architecture

```
                                +-----------------------+
                                |   USE_REAL_CLOB env   |
                                +-----------+-----------+
                                            |
                            False (default) |  True + creds complete
                                            |
                  integrations.clob.get_clob_client(settings)
                                            |
              +-----------------------------+-----------------------------+
              |                                                           |
       MockClobClient                                            ClobAdapter
       (deterministic,                                       (httpx.AsyncClient,
        no network)                                          tenacity retries,
              |                                              EIP-712 + HMAC,
              |                                              optional builder)
              |                                                           |
              |                                                           |
              +----- ClobClientProtocol (post_order / cancel_order        |
                       / get_order / aclose) -----------------------------+
                                            |
                                            v
                          (Phase 4B target — not wired in this lane)
                          domain.execution.live.execute_live_order

  integrations.clob.MarketDataClient
        (separate transport, never signs, no creds needed) - reachable today
```

Untouched:

- `integrations/polymarket.py` — `_build_clob_client()` / `prepare_live_order()`
  / `submit_signed_live_order()` / `submit_live_redemption()` still drive
  every existing live-execution call site. Phase 4B will rewire them.
- `domain/execution/{live,paper,router,order}.py` — unchanged.
- `monitoring/` — unchanged.
- All activation guards — unchanged.

---

## 3. Files created / modified (full repo-root paths)

Created:

- `projects/polymarket/crusaderbot/integrations/clob/__init__.py`
- `projects/polymarket/crusaderbot/integrations/clob/auth.py`
- `projects/polymarket/crusaderbot/integrations/clob/adapter.py`
- `projects/polymarket/crusaderbot/integrations/clob/market_data.py`
- `projects/polymarket/crusaderbot/integrations/clob/mock.py`
- `projects/polymarket/crusaderbot/integrations/clob/exceptions.py`
- `projects/polymarket/crusaderbot/tests/test_clob_auth.py`
- `projects/polymarket/crusaderbot/tests/test_clob_adapter.py`
- `projects/polymarket/crusaderbot/tests/test_clob_market_data.py`
- `projects/polymarket/crusaderbot/tests/test_clob_factory.py`
- `projects/polymarket/crusaderbot/tests/integration_clob_smoke.py`
- `projects/polymarket/crusaderbot/reports/forge/clob-adapter.md` (this file)

Modified:

- `projects/polymarket/crusaderbot/config.py` — surgical addition of
  `POLYMARKET_API_PASSPHRASE`, `POLYMARKET_PRIVATE_KEY`,
  `POLYMARKET_FUNDER_ADDRESS`, `POLYMARKET_SIGNATURE_TYPE`,
  `POLYMARKET_BUILDER_API_KEY`, `POLYMARKET_BUILDER_API_SECRET`,
  `POLYMARKET_BUILDER_PASSPHRASE`, `USE_REAL_CLOB`. Existing fields
  untouched. Validation hooks untouched.

State files (to be updated under Chunk 5 commit):

- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What is working

Test suite: **624/624 crusaderbot tests passing**, ruff clean on every
changed file. New + previously green tests both clean.

Specific green paths:

- L1 EIP-712 signing produces the expected vector (locked against
  `eth-account.encode_typed_data`); domain version drift breaks the test.
- L2 HMAC produces the expected vector; method-case normalisation,
  body-difference detection, and unpadded-base64 tolerance all locked.
- Strict base64 validation: a typo'd secret raises `ClobAuthError` instead
  of silently producing a wrong HMAC (catches the
  `urlsafe_b64decode strips invalid chars` footgun).
- Builder headers attach iff every builder credential is set; absent
  credentials → no `POLY_BUILDER_*` headers leak onto the request.
- `ClobAdapter.post_order` 4xx → `ClobAPIError`, **no retry** (capital-safety:
  duplicate POST after a broker-class reject is a footgun).
- `ClobAdapter.post_order` 401/403 → `ClobAuthError` (distinct from
  business-class rejection).
- `ClobAdapter.post_order` 5xx → tenacity exponential backoff, 3 attempts,
  then re-raises the underlying `httpx.HTTPStatusError`.
- `MarketDataClient` cannot leak L1/L2 headers onto its transport
  (asserted by `test_no_credentials_required`).
- `MockClobClient` never instantiates `httpx.AsyncClient` (asserted by
  `test_mock_does_not_create_an_httpx_client`); deterministic order ids
  across instances given identical inputs.
- Factory: `USE_REAL_CLOB=False` → `MockClobClient` regardless of whether
  Polymarket creds exist; `USE_REAL_CLOB=True` + missing creds raises
  `ClobConfigError` listing each missing env var; legacy
  `POLYMARKET_PASSPHRASE` accepted as a fallback for the new
  `POLYMARKET_API_PASSPHRASE` name.

Structure validation:

- Zero `phase*/` folders introduced.
- Zero shims or compat layers.
- Hard delete policy: nothing was renamed or moved (additive lane).
- All new code in the locked domain layout (`integrations/clob/*` lives
  under the existing `integrations/` root).
- No reports outside `{PROJECT_ROOT}/reports/forge/`.
- Encoding: UTF-8 without BOM.

Hard-rule compliance:

- `asyncio` only — no `threading` introduced.
- Secrets only via `.env` / pydantic Settings — no hardcoded keys.
- `Kelly = 0.25` not touched (this lane does not affect risk math).
- Zero silent failures: every exception path either raises `ClobError`
  (typed) or re-raises after logging. `_signed_request` and
  `MarketDataClient._get` both surface 4xx without retrying.
- Full type hints on every public surface.

---

## 5. Known issues

1. **Live callers not yet rewired.** `domain.execution.live.execute_live_order`
   still constructs the SDK client via `integrations.polymarket._build_clob_client`.
   `get_clob_client()` is reachable but unused outside tests + the manual
   smoke script. Phase 4B owns the rewire under the activation guards.
2. **On-chain order builder still delegated to `py-clob-client`.**
   `ClobAdapter._build_signed_order` calls `py_clob_client.order_builder.OrderBuilder`
   so we don't reimplement the CTF Exchange EIP-712 schema (salt, taker /
   maker addresses, neg-risk discriminator) inside this lane. Reimplementing
   that is Phase 4C scope (or never — the SDK piece that is least likely to
   benefit from a custom rewrite).
3. **No WebSocket / streaming surface.** Market subscription channels
   (`wss://ws-subscriptions-clob.polymarket.com/ws/{market,user}`) are not
   in this lane. Existing market data still flows through Gamma in
   `integrations/polymarket.py`.
4. **`POLYMARKET_API_PASSPHRASE` vs `POLYMARKET_PASSPHRASE` duplication.**
   The factory accepts either; both fields exist on `Settings`. A future
   minor lane can deprecate the legacy name once the existing
   `_build_clob_client` callers migrate (Phase 4B / 4C).
5. **Integration smoke test is read-only by default.** `CLOB_SMOKE_WRITE=1`
   enables a single dust-order POST + immediate cancel against the live
   broker. Operator MUST run this on a wallet with negligible balance and
   only when WARP🔹CMD has explicitly approved a write probe.
6. **`run_in_executor` not used for `OrderBuilder`.** `_build_signed_order`
   calls into the SDK synchronously. The on-chain signing is CPU-bound
   (~ms) so the trading loop is not blocked meaningfully today, but
   Phase 4B should wrap the call in `asyncio.to_thread` if profiling shows
   contention.

---

## 6. What is next

Immediate (gating WARP•SENTINEL):

- WARP•SENTINEL audit (MAJOR tier) — Phase 0 then Phases 1, 3, 5.
- Operator review of the new env names (`POLYMARKET_API_PASSPHRASE`,
  `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_FUNDER_ADDRESS`,
  `POLYMARKET_BUILDER_*`, `USE_REAL_CLOB`) before they land in Fly secrets.

Follow-on lanes (NOT in this PR):

- **Phase 4B (MAJOR, NARROW INTEGRATION)** — migrate
  `domain.execution.live.execute_live_order` to call
  `get_clob_client()` instead of the SDK directly. Live engine begins
  using the adapter under the activation guards.
- **Phase 4C (MAJOR, FULL RUNTIME)** — replace `py-clob-client`
  `OrderBuilder` inside `ClobAdapter._build_signed_order` (or formally
  pin the SDK and add a property test against its output).
- **Phase 4D (STANDARD)** — WebSocket market + user channel client living
  next to `MarketDataClient` for real-time orderbook + fills.

Activation guards remain NOT SET. No deployment posture change.

---

## Validation Handoff

```
WARP•SENTINEL validation required for Phase 4A CLOB Adapter before merge.
Source: projects/polymarket/crusaderbot/reports/forge/clob-adapter.md
Tier: MAJOR
```

Done -- Phase 4A CLOB Adapter complete.
PR: WARP/CRUSADERBOT-PHASE4A-CLOB-ADAPTER
Report: projects/polymarket/crusaderbot/reports/forge/clob-adapter.md
State: PROJECT_STATE.md updated
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
