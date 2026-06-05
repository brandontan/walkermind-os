# WARP•FORGE Report — CLOB v2 Migration (PLAN ONLY)

Role: WARP•FORGE (investigate/plan sub-task — NO merge authority)
Branch: WARP/clob-v2-migration
Lane: WARP-74 Lane 2 staging proof → CLOB v2 migration
Owner directive: "Investigate + plan first" — present plan, get approval BEFORE touching execution code.

Validation Tier: MINOR (this artifact is a plan + state sync; ZERO runtime code changed)
Claim Level: FOUNDATION (investigation + plan only — no integration performed)
Validation Target: the migration plan's accuracy against py-clob-client-v2 source and current order path
Not in Scope: any edit to `integrations/clob/adapter.py`, `__init__.py`, `pyproject.toml`, or tests (the migration itself — deferred until boss approval; that lane is MAJOR tier and SENTINEL-gated)
Suggested Next Step: boss approves plan → open `WARP/clob-v2-migration` FORGE lane to implement Option A (below) → staging proof cases 1–4 from Fly `nrt` → SENTINEL before LIVE flip

---

## 1. What was built

No code. This deliverable is a **read-only investigation + concrete migration plan** for moving the
live order-placement path from the archived `py-clob-client` (v1) to `py-clob-client-v2`, which is
the confirmed fix for the `400 order_version_mismatch` blocker on staging-proof cases 1–4.

Produced:
- Confirmed root cause (v1 EIP-712 order struct rejected by CLOB v2).
- v1→v2 API delta table (from py-clob-client-v2 source).
- Architectural decision (keep async transport vs adopt v2 ClobClient) with recommendation.
- Concrete migration steps, effort, risk, and the unknowns that must be verified at implementation time.

## 2. Current system architecture (order path today)

The order path is a **hybrid**: the SDK is used ONLY to build + sign the order struct; the
adapter posts it through its OWN async httpx transport with hand-rolled auth and resilience.

```
post_order(token_id, side, price, size, order_type, tick_size, neg_risk)
  └─ _build_signed_order()                      integrations/clob/adapter.py:436
       ├─ py_clob_client.signer.Signer(private_key=, chain_id=)        adapter.py:470
       ├─ py_clob_client.order_builder.builder.OrderBuilder(
       │      signer, sig_type=<int>, funder=)                          adapter.py:473
       ├─ py_clob_client.clob_types.OrderArgs(token_id, price, size, side)
       ├─ [opt] CreateOrderOptions(tick_size, neg_risk)
       └─ builder.create_order(order_args[, opts]).dict()  → v1 order dict  adapter.py:493/495
  └─ body = {"order": signed, "owner": api_key, "orderType": order_type}  adapter.py:305
  └─ _breaker.call(_signed_request("POST", "/order", body))   ← own httpx + L2 HMAC + retries
```

Resilience that lives in the adapter (NOT the SDK), and must be preserved by any migration:
- async httpx transport (asyncio-only HARD RULE)
- circuit breaker + rate limiter singletons (`__init__.py:142-143`)
- L2 HMAC signing (`auth.py` `build_l2_headers`) over `ts+method+path+body`
- optional builder-attribution headers (`build_builder_headers`)
- `_derived` auto-credential cache (`__init__.py:147`, `ensure_clob_credentials`)

Credential L1/L2 paths (`/auth/derive-api-key`, `/auth/api-key`) are **already proven working** by
the staging proof (auth succeeded; the failure is purely the order struct). So the migration is
scoped to order BUILD + SIGN + POST-envelope only — not auth, not market data, not cancel.

## 3. Files created / modified

This PR (plan only):
- `projects/polymarket/crusaderbot/reports/forge/clob-v2-migration.md` (this report)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (surgical: IN PROGRESS + NEXT PRIORITY)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append one lane entry)

