# WARP•R00T — scan-reject-classify

Follow-up patch to `WARP/root-rpc-watcher-hardening` (#1761), driven by live
post-deploy verification. Branch: `WARP/root-scan-reject-classify`.

- Validation Tier   : MAJOR
- Claim Level       : NARROW INTEGRATION
- Validation Target : eth_getLogs rejection classification + adaptive-span
  memory in `integrations/polygon.py` only.
- Not in Scope      : everything else (risk constants / guards / order paths /
  scheduler / custody untouched this lane).
- Suggested Next    : WARP•R00T merge on CI green; verify prod chain_cursor
  advances off block 0 after the CD deploy.

## 1. What was built

Post-deploy verification of #1761 against prod showed the scheduler healthy
(10 scan_runs/15min on version 3b2cc51, /health alchemy_rpc ok) but
chain_cursor STILL at block 0 — ticks kept failing. Root cause found in the
installed web3 7.16 source: `AsyncHTTPProvider.make_request ->
HTTPSessionManager.async_make_post_request -> response.raise_for_status()`
runs BEFORE the JSON-RPC body is parsed, so an Alchemy-class deterministic
range/size rejection of eth_getLogs (HTTP 400) surfaces as aiohttp
`ClientResponseError` — never `Web3RPCError`. The #1761 adaptive scan keyed
halving on `Web3RPCError` only and classified ALL ClientErrors as transport,
so the deterministic 400 reraised every tick and the cursor never advanced.

Fixes:
1. `_is_request_rejection`: ClientResponseError status 400/413/414 = a
   deterministic request-shape verdict → drives adaptive halving exactly like
   `Web3RPCError`. 429/5xx remain transport (retried, never halved).
2. `_should_retry` (replaces the type-only predicate): request rejections are
   NOT retried verbatim (replaying an identical rejected request cannot
   succeed); throttles/5xx/timeouts/conn errors still retry with backoff.
3. `_accepted_span` memory (per scanned token contract): the halving ladder
   is no longer re-walked from max_range on every tick — the scan starts at
   the last accepted span and probes upward (x2, capped) so a degraded plan
   does not pin the scan small forever. Process-local; a restart re-discovers
   the cap in one tick.

## 2. Current system architecture (relevant slice)

`scheduler.watch_deposits` (120s) → `polygon.scan_from_cursor` →
`scan_usdc_transfers` (eth_getLogs, retry+deadline per #1761). Rejection
taxonomy now: Web3RPCError | HTTP 400/413/414 → halve span (31-block floor);
HTTP 429/5xx | ClientError | TimeoutError → fail tick fast, retry next
interval; success → cursor advances, span remembered.

## 3. Files created / modified

- projects/polymarket/crusaderbot/integrations/polygon.py
- projects/polymarket/crusaderbot/tests/test_rpc_watcher_hardening.py
- projects/polymarket/crusaderbot/reports/forge/scan-reject-classify.md
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md,
  projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

17 tests in test_rpc_watcher_hardening.py green (4 new: 400-halves /
429-transport / span-memory / retry-classification table); deposit-watcher
regression green; ruff clean. Full-suite result recorded in PROJECT_STATE.

## 5. Known issues

If prod cursor still does not advance after this deploy, the failure is
outside the deterministic classes entirely — the #1761 context-rich log line
(stage+cursor+head+watched+lookback+repr) in Fly/Sentry is then the
single-read diagnosis. No other known issues introduced.

## 6. What is next

Merge on CI green → CD deploy → re-read prod chain_cursor (expect advance off
0 within ~2-4 min) → owner continues the gate-4 sequence (admin backfill,
deposit within lookback).
