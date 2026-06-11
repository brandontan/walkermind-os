# scan-provider-cap — deposit scanner survives ANY provider getLogs cap

Role: WARP•R00T (owner-assigned, /goal live-trade readiness 2026-06-11)
Branch: WARP/root-scan-provider-cap
Date: 2026-06-11 21:10 Asia/Jakarta

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : integrations/polygon.scan_from_cursor chunked adaptive scan; scheduler.watch_deposits budget threading + log redaction; monitoring/logging httpx quieting
Not in Scope      : order submit paths, risk constants, ENABLE_LIVE_TRADING + guards, kill switch, strategy entry/exit, migrations, confirmation/credit pipeline (`_record_pending_deposit` onward — byte-unchanged)
Suggested Next    : WARP•R00T merge on CI green (owner full-bypass directive) -> CD deploy -> verify prod chain_cursor advances off block 0

## 1. What was built

ROOT CAUSE OF THE 5-WEEK BLOCK-0 OUTAGE — PROVEN WITH THE PROVIDER'S OWN ERROR BODY.
Post-#1762 prod evidence (2026-06-11 13:45 UTC, streak 97): every tick still failed at
stage=scan with HTTP 400. Replaying the EXACT watcher request (same filter shape, same
endpoint, span 31) from this session returned the JSON-RPC body that web3 v7's
`raise_for_status()` discards:

> "Under the Free tier plan, you can make eth_getLogs requests with up to a **10 block
> range**. ... Upgrade to PAYG for expanded block range." (code -32600)