Files the APPROVED migration will touch (NOT touched here):
- `projects/polymarket/crusaderbot/pyproject.toml:19` — `py-clob-client` → `py_clob_client_v2`
- `projects/polymarket/crusaderbot/integrations/clob/adapter.py` — `_build_signed_order`, `post_order` envelope
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py` — only if `ClobClientProtocol.post_order` gains `post_only`/`defer_exec`
- `projects/polymarket/crusaderbot/tests/...` — unit test for v2 order field-set + staging harness rerun

## 4. What is working (investigation findings)

### Root cause — CONFIRMED
- Bot order path uses the archived `py-clob-client` v1 (archived 2026-05-11). Its
  `OrderBuilder.create_order` emits a **v1 CTF-Exchange EIP-712 order struct**.
- Polymarket CLOB v2 (~Apr 30 2026) rejects the v1 struct → `400 order_version_mismatch`
  (invariant across `neg_risk` and `signature_type` 1/2, as observed from Fly `nrt`).
- Fix = migrate to `py-clob-client-v2` (`pip install py_clob_client_v2`, import root `py_clob_client_v2`).

### v1 → v2 API delta — from py-clob-client-v2 source
| Concern | v1 (current) | v2 |
|---|---|---|
| pip / import | `py-clob-client` / `py_clob_client` | `py_clob_client_v2` / `py_clob_client_v2` |
| Signer ctor | `Signer(private_key, chain_id)` | `Signer(private_key, chain_id)` — unchanged ✓ |
| Signer addr | `.address` (property) | `.address()` (method), `.get_chain_id()` |
| OrderBuilder ctor | `OrderBuilder(signer, sig_type=<int>, funder=)` | `OrderBuilder(signer, signature_type=<SignatureTypeV2>, funder=)` |
| build method | `create_order(args[, opts])` → SignedOrder | `build_order(args, options, version=2, fee_rate_bps=None)` → SignedOrderV2 |
| options | optional (omitted when no tick/neg) | **required** positional (`CreateOrderOptions` / `PartialCreateOrderOptions`) |
| OrderArgs | token_id, price, size, side | + expiration, builder_code, metadata, user_usdc_balance |
| order struct fields | salt, maker, signer, **taker**, tokenId, makerAmount, takerAmount, expiration, **nonce**, **feeRateBps**, side, signatureType, signature | salt, maker, signer, tokenId, makerAmount, takerAmount, side, expiration, signatureType, **timestamp**, **metadata**, **builder**, signature |
| POST envelope | `{"order": <dict>, "owner", "orderType"}` | `order_to_json_v2(...)` → adds `owner, orderType, deferExec, postOnly` |
| version resilience | none | client `_retry_on_version_update` loop |

The struct change is the smoking gun: v2 **drops** `taker`/`nonce`/`feeRateBps` and **adds**
`timestamp`/`metadata`/`builder`. Different struct → different EIP-712 hash → v1 signature is
rejected. `build_order(version=2)` produces the struct CLOB v2 expects.

### Architectural decision
**Option A — Minimal swap (RECOMMENDED).** Keep the async httpx transport and ALL adapter
resilience. Replace only `_build_signed_order` (import `py_clob_client_v2`, `build_order(version=2)`)
and rebuild the `post_order` envelope to match `order_to_json_v2`. Pin `py_clob_client_v2`, drop v1.
- Pros: smallest blast radius on a capital-safety path; preserves asyncio-only, circuit breaker,
  rate limiter, L2 HMAC, builder headers, `_derived` cache; cancel / market-data / fills untouched.
- Cons: must replicate the v2 envelope exactly and keep it in sync; loses the SDK's
  `_retry_on_version_update` unless we add explicit version-mismatch handling.

**Option B — Adopt v2 `ClobClient` for the order path. REJECTED.** The v2 `ClobClient` is
**synchronous (`requests`-based)** → blocking I/O on the async trading loop, violating the
asyncio-only HARD RULE unless wrapped in `run_in_executor`; it also manages its own creds / session /
host, conflicting with the `_derived` cache, builder headers, and the shared breaker + limiter.
High blast radius on a capital path. Disqualified.

→ **Recommendation: Option A.**

## 5. Known issues (risks + unknowns to verify at implementation time)

These CANNOT be finalized from README/source skim alone and MUST be confirmed when code is written:

1. **`order_to_json_v2` exact envelope** — flat (order fields at top level) vs nested under `order`,
   and whether `metadata`/`builder`/`timestamp` must be non-zero/non-empty. The adapter's hand-rolled
   body must byte-match what the broker recomputes (L2 HMAC is over the exact body).
2. **`SignatureTypeV2` integer mapping** — current config passes ints (magic-link Polymarket =
   PROXY = `1`). Must confirm `SignatureTypeV2` enum int values match (EOA/POLY_PROXY/POLY_GNOSIS_SAFE/
   POLY_1271) so `POLYMARKET_SIGNATURE_TYPE` stays valid; add an int→enum map.
3. **Current live order version** — `build_order(version=2)` is the default, but the SDK's
   `_retry_on_version_update` exists because the broker can bump again. Confirm v2 is broker-current at
   implementation time; consider porting explicit version-mismatch handling.
4. **Serialization source of truth** — use `order_to_json_v2` (not `SignedOrderV2.dict()`) as the
   canonical body shape; confirm whether a public helper is importable or must be replicated.
5. **`post_only` / `defer_exec`** — v2 envelope carries them; confirm broker requirement and whether
   `ClobClientProtocol.post_order` should expose them (default false) to keep the mock in parity.

Safety invariants unchanged by the plan: `ENABLE_LIVE_TRADING` guard, Kelly a=0.25, asyncio-only,
secrets in `.env`, `allow_fills=true` stays gated. The isolated Fly proof app holds NO prod secrets.

## 6. What is next

Staged migration (execute ONLY after boss approves this plan):

1. `pyproject.toml:19` — `"py-clob-client"` → `"py_clob_client_v2>=<pin>"`; grep-verify no other
   `py_clob_client` import remains.
2. `adapter.py._build_signed_order` — import `py_clob_client_v2`; map int `signature_type` →
   `SignatureTypeV2`; `OrderBuilder(signer, signature_type=, funder=)`;
   `build_order(order_args, options, version=2)` (always pass options).
3. `adapter.py.post_order` — rebuild POST body to match `order_to_json_v2` (owner, orderType,
   deferExec, postOnly; confirm flat-vs-nested); thread `post_only`/`defer_exec` if required.
4. `cancel_order` — v2 body still `{"orderID": ...}`; confirm CANCEL path constant unchanged (likely
   no change).
5. Add unit test asserting `_build_signed_order` emits the v2 field set (no taker/nonce/feeRateBps;
   has timestamp/metadata/builder).
6. (Optional, recommended) explicit `order_version_mismatch` handling mirroring `_retry_on_version_update`.
7. Run staging-proof cases 1–4 from Fly `nrt` (Tokyo, API-permitted) with `allow_fills=false`; then a
   single gated `allow_fills=true` confirmation before LIVE.

### Effort / Risk
- **Effort: S–M.** 2 prod files (`adapter.py`, `pyproject.toml`) + 1 test; ~1 focused FORGE chunk.
- **Risk: MAJOR tier** — EIP-712 order signing on the execution/capital path. Real-money correctness
  hinges on exact envelope/field replication. **WARP•SENTINEL validation required before LIVE flip.**
  Acceptance gate = all 5 staging-proof cases pass (cases 1–4 via Fly `nrt`), `allow_fills` gated.

---

Validation Handoff (NEXT PRIORITY):
```
WARP🔹CMD review required — APPROVE migration plan (Option A) before execution-code lane opens.
Source: projects/polymarket/crusaderbot/reports/forge/clob-v2-migration.md
Tier: MINOR (this plan artifact) — planned migration is MAJOR (SENTINEL-gated)
```
