# WARP•SENTINEL — CLOB v2 migration (polymarket-client backend)

Auditor: WARP•R00T (owner-assigned; self-audit authorized 2026-06-05)
PR: #1638 · Branch: WARP/clob-v2-migration · Head: post-merge (origin/main merged in)
Tier: MAJOR (execution / capital path) · Default posture: UNSAFE until proven

---

## TEST PLAN

Environment: dev (code-truth audit). The live 5-case staging proof (real CLOB,
Fly Tokyo `nrt`) is NOT runnable from this container — no `STAGING_*` secrets,
no full runtime deps. Phases run here: 0 (pre-test), 1 (functional/unit, lib
mocked + real exception classes), 3 (failure-mode mapping), 4 (async safety),
5 (risk invariants). Phases 2/6/7/8 (live pipeline, latency, infra, Telegram
live) deferred to the staging proof.

## PHASE 0 — PRE-TEST

- Forge report present, correct path/naming, all 6 sections + metadata — PASS (`reports/forge/clob-v2-migration-pysdk.md`).
- PROJECT_STATE.md updated (IN PROGRESS + NEXT PRIORITY + timestamp) — PASS.
- No `phase*/` folders — PASS.
- No hard-delete policy violation (legacy ClobAdapter retained intentionally, documented) — PASS.
- Implementation evidence for the critical layer (order build/sign/post) exists — PASS.

## FINDINGS (code = truth)

- ARCH (`integrations/clob/sdk_client.py`): new `PolymarketSdkClient` implements the full `ClobClientProtocol`; heavyweight `AsyncSecureClient.create()` behind a lazy `asyncio.Lock` singleton (`sdk_client.py:148` `_ensure`) → sync `get_clob_client()` factory + all 18 consumers unchanged. Clean composition; no rewrite. PASS.
- FUNCTIONAL: isolated logic tests pass against the REAL `polymarket-client` exception classes — accepted→dict, `RejectedOrder`→raise, non-GTC→`ClobConfigError`, open-order id/`asset_id` aliasing, `get_fills` order-id filter, market-scoped cancel, error mapping. CI "Lint + Test" GREEN on the merge commit (full 2843-test suite incl. `test_clob_pysdk.py`).
- FAILURE MODES (`sdk_client.py:189` `_map_error`): py-sdk `RateLimitError`/`RequestRejectedError(4xx/5xx)`/`TransportError`/`TimeoutError`/`SigningError`/`UserInputError`/`Insufficient*` → typed `ClobError`; unknown exceptions re-raised unchanged (no masking). `RejectedOrder` is RAISED, never returned silently (`_accepted_to_dict`, `sdk_client.py:250`). Order path wrapped by CircuitBreaker + RateLimiter (`post_order`/`cancel*`/`get_order`/`get_open_orders`). PASS.
- ASYNC SAFETY: async-only; no threading; py-sdk client is async-native; singleton guarded by `asyncio.Lock` (double-checked). `aclose` idempotent + swallows teardown errors only. PASS.
- RISK INVARIANTS: no threading, no full Kelly (a=1.0), no hardcoded secrets, `ENABLE_LIVE_TRADING` untouched, no `phase*/`, no `except: pass`. Dep bumps (`eth-account>=0.13`, `websockets>=13`) validated by the green full suite. PASS.

## CRITICAL ISSUES

- None blocking MERGE. The backend is config-gated `USE_PYSDK_CLOB` (default False) → prod path returns `ClobAdapter` unchanged; merging carries ZERO prod/capital change.

## FIX RECOMMENDATIONS (priority ordered)

1. [FIXED this audit] `get_fills` queried `maker_address=self._address` (EOA signer); proxy wallets (signature_type 1/2 + funder — the staging/prod config) record trades under the FUNDER. Now queries `self._funder or self._address` (`sdk_client.py:395`). Would otherwise have returned zero fills for the exact wallet the proof uses.
2. [BLOCKS LIVE, not merge] GTC-only: `post_order` raises `ClobConfigError` for GTD/FOK/FAK/market. Live paths that place market/FOK orders (complete-set, fast exit) would fail under this backend → close or confirm out-of-scope before LIVE.
3. [VERIFY IN PROOF] `signature_type` is advisory — py-sdk infers proxy type from `wallet`. Confirm it selects the correct proxy (type 1 magic-link vs type 2 Safe) for the staging wallet during the proof.
4. [LOW] `get_fills` and `_ensure`/`create()` are not breaker-wrapped (matches legacy adapter for get_fills). Acceptable; revisit if create() failures need breaker accounting.

## STABILITY SCORE

- Architecture 18/20 · Functional 12/20 (live path UNPROVEN here; market-order gap) · Failure modes 16/20 · Risk 17/20 · Infra+TG 8/10 · Latency 6/10 (per-order tick_size network resolution unmeasured)
- TOTAL: 77/100

## GO-LIVE STATUS

- VERDICT (MERGE, dormant backend): APPROVED — code-correct, CI green, inviolable invariants clean, default-off ⇒ zero prod/capital change. Safe to merge to unblock the lane.
- VERDICT (LIVE activation): BLOCKED until ALL of: (a) live 5-case staging proof passes from Fly `nrt` with `USE_PYSDK_CLOB=1` (confirms `order_version_mismatch` resolved); (b) `signature_type` inference confirmed for the proxy wallet; (c) GTC-only gap closed or confirmed out-of-scope. `ENABLE_LIVE_TRADING` / `allow_fills` remain gated.

Disposition: WARP•R00T merges the dormant backend (full merge authority); LIVE flip stays gated behind the staging proof above.
