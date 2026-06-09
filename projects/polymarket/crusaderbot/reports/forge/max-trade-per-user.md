# WARP•R00T FORGE REPORT — max-trade-per-user + polymarket-integration-audit

Branch: WARP/ROOT/max-trade-per-user
Date: 2026-05-30 01:48 Asia/Jakarta
Role: WARP•R00T (self-validated directly per WARP🔹CMD direction — no separate SENTINEL)

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : the per-user "Max trade setting" caps signal_following sizing (not just late_entry_v3); Polymarket integration audited for bugs/staleness
Not in Scope      : the CLOB tick-size/neg_risk fix (recommended next lane — see Remediation); live-arming
Suggested Next    : WARP🔹CMD decision on the tick-size/neg_risk lane (top pre-LIVE order-correctness item)

## 1. What was built (code change)
**Per-user Max trade setting now applies to signal_following (the default strategy).**
`services/signal_feed/signal_evaluator._resolve_size_usdc` previously capped a
signal-following trade only by `available_balance × capital_allocation_pct` and
IGNORED the user's explicit per-trade ceiling (`max_per_trade_mode/usdc/pct`).
Only `late_entry_v3` honored it (`resolve_per_trade_ceiling`), so a user who set
"max $X / Y% per trade" still got uncapped sizing on the default strategy.

Fix: `_resolve_size_usdc` now applies `resolve_per_trade_ceiling(...)` as an
additional `min()` cap **only for explicit `fixed`/`pct` modes**. `auto`/None is
unchanged — we deliberately do NOT impose the candle-strategy $25 default on
signal_following (that would shrink every default-strategy trade = regression).
Net: explicit caps are honored everywhere; auto users see no behavior change.

## 2. Polymarket integration audit (findings — code-as-truth)
Audited `integrations/clob/{adapter,auth,ws,market_data}.py`,
`integrations/polymarket.py`, `integrations/polygon{,_usdc}.py` against official
CLOB conventions (L1 EIP-712 / L2 HMAC, order routing, tick size, CTF redeem).

SOLID: L2 HMAC message order + base64 handling (`auth.py:182-208`); L1 ClobAuth
domain/struct (`auth.py:102-130`); auth-class errors not retried (`adapter.py:116`);
Gamma `condition_ids` plural + conditionId validation (`polymarket.py:264-280`);
empty-book sentinel guard (`polymarket.py:405-435`); CTF redeemPositions ABI/args
+ contract (`polymarket.py:36-49,614`); on-chain retry/backoff + USDC 6-dec +
nonce_lock + pending tag (post Lane 5).

REMEDIATION BACKLOG (NOT changed in this lane — all LIVE-gated, live is OFF):
- **CRITICAL (recommended next lane): no tick-size rounding / no neg_risk before
  signing.** `domain/execution/live.py:222,397` + `lifecycle.py:678` call
  `client.post_order(...)` without `tick_size`/`neg_risk`. `MarketDataClient.
  get_tick_size`/`get_neg_risk` (`market_data.py:117-136`) exist but have ZERO
  callers. A price not aligned to the market tick (0.01/0.001) is rejected by
  CLOB; neg-risk markets need a different Exchange contract. Fix = fetch tick +
  neg_risk per token, round the limit price to tick, pass both through
  `post_order` (adapter already accepts them, `adapter.py:292-303`). Deferred to
  its own lane because it threads a MarketDataClient into 3 money-path sites and
  warrants staging validation before live.
- **HIGH: legacy EOA-default order builder footgun.** `polymarket.py:479-561`
  (`_build_clob_client`/`prepare_live_order`/`submit_live_order`) builds
  `ClobClient` with NO signature_type/funder → defaults to EOA(0) while the
  account is a Gnosis Safe(2). Dead in the current live path (live.execute uses
  the adapter) but importable. Fix = delete the block (after confirming zero
  importers) or pass signature_type+funder. Left untouched: changing/removing it
  needs importer certainty I can't get against a live env without risk.
- **MEDIUM: `get_usdc_balance` unit heuristic** (`adapter.py:410-414`) guesses
  micro-units by `>1e6`; the field is documented raw 6-decimal. Left as-is — I
  can't verify the live API's exact return shape here, and a wrong flip would
  mis-read collateral. Verify against current docs, then make it unconditional.
- MEDIUM/LOW: WS silent auth-reject loop (`ws.py:256-284`); legacy `gasPrice` vs
  EIP-1559; rate-limit comments unverified. All advisory.

## 3. Files created / modified (full repo-root paths)
Modified:
- projects/polymarket/crusaderbot/services/signal_feed/signal_evaluator.py (_resolve_size_usdc applies explicit per-trade ceiling)
Created:
- projects/polymarket/crusaderbot/tests/test_max_per_trade_signal_following.py (5 tests)

## 4. What is working
- py_compile + ruff clean.
- 5/5 max-trade tests pass (fixed cap, pct cap, auto-not-capped, capital cap preserved, smaller-wins).
- 195 signal_following/evaluator/signal_scan regression tests pass.

## 5. Known issues
- Polymarket order-path tick-size/neg_risk CRITICAL is documented + deferred to a
  dedicated lane (live-gated, needs staging) — see §2.
- Grimoire/web3 venue CLI could not run in this sandbox (external binary + key);
  the integration was verified by code audit against official conventions.

## 6. What is next
- WARP🔹CMD: approve the tick-size/neg_risk order-correctness lane (top pre-LIVE item).
- Optional: legacy-builder removal + get_usdc_balance unit confirmation.

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
