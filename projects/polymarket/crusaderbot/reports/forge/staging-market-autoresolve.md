# WARP-74 staging proof — runtime open-market resolution (no stale secrets)

Validation Tier: STANDARD (test harness + CI workflow; no runtime/capital path change)
Claim Level: NARROW INTEGRATION (resolver implemented + py_compile-clean; exercised live by the next staging-proof dispatch)
Validation Target: the staging proof no longer depends on operator-pinned `STAGING_TOKEN_ID`/`STAGING_MARKET_ID` secrets — it resolves a currently-OPEN, order-book-enabled market at runtime via the public CLOB read API.
Not in Scope: trading/execution code; the CLOB v2 backend; `ENABLE_LIVE_TRADING`/`allow_fills` (stay gated); choosing neg-risk markets (resolver deliberately skips them).
Suggested Next Step: re-dispatch `staging-proof-fly.yml` (case3, nrt, `USE_PYSDK_CLOB=1`, `allow_fills=0`) — the resolver should now place a real resting GTC on a live market, proving the kill-switch cancel end-to-end.

---

## 1. Problem

The previous run (#6, 27016636308) reached the broker on the CLOB v2 backend
(`order_version_mismatch` gone) but failed with `the orderbook does not exist`:
`STAGING_TOKEN_ID`/`STAGING_MARKET_ID` pointed at a market whose orderbook no
longer existed. Root cause is structural, not a one-off: the bot trades
short-lived RECURRING markets (5m/15m crypto up/down) whose `token_id`s resolve
and roll over every few minutes, so any market id pinned in a repo secret is stale
before the proof can run. Babysitting that secret by hand is unworkable.

## 2. Fix — resolve a live market at runtime

`tests/staging/test_live_reconcile_staging.py` now resolves the market itself when
the env override is absent:

- `_resolve_open_market()` — pages the public, unauthenticated CLOB `/markets`
  (`MarketDataClient`, no signing/creds/Redis) and keeps markets that are
  `active & !closed & accepting_orders & enable_order_book`, binary (2 tokens),
  NOT neg-risk. It prefers the longest-dated markets (so the book can't resolve
  mid-test), BUYs the higher-priced token (max headroom), and **verifies the
  token's `/book` carries an ask above the resting price** before accepting it —
  guaranteeing the test BUY rests instead of crossing.
- `_ensure_market_resolved()` — populates the `_TOKEN`/`_MARKET`/`_NO_TOKEN`/
  `_TICK`/`_NEG_RISK` module globals once (cached in `_RESOLVED`), honouring an
  explicit `STAGING_TOKEN_ID`+`STAGING_MARKET_ID` override when both are set.
- Called at the top of the `broker` fixture, so every order-placing case (1–4)
  gets a fresh live market; case5 (no broker) is untouched.

`STAGING_TOKEN_ID`/`STAGING_MARKET_ID`/`STAGING_NO_TOKEN_ID` are now **optional
overrides** (reproduce a specific market) rather than required secrets. The only
required staging secret remains `STAGING_WALLET_KEY`.

## 3. Files modified (full repo-root paths)

- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py` — `_RESOLVED`, `_resolve_open_market`, `_ensure_market_resolved`; `broker` fixture resolves before yielding; comment + `_need_market` message updated.
- `.github/workflows/staging-proof-fly.yml` — comment: market-id secrets now optional (auto-resolved); `STAGING_WALLET_KEY` is the only required staging secret. (No input/flow change — empty market envs simply trigger resolution.)
- `projects/polymarket/crusaderbot/docs/runbooks/warp74-staging-proof.md` — env table: token/market/no-token marked auto-resolved overrides.
- `projects/polymarket/crusaderbot/reports/forge/staging-market-autoresolve.md` — this report.
- `state/PROJECT_STATE.md`, `state/CHANGELOG.md` — lane sync.

## 4. What is working

- Harness `py_compile`-clean; resolver uses only the existing public-read
  `MarketDataClient` (no new deps).
- Backend-agnostic: resolution is independent of `USE_PYSDK_CLOB` (CLOB v2 or
  legacy). py-sdk re-derives tick/neg-risk from market truth regardless.
- Inert in CI: the whole module still skips without `STAGING_WALLET_KEY`, so the
  network resolver never runs on the hosted runner.

## 5. Known issues / boundaries

- Resolver skips neg-risk markets by design; if the entire open universe were
  neg-risk (not realistic) it raises a clear error — pin an override to bypass.
- Resting price stays `STAGING_REST_PRICE=0.10`; the resolver enforces the chosen
  token's best ask is comfortably above it, so a fill cannot occur.
- Live behaviour (an order actually resting + cancelled) is proven by the next
  dispatch, not in this container.

## 6. What is next

1. Re-dispatch `staging-proof-fly.yml` case3 (nrt, `USE_PYSDK_CLOB=1`, `allow_fills=0`).
2. Confirm a real GTC rests on the auto-resolved market, then the kill switch cancels it; then `all-broker` for cases 1–2–4.
3. Confirm `signature_type` proxy inference on the resting order; close/scope the GTC-only gap; pass all 5 cases before any LIVE flip.

---

Validation Handoff (NEXT PRIORITY): WARP🔹CMD review — STANDARD. Source: projects/polymarket/crusaderbot/reports/forge/staging-market-autoresolve.md. Re-dispatch the proof to validate live.
