# WARP•SENTINEL Report — CLOB Adapter Phase 4A

| Field | Value |
| --- | --- |
| Branch | `WARP/CRUSADERBOT-PHASE4A-CLOB-ADAPTER` |
| PR | #911 |
| Tier | MAJOR |
| Claim Level | NARROW INTEGRATION |
| Environment | dev — unit test suite (httpx.MockTransport, no network) |
| Validation Target | `integrations/clob/auth.py` · `integrations/clob/adapter.py` · `integrations/clob/market_data.py` · `integrations/clob/mock.py` · `integrations/clob/__init__.py` · `config.py` |
| Not in Scope | Live execution rewiring (Phase 4B) · WebSocket (Phase 4D) · on-chain order builder reimplementation (Phase 4C) |
| Verdict | **APPROVED** |
| Score | **89 / 100** |
| Critical Issues | **0** |

---

## TEST PLAN

**Environment:** Unit tests only — `httpx.MockTransport`, no live network, no real keys.

**Phases run:**

- Phase 0 — Pre-test gates
- Phase 1 — Functional (per-module)
- Phase 3 — Failure modes (4xx / 5xx / auth / bad-input)
- Phase 5 — Risk rules (activation guards, capital-safe no-retry)

**Phases N/A for this lane:**

- Phase 2 — Pipeline end-to-end: live callers (`domain.execution.live`) not yet rewired; this lane is reachable only from tests and the manual smoke file. Phase 4B scope.
- Phase 4 — Async safety: auth helpers are pure functions (no shared state). Mock client holds per-instance `_orders` dict (no shared state between tests).
- Phase 6 — Latency benchmarks: transport-layer unit tests; no latency assertions expected at this claim level.
- Phase 7 — Infra: Redis / PostgreSQL / Alchemy untouched.
- Phase 8 — Telegram: no new alerts or commands in this lane.

---

## Phase 0 — Pre-Test Gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Report at correct path | PASS | `projects/polymarket/crusaderbot/reports/forge/clob-adapter.md` present on PR branch |
| Report naming correct | PASS | `clob-adapter.md` — short hyphen slug, no phase prefix, no date |
| All 6 sections present | PASS | §1 What was built · §2 Architecture · §3 Files · §4 Working · §5 Known issues · §6 Next |
| `PROJECT_STATE.md` updated | PASS | PR file list: `state/PROJECT_STATE.md` modified (+5 / -3) |
| No `phase*/` folders | PASS | Additive lane; PR introduces only `integrations/clob/*` + tests + state files |
| Domain structure correct | PASS | New code under `integrations/clob/` inside existing `integrations/` root |
| Hard delete policy | PASS | Additive lane — no files moved or deleted |
| Implementation evidence | PASS | 45 unit tests + locked EIP-712 and HMAC deterministic test vectors |

**Phase 0 verdict: PASSED — proceeding to functional phases.**

---

## FINDINGS

### Phase 1 — Functional Testing

#### auth.py

| ID | Test | Result |
| --- | --- | --- |
| F1-01 | `test_eip712_signature_matches_known_vector` — `pk=0xaa..aa`, `ts=1700000000`, `nonce=0` → `0xd26cc358...d241b` | PASS |
| F1-02 | `test_clob_constants_unchanged` — domain name `ClobAuthDomain`, version `"1"`, chain `137`, message string locked | PASS |
| F1-03 | `test_l1_headers_have_required_keys_only` — exact 4-key set: `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_NONCE` | PASS |
| F1-04 | `test_nonce_bumps_change_signature` — nonce=0 vs nonce=1 produce distinct signatures | PASS |
| F1-05 | `test_hmac_matches_known_vector` — `secret=det_secret`, `POST /order`, `body={"a":1}` → `gkIXW1DbVAgR5Eo2M4QUfqa2WXbMRKckaEVD043fVXM=` | PASS |
| F1-06 | `test_hmac_method_case_normalized` — `POST` and `post` produce identical HMAC | PASS |
| F1-07 | `test_hmac_body_difference_changes_signature` — `{"a":1}` vs `{"a":2}` differ | PASS |
| F1-08 | `test_hmac_rejects_non_base64_secret` — `ClobAuthError` raised on non-base64 input | PASS |
| F1-09 | `test_hmac_tolerates_unpadded_b64` — padded and unpadded secret produce identical HMAC | PASS |
| F1-10 | `test_l2_headers_match_polymarket_spec` — exact 5-key set: `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_API_KEY`, `POLY_PASSPHRASE` | PASS |
| F1-11 | `test_builder_headers_required_keys` — exact 4-key set: `POLY_BUILDER_API_KEY`, `POLY_BUILDER_TIMESTAMP`, `POLY_BUILDER_PASSPHRASE`, `POLY_BUILDER_SIGNATURE` | PASS |
| F1-12 | `test_builder_signature_matches_l2_hmac_for_same_inputs` — builder uses same HMAC algorithm as L2 | PASS |

#### adapter.py