The configured Alchemy app is on the FREE tier: eth_getLogs caps at **10 blocks per
request**. The adaptive scan's floor was `_MIN_SCAN_RANGE = 31` — the halving ladder
bottomed out ABOVE the cap (1000→500→250→125→62→31, raise), so #1761/#1762 were
correct about the error class but the floor assumption ("a provider rejecting 31
blocks is not range-capped") was empirically false. `eth_blockNumber` succeeds on the
same key, which is why head reads worked while every scan failed.

FIX — provider-agnostic chunked scanning:
- `_MIN_SCAN_RANGE` 31 → 1. Only a provider rejecting a SINGLE-block range is broken.
- `scan_from_cursor` now walks the window in accepted-size CHUNKS under a per-call
  request budget (`max_rpc`, default 60; rejected probes count too). At a 10-block cap
  the ladder discovers span 7 and covers ~371 blocks on the first tick, ~420/tick at
  steady state vs ~240 produced per 120s — the cursor catches up and stays caught up.
  On an uncapped provider one or two requests still cover the whole window (previous
  behavior, same cost).
- Partial-coverage semantics: a transport failure or floor-rejection AFTER ≥1 accepted
  chunk returns the covered range (cursor advances; the failing offset is retried at
  the start of the next tick, where a zero-coverage repeat DOES raise and feeds the
  watch_deposits DOWN escalation). A budget burned entirely on rejections raises —
  never a silent empty success.
- `DEPOSIT_SCAN_MAX_RPC_PER_TICK` (config, default 60, env-tunable) threaded into both
  scan passes (usdc_deposits + usdc_native_deposits).
- Span memory (#1762 `_accepted_span`) preserved: ladder walked once, steady state
  opens at the proven span, upward probe after 5 clean calls.

SECURITY (same lane — found while reading the prod failure lines):
- RPC API key leak: aiohttp's `ClientResponseError` repr embeds the full request URL —
  Alchemy key included — and that repr reached Fly logs (+Sentry on escalation) via
  `_watch_deposits_failed` and the three scan_from_cursor log sites. New
  `polygon.redact_rpc_secrets()` (exception-safe by contract) scrubs every configured
  RPC URL's secret segments; applied at all four sites.
- Telegram bot token leak: httpx logs every request URL at INFO —
  `api.telegram.org/bot<TOKEN>/getUpdates` was verbatim in Fly logs.
  `configure_json_logging` now pins the `httpx` logger to WARNING.

Gemini #1763 review applied (both findings verified real): HIGH — empty query
string in a configured URL would have made `str.replace("", ...)` insert
`[redacted]` between every character of the log line (guarded); MED — the
probe-up streak now counts only clean FULL-WINDOW passes, so budget-exhausted
catch-up ticks never waste a probe request on a span the provider just capped.

## 2. Current system architecture (relevant slice)

```
watch_deposits (120s tick, APScheduler max_instances=1)
  wallets read -> head read -> cursor read -> scan_from_cursor -> record -> cursor advance
                                              |
                              latest_block (same RPC, works on Free tier)
                              chunk loop: budget=DEPOSIT_SCAN_MAX_RPC_PER_TICK
                                span ladder 1000..1 (rejection-halved, memory-pinned)
                                accepted chunks accumulate transfers, advance covered_to
                                transport/floor failure: keep partial coverage if any
                              zero coverage -> raise -> _watch_deposits_failed (redacted)
```

Failure-classification (unchanged from #1762): Web3RPCError or HTTP 400/413/414 =
deterministic rejection (halve); 429/5xx/timeouts/conn-drops = transport (retry
per-call, never halve, raise on zero coverage).

## 3. Files created / modified

- projects/polymarket/crusaderbot/integrations/polygon.py — redact_rpc_secrets; floor 31→1; chunked scan_from_cursor with max_rpc budget + partial coverage; redaction at 3 log sites
- projects/polymarket/crusaderbot/scheduler.py — max_rpc threaded into both scan passes; _watch_deposits_failed redacts err
- projects/polymarket/crusaderbot/config.py — DEPOSIT_SCAN_MAX_RPC_PER_TICK: int = 60
- projects/polymarket/crusaderbot/monitoring/logging.py — httpx logger pinned to WARNING
- projects/polymarket/crusaderbot/tests/test_rpc_watcher_hardening.py — 6 tests reshaped to the chunked contract + 7 new (ten-block prod cap, contiguous chunking, partial transport coverage, zero-coverage budget burn, redaction unit, watcher-line redaction, budget threading, httpx level, config default)
- projects/polymarket/crusaderbot/tests/test_deposit_e2e.py — fake_scan signatures accept max_rpc
- projects/polymarket/crusaderbot/reports/forge/scan-provider-cap.md — this report
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md / CHANGELOG.md — state sync

## 4. What is working

- 24/24 test_rpc_watcher_hardening.py green, incl. `test_scan_from_cursor_survives_ten_block_provider_cap` reproducing the exact prod cap shape (spans [1000,500,250,125,62,31,15] + [7]*53, cursor advances 371 blocks, span memory pins 7).
- 44/44 touched-surface regression green (deposit_e2e, main_logging, polygon_native_decode, watch_deposits_rescue, watcher_deposit_wallet, rpc_watcher_hardening).
- ruff clean on all touched files. Full suite run recorded below (section 6 / CI).
- Replay harness confirmed the EXACT Alchemy error text; a 10-block request against the same endpoint shape is the provider-documented accepted form.

### Post-deploy verification (2026-06-11 21:27 WIB, prod)

- Deploy b54846af8c72 live 14:23 UTC; first tick 14:25:41: ladder walked
  1000->...->15 (rejections logged WITH `[redacted]` in place of the API key —
  redaction verified live), span 7 accepted, chunks proceeded silently.
- chain_cursor.usdc_deposits: block 0 -> 88,272,761 (14:27:42 UTC);
  usdc_native_deposits: 0 -> 88,272,771. BOTH cursors advancing +420
  blocks/tick. THE 5-WEEK GATE-4 OUTAGE IS CLOSED IN PRODUCTION.
- Catch-up to head (~49k blocks behind, net ~360/tick): ~4-5h on the Free
  tier at the default budget.
- OWNER-DEPOSIT FINDING (changes the gate-4 runbook): Alchemy
  getAssetTransfers over the FULL history of the owner's bot deposit address
  0x5827edEf918dc6bf38D5b7D7bbf0A53dF5e8F808 (erc20 + external + internal)
  returns ZERO transfers ever — the reported $8.32 funding went to the
  owner's PERSONAL polymarket.com account, an address the bot does not (and
  after backfill still would not) watch. Gate 4 needs USDC.e (Polygon) sent
  to the bot deposit address shown in /wallet -> Deposit (or, post-backfill,
  the bot-user's resolved Polymarket deposit wallet). No lookback raise is
  needed for a fresh deposit — the watcher is live.

## 5. Known issues

- Catch-up speed on a 10-block-capped plan is ~420 blocks/tick (≈12-14h to drain the 50k lookback). `DEPOSIT_SCAN_MAX_RPC_PER_TICK` is env-tunable for faster catch-up; an Alchemy PAYG upgrade makes it instant (owner $ decision — code now works on EITHER).
- If the owner's funding deposit is older than DEPOSIT_SCAN_LOOKBACK_BLOCKS (~28h) at the time the cursor first advances, raise the lookback once via env (existing posture from #1759).
- The Alchemy key that leaked into historical Fly log lines should be rotated by the owner (logs retention exposes it even after this fix).

## 6. What is next

1. Merge on CI green (WARP•R00T full-bypass), CD deploys.
2. Verify prod: chain_cursor.usdc_deposits advances off 0 within ~4 min of boot; watch a tick log for chunked scan lines.
3. Ops continuation (this session): backfill deposit wallets (admin trigger #1758), confirm owner funding deposit credits, gate 4 flips.
4. Owner: rotate the Alchemy API key (historical log exposure), optionally upgrade plan for instant catch-up.
