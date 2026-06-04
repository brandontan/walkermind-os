# WARP•FORGE Report — oracle-chainlink-client

Role: WARP•R00T (operating as WARP•FORGE for this build lane)
Branch: WARP/ROOT/oracle-chainlink-client
Linear: WARP-62 (Chunk 1/4) · Parent: WARP-61 · Blocks: WARP-64 (Chunk 3)
Date: 2026-06-04 09:18 Asia/Jakarta

Validation Tier   : STANDARD
Claim Level       : FOUNDATION
Validation Target : domain/strategy/oracle/ price-read + price_to_beat capture
                    + config knobs, in isolation (network stubbed). Decoding,
                    HMAC signing, flag-gating, and the price_to_beat parser.
Not in Scope      : Fair-value / edge calculator (Chunk 2), strategy wiring into
                    late_entry_v3 / signal_scan / scheduler (Chunk 3, WARP-64),
                    live trading, real network calls, ORACLE_ENABLED=true runtime.
Suggested Next    : WARP🔹CMD review.

---

## 1. What was built

The foundation of the candle oracle layer: an async, pull-based client that
reads **the same price source the Polymarket BTC up/down candle markets resolve
against** — the Chainlink BTC/USD Data Stream
(`data.chain.link/streams/btc-usd`) — plus a pure parser that captures each
market's candle-open **"Price to Beat"**. This is the missing BTC price
reference identified in the WARP-61 knowledge-graph audit (no `crypto_price` /
`chainlink` / `candle_open` node existed anywhere in the signal path).

Scope is strictly Chunk 1: read the live price and capture the baseline. No fair
value, no edge math, no strategy wiring. Every runtime entrypoint is gated
behind a new `ORACLE_ENABLED` feature flag that defaults **OFF**, so nothing in
the running system changes until the operator opts in (and provisions
credentials).

Anti-fake-data posture (consistent with the prior `kill-fabricated-prices`
lane): the client **never** returns a placeholder price. A missing/undecodable
report raises a typed `OracleUnavailableError`; a missing baseline returns
`None` for the caller to skip. No `0.50`-style fabrication path exists.

## 2. Current system architecture (relevant slice)

New package `projects/polymarket/crusaderbot/domain/strategy/oracle/`:

```
oracle/
├── __init__.py        public surface (client, errors, get_btc_price,
│                      get_price_to_beat, decode_benchmark_price, ...)
├── chainlink.py       ChainlinkDataStreamsClient + HMAC signer + report
│                      decoder + settings-driven, flag-gated entrypoint
└── price_to_beat.py   pure get_price_to_beat(market) capture
```

Data flow (when ORACLE_ENABLED, future chunks):

```
get_btc_price()
  └─ client_from_settings()           # ORACLE_ENABLED gate + .env creds
       └─ ChainlinkDataStreamsClient
            ├─ _signed_request()       # HMAC-SHA256 headers (ts in ms)
            ├─ transport(url,hdrs,to)  # httpx + tenacity retry/backoff (seam)
            ├─ fetch_latest_report()   # validates {report:{fullReport}}
            └─ decode_benchmark_price  # ABI envelope -> v3 blob -> price/1e18
```

The `transport` is an injectable async seam: production uses an httpx client
wrapped in `tenacity` retry (3 attempts, exponential 1→8s backoff, retry on
`httpx.HTTPError`/`TimeoutException`); tests inject a stub so no socket opens.
This mirrors the existing `integrations/polymarket.py` `_retry()` pattern.

`get_price_to_beat(market)` is pure (no I/O): explicit numeric fields first
(`priceToBeat`/`openPrice`/`strikePrice`/…), then a sanity-banded
($1k–$100M) USD figure parsed from `question`/`title`/`description`, else
`None`.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/strategy/oracle/__init__.py`
- `projects/polymarket/crusaderbot/domain/strategy/oracle/chainlink.py`
- `projects/polymarket/crusaderbot/domain/strategy/oracle/price_to_beat.py`
- `projects/polymarket/crusaderbot/tests/test_oracle_chainlink.py`

Modified:
- `projects/polymarket/crusaderbot/config.py` — added `ORACLE_ENABLED`,
  `ORACLE_CHAINLINK_API_URL`, `ORACLE_CHAINLINK_BTC_FEED_ID`,
  `ORACLE_TIMEOUT_SEC`, `CHAINLINK_DATASTREAMS_API_KEY`,
  `CHAINLINK_DATASTREAMS_API_SECRET` (all default OFF/None; creds `.env`-only).

State files:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `decode_benchmark_price` round-trips an ABI-encoded v3 report to the exact
  USD price (`104250.5` → `104250.5`); rejects bad hex and garbage blobs.
- `ChainlinkDataStreamsClient.get_btc_price()` returns the live price via the
  stubbed transport; honours the injected timeout.
- `fetch_latest_report()` raises `OracleUnavailableError` on a transport error
  and on a response missing `fullReport` (no silent None).
- Non-positive decoded price raises (never traded as real).
- `build_hmac_signature` matches an independently-computed HMAC reference;
  signed request carries `Authorization` / `X-Authorization-Timestamp` /
  `X-Authorization-Signature-SHA256`.
- `client_from_settings()` raises `OracleDisabledError` when `ORACLE_ENABLED`
  is OFF (default), `OracleConfigError` when enabled-but-no-creds, and builds
  the client when enabled with creds.
- `get_price_to_beat` returns the value from explicit fields, from question
  text, `None` when absent, rejects out-of-band figures, and prefers explicit
  fields over text.
- 18/18 unit tests pass; `ruff check` clean; `py_compile` clean. Network fully
  stubbed.

## 5. Known issues

- `ORACLE_CHAINLINK_BTC_FEED_ID` ships with the documented mainnet BTC/USD v3
  Data Streams feed ID as a default; the operator must confirm/override it for
  the deployed network before enabling. It is a config knob precisely so this
  is an operator decision, not a hardcoded assumption.
- Decoder targets the v3 (crypto) report schema (price/bid/ask). Other schema
  versions (e.g. v4 RWA) are out of scope for BTC/USD and would need a schema
  switch if a non-v3 feed is ever configured.
- No live network call has been exercised (foundation, flag OFF). End-to-end
  validation against the real Data Streams endpoint is deferred to operator
  enablement, after credentials are provisioned.

## 6. What is next

- Chunk 2/4: fair-value / edge calculator (`delta`, `z`, `Phi(z)`, `edge_up`/
  `edge_down`) — consumes `get_btc_price()` + `get_price_to_beat()`. NOT started
  here per chunk scope.
- Chunk 3/4 (WARP-64): wire the oracle + edge gate into `late_entry_v3` presets
  (Distance / Min Edge / Trend). Blocked on this lane + Chunk 2.
- Operator pre-activation (later): set `CHAINLINK_DATASTREAMS_API_KEY` /
  `_SECRET` in Fly secrets, confirm `ORACLE_CHAINLINK_BTC_FEED_ID`, then flip
  `ORACLE_ENABLED=true`.