| ID | Test | Result |
| --- | --- | --- |
| F1-13 | `test_post_order_attaches_l2_headers_and_returns_payload` — all 5 L2 headers present; body has `owner` / `orderType` / `order.tokenId` | PASS |
| F1-14 | `test_post_order_omits_builder_headers_when_unconfigured` — no `poly_builder_*` keys on request | PASS |
| F1-15 | `test_post_order_attaches_builder_headers_when_configured` — all 4 `poly_builder_*` headers present when builder creds set | PASS |
| F1-16 | `test_derive_api_credentials_uses_l1_headers` — 4 L1 headers present; `poly_api_key` and `poly_passphrase` absent on L1 path | PASS |
| F1-17 | `test_cancel_order_sends_delete_with_body` — `DELETE` method; body `{"orderID":"abc"}` | PASS |

#### market_data.py

| ID | Test | Result |
| --- | --- | --- |
| F1-18 | `test_get_orderbook_passes_token_id_param` — path `/book`, query `token_id=TKN` | PASS |
| F1-19 | `test_get_midpoint_and_spread_paths` — `/midpoint` then `/spread` | PASS |
| F1-20 | `test_get_price_uppercases_side` — `side=buy` → `side=BUY` in query string | PASS |
| F1-21 | `test_get_market_uses_path_param` — path `/markets/{condition_id}` (not `/clob-markets`; Codex P2 dismissed — confirmed correct per official py-clob-client source) | PASS |
| F1-22 | `test_get_markets_pagination_passes_cursor` — no cursor on first call; cursor encoded on second | PASS |
| F1-23 | `test_get_tick_size_returns_string` — returns `"0.01"` string | PASS |
| F1-24 | `test_get_neg_risk_returns_bool` — returns Python `True` | PASS |
| F1-25 | `test_no_credentials_required` — handler asserts no `poly_*` header reaches the unauth transport | PASS |

#### factory + mock

| ID | Test | Result |
| --- | --- | --- |
| F1-26 | `test_factory_returns_mock_when_use_real_clob_false` | PASS |
| F1-27 | `test_factory_returns_mock_with_no_polymarket_creds` — CI-safe, no secrets needed | PASS |
| F1-28 | `test_factory_raises_when_use_real_clob_true_but_creds_missing` — `ClobConfigError` message contains all 4 missing var names | PASS |
| F1-29 | `test_factory_returns_real_adapter_when_creds_complete` — `ClobAdapter`, `signature_type=2`, `has_builder_credentials=False` | PASS |
| F1-30 | `test_factory_accepts_legacy_passphrase_name` — `POLYMARKET_PASSPHRASE` fallback accepted | PASS |
| F1-31 | `test_factory_picks_up_builder_creds_when_set` — `has_builder_credentials=True` | PASS |
| F1-32 | `test_mock_post_order_returns_well_formed_response` — `status=matched`, `tokenID`, `side=BUY`, `_mock=True` | PASS |
| F1-33 | `test_mock_orders_are_deterministic_per_invocation` — uuid5 stable across separate `MockClobClient` instances | PASS |
| F1-34 | `test_mock_cancel_round_trip` — cancel found; second cancel returns `canceled=[]` without raising | PASS |
| F1-35 | `test_mock_cancel_all_returns_active_ids` — both placed order IDs in `canceled` list; `open_orders()==[]` | PASS |
| F1-36 | `test_mock_aclose_is_idempotent` — double `aclose()` does not raise | PASS |
| F1-37 | `test_mock_does_not_create_an_httpx_client` — `vars(m)` contains no `httpx.AsyncClient` or `httpx.Client` instance | PASS |

### Phase 3 — Failure Modes

| ID | Test | Result |
| --- | --- | --- |
| F3-01 | **4xx no-retry (adapter)** — `test_post_order_4xx_raises_api_error_no_retry`: `calls["n"]==1`; `ClobAPIError.status_code==400` | PASS |
| F3-02 | **4xx no-retry (market_data)** — `test_4xx_raises_api_error_no_retry`: `calls["n"]==1`; `ClobAPIError.status_code==404` | PASS |
| F3-03 | **5xx retry (adapter)** — `test_post_order_5xx_retries_then_raises`: `calls["n"]==3`; `httpx.HTTPStatusError` re-raised | PASS |
| F3-04 | **5xx retry (market_data)** — `test_5xx_retries_then_raises`: `calls["n"]==3`; `httpx.HTTPStatusError` re-raised | PASS |
| F3-05 | **Auth rejection (401)** — `test_post_order_401_raises_auth_error`: `ClobAuthError` raised; no retry | PASS |
| F3-06 | **Bad secret** — `test_hmac_rejects_non_base64_secret`: `ClobAuthError` on malformed base64; strict `validate=True` decode path at `auth.py:build_hmac_signature` | PASS |
| F3-07 | **Missing creds (factory)** — `test_factory_raises_when_use_real_clob_true_but_creds_missing`: `ClobConfigError` lists all 4 missing vars | PASS |
| F3-08 | **Timeout** — No dedicated unit test for `httpx.TimeoutException`. Tenacity declares `retry_if_exception_type(httpx.TimeoutException)` in both `adapter.py:_signed_request` and `market_data.py:_get`; declared but not exercised by a test. | MINOR GAP |
| F3-09 | **WS disconnect** — N/A (Phase 4D scope) | N/A |
| F3-10 | **Partial fill** — N/A (Phase 4B scope) | N/A |
| F3-11 | **Signal dedup** — N/A (Phase 4B scope) | N/A |

### Phase 5 — Risk Rules

| ID | Check | File:Line | Result |
| --- | --- | --- | --- |
| F5-01 | `USE_REAL_CLOB` defaults `False` (paper-safe) | `config.py:144` | PASS |
| F5-02 | `EXECUTION_PATH_VALIDATED` defaults `False` | `config.py:154` | PASS |
| F5-03 | `CAPITAL_MODE_CONFIRMED` defaults `False` | `config.py:155` | PASS |
| F5-04 | No live execution callers rewired — `domain/execution/live.py` absent from PR file list | PR file list | PASS |
| F5-05 | 4xx no-retry is capital-safe — broker-class reject on `POST /order` cannot cause duplicate order | `adapter.py:_signed_request` + F3-01 | PASS |
| F5-06 | Kelly fraction untouched — `domain/risk/` absent from PR file list | PR file list | PASS |
| F5-07 | `ENABLE_LIVE_TRADING` code default is `True` | `config.py:153` | ⚠️ PRE-EXISTING |

Note on F5-07: Pre-existing Known Issue in PROJECT_STATE.md, NOT introduced by this PR. fly.toml `[env]` overrides to `"false"` so production posture is correct. Phase 4A does not rewire any live execution caller — this default has zero impact on this lane.

---

## CRITICAL ISSUES

None found.

---

## STABILITY SCORE

| Category | Weight | Score | Notes |
| --- | --- | --- | --- |
| Architecture | 20% | 19/20 | Factory toggle correct; clean `ClobClientProtocol`; clear module boundaries. Builder and L2 timestamps generated by separate `_now()` calls — may diverge by ~1s; spec-compliant (each validated independently by broker). |
| Functional | 20% | 19/20 | 37 findings all passing; all 5 modules verified; deterministic EIP-712 and HMAC vectors locked. |
| Failure modes | 20% | 17/20 | 4xx no-retry proven (call counter); 5xx retry proven (3 attempts); auth + config errors typed and raised correctly. Timeout not explicitly unit-tested (tenacity declared, not exercised). WS / partial-fill / dedup N/A this lane. |
| Risk rules | 20% | 19/20 | `USE_REAL_CLOB=False` default confirmed; activation guards unchanged; no live callers rewired. `ENABLE_LIVE_TRADING=True` code default is pre-existing deferred issue with zero impact on this lane. |
| Infra + Telegram | 10% | 8/10 | N/A by lane design — no Telegram / Redis / PostgreSQL touched; no degradation introduced. |
| Latency | 10% | 7/10 | `_build_signed_order` calls `py_clob_client.OrderBuilder` synchronously in async context (forge §5 Known Issue #6); ∼ms CPU, non-blocking at current load. No latency benchmarks expected for unit-test-only lane. |
| **Total** | **100%** | **89 / 100** | |

---

## GO-LIVE STATUS

**APPROVED — Score 89/100 — Zero critical issues.**

Phase 4A is a transport-layer foundation. Live execution is not rewired; all activation guards are unchanged; `USE_REAL_CLOB=False` keeps every caller on `MockClobClient`. Auth primitives are locked against deterministic test vectors. Retry posture is capital-safe (4xx never retried, proven by call counter in two independent test files). Factory is fail-fast on misconfiguration with no silent fallback.

WARP🔹CMD may merge PR #911.

---

## FIX RECOMMENDATIONS (priority ordered — critical first)

Critical: None.

Minor (address in follow-on lanes):

1. **(Phase 4B — MINOR)** Add explicit unit test for `httpx.TimeoutException` in `ClobAdapter._signed_request` and `MarketDataClient._get` to prove tenacity retry fires on timeout. Use `httpx.MockTransport` that raises `httpx.TimeoutException` on the first N calls.

2. **(Phase 4B — MINOR)** Wrap `ClobAdapter._build_signed_order` in `asyncio.to_thread` to prevent blocking the event loop on the synchronous `py_clob_client.OrderBuilder.create_order()` call. At current scale this is non-blocking; required before high-throughput use.

3. **(Post-demo — MINOR / `WARP/config-guard-default-alignment`)** Align `ENABLE_LIVE_TRADING: bool = True` code default in `config.py:153` to `False`. Currently safe because fly.toml `[env]` overrides it; code default disagrees with "all guards default OFF" intent.

---

## TELEGRAM PREVIEW

N/A — Telegram integration unchanged by this lane. No new alert events, commands, or dashboard elements added.

---

**Codex P2 disposition:** `market_data.py` uses `/markets/{condition_id}` and `GET /markets` — confirmed correct per official `py-clob-client` source. Codex P2 suggestion (`/clob-markets`) was incorrect. Dismissed by WARP🔹CMD. ✓
