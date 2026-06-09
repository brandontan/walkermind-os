# WARP•FORGE REPORT — heisenberg-survey

Branch: `WARP/ROOT/heisenberg-survey`
Role: WARP•R00T (research-only, no code)
Validation Tier: MINOR
Claim Level: FOUNDATION
Validation Target: Heisenberg agent integration survey — current state + ROI ranking
Not in Scope: code changes, new migrations, live trading logic
Suggested Next Step: WARP🔹CMD decision — set `HEISENBERG_API_TOKEN` in Fly.io secrets to activate all dormant agents; then decide whether to promote agent 585 social momentum from metadata flag to confidence multiplier (see section 6).

---

## 1. What was built

Research-only lane. No code written. Surveyed all Heisenberg agent integration
points in the codebase to answer: which agent delivers the highest ROI for making
the bot better, and what (if anything) is blocking it?

---

## 2. Current system architecture

All 4 agents are already coded and integrated. Every one is dormant because
`HEISENBERG_API_TOKEN` is not set in Fly.io secrets.

```text
HEISENBERG_API_TOKEN (not set)
        │
        ├─► Agent 574  jobs/market_sync.py          ← dormant
        │    every 30 min, upserts active markets (min_volume ≥ 50k)
        │
        ├─► Agent 575  jobs/market_signal_scanner.py ← dormant
        │    liquidity pre-screen: rejects volume_collapse_risk or very_low tier
        │
        ├─► Agent 568  jobs/market_signal_scanner.py ← dormant
        │    1h candlestick data → edge_finder (6h mean deviation >8%)
        │                        → momentum_reversal (3 consecutive candles)
        │
        └─► Agent 585  jobs/market_signal_scanner.py ← dormant
             social pulse enrichment: acceleration >1.2 AND author_diversity_pct >40
             → sets payload["social_momentum"] = True (non-blocking, metadata only)

Already active (copy-trade path):
  Agent 584  services/copy_trade/leaderboard_sync.py  ← uses same token
  Agent 581  services/copy_trade/wallet_360.py        ← uses same token
```

**Single blocker for all 6 agents: `HEISENBERG_API_TOKEN` not set.**

Setting the token activates the entire live signal pipeline
(`_run_heisenberg_signals` in `market_signal_scanner.py`) and the copy-trade
leaderboard + wallet 360 enrichment simultaneously.

---

## 3. Files created / modified

No files modified (research only).

Files surveyed:

```text
projects/polymarket/crusaderbot/services/heisenberg.py
projects/polymarket/crusaderbot/jobs/market_sync.py
projects/polymarket/crusaderbot/jobs/market_signal_scanner.py
projects/polymarket/crusaderbot/services/copy_trade/leaderboard_sync.py
projects/polymarket/crusaderbot/services/copy_trade/wallet_360.py
projects/polymarket/crusaderbot/config.py
projects/polymarket/crusaderbot/.env.example
```

---

## 4. What is working

All 6 Heisenberg agents (574, 575, 568, 585, 584, 581) are integrated and
code-complete. The implementation is dormant pending `HEISENBERG_API_TOKEN`
configuration — no signals emitted, no leaderboard sync, no wallet 360 enrichment.

### Agent ROI ranking

### #1 — Agent 568 (Candlesticks) — HIGHEST ROI

**What it does**: delivers per-token 1h OHLC data, which powers the two live
signal types: `edge_finder` (price deviated >8% from 6h rolling mean → trade
against it) and `momentum_reversal` (3 consecutive candles trending → follow
direction).

**Why it is #1**: without candles, `_run_heisenberg_signals` exits immediately at
the candlestick fetch (`if len(candle_results) < 6: continue`). Agents 575 and
585 are gating/enrichment layers — they only fire AFTER candlestick data exists.
Agent 568 is the beating heart of the live Heisenberg signal path.

**Current state**: code complete, fully wired, zero signals emitted because token
is unset.

**Gap worth noting**: the edge_finder and momentum_reversal signal types produced
by this path are meaningfully different from the demo path's crude
`oneDayPriceChange / oneHourPriceChange` proxy — real OHLC data on a per-token
basis vs a single Gamma price field. This is a qualitative signal quality upgrade.

---

### #2 — Agent 575 (Market Insights) — HIGH ROI / risk reduction

**What it does**: liquidity screen — checks `volume_collapse_risk_flag` and
`liquidity_tier` before wasting a candlestick fetch on a thin market.

**Why it is #2**: it does not generate signals — it prevents bad entries. Without
it the live path fetches candles on every market regardless of liquidity health,
which means signals on near-dry markets are emitted and traded. Combined with 568,
this is critical risk hygiene.

**Current state**: code complete, wired as step A in `_run_heisenberg_signals`.

---

### #3 — Agent 585 (Social Pulse) — MEDIUM ROI, highest upside for NEW work

**What it does**: keywords extracted from the market question are sent to the social
pulse agent; if `acceleration > 1.2` AND `author_diversity_pct > 40` it sets
`payload["social_momentum"] = True`.

**Why it is #3 now**: the flag is currently metadata only — it flows into the
`signal_publications.payload` JSONB column but no downstream code reads it. The
risk gate, position sizer, and signal_following consumer all ignore it. So the
current value of 585 is zero beyond logging.

**Why it has the highest upside**: if the `social_momentum` flag were wired into
confidence scoring (e.g. `confidence += 0.05` when True, capped at 0.90), it would
become a legitimate signal booster. That is a small code change with a clear
mechanism for improvement. See section 6.

---

### #4 — Agent 574 (Markets) — FOUNDATIONAL, partially redundant

**What it does**: pulls active Polymarket markets with `min_volume ≥ 50k` and
upserts them into the `markets` table (is_demo=FALSE). Runs every 30 minutes.

**Why it is #4**: the demo path (`edge_finder` via Polymarket Gamma API) already
populates the `markets` table with real conditionIds and prices via `_upsert_market`
in `market_signal_scanner.py`. Agent 574 adds Heisenberg-curated high-volume markets
as an independent source, which is valuable for expanding the live feed's market
coverage — but the live signal path in `_run_heisenberg_signals` reads from the
existing `markets` table (`WHERE is_demo=FALSE AND resolved=FALSE`), which 574 also
writes to. Both sources converge at the same table.

**Current state**: code complete, wired, scheduled at 1800s via `heisenberg_market_sync`.

---

## 5. Known issues

- **Field name assumptions**: `heisenberg.py` and `market_sync.py` use field aliases
  like `side_a_implied`, `side_a_token_id`, `volume_collapse_risk_flag`,
  `liquidity_tier`, `acceleration`, `author_diversity_pct`, `c`/`close` for candle
  close. If the actual Heisenberg API returns different field names, upserts fall back
  to defaults (0.50 prices, null tokens, skipped enrichment) with no crash — but live
  signals may be lower quality until field names are confirmed against real responses.

- **social_momentum flag unused downstream**: agent 585 adds the flag to the payload
  but nothing reads it. Zero improvement to signal quality until wired (see section 6).

- **Live path market coverage**: `_run_heisenberg_signals` reads up to
  `LIVE_MARKETS_PER_CYCLE = 20` markets per tick from the DB. On a fresh deploy with
  no Heisenberg-sourced rows yet, it will scan whatever the demo path or agent 574
  has populated. Both paths write to the same table — no gap.

---

## 6. What is next

### Immediate (highest ROI, zero code)

Set `HEISENBERG_API_TOKEN` in Fly.io secrets:
```bash
fly secrets set HEISENBERG_API_TOKEN=<token> -a crusaderbot
```
This activates 574 + 575 + 568 + 585 + 584 + 581 in a single deploy. The live
signal path, leaderboard sync, and wallet 360 enrichment all come online together.

After deploy: tail logs for `heisenberg_market_sync` (expect upsert count > 0) and
`live_signal_published` events in `market_signal_scanner`. If field names differ from
assumptions, adjust the alias lookups in `market_sync.py` lines 58-94 and the
`volume_collapse_risk_flag` / `liquidity_tier` checks in `_run_heisenberg_signals`.

### Next code lane (highest ROI for new work)

**Wire agent 585 social momentum into confidence scoring.**

Current behaviour (`market_signal_scanner.py:345`):
```python
payload["social_momentum"] = True
```
Nothing downstream reads this.

Proposed change (1 line in `_run_heisenberg_signals`, after social enrichment):
```python
if payload.get("social_momentum"):
    payload["confidence"] = min(payload["confidence"] + 0.05, 0.90)
```
This elevates the default confidence from 0.65 → 0.70 when social chatter aligns
with the price signal — a principled boost with a hard cap. The `signal_scan_job`
already passes `confidence` into `_resolve_size_usdc` (via `SignalCandidate`), so a
higher confidence directly increases the trade size within the user's
`capital_alloc_pct` ceiling. No migration, no schema change.

This is the only agent enhancement that is both small and creates a real feedback loop
from Heisenberg data into position sizing.

---

## Recommendation summary

| Action | Agent | Effort | Impact |
|---|---|---|---|
| Set HEISENBERG_API_TOKEN (Fly secrets) | 574+575+568+585+584+581 | zero code | HIGH — entire dormant pipeline activates |
| Wire 585 confidence multiplier | 585 | 1 line | MEDIUM — signal quality boost with measurable mechanism |
| No action needed | 574, 575, 568 | — | Already coded correctly |

**Bottom line**: the bot is one `fly secrets set` away from having real candlestick-driven
live signals, liquidity screening, social enrichment, a leaderboard, and wallet 360 analytics
all active simultaneously. The only meaningful NEW code is the one-line confidence bump for
agent 585 — which converts an existing metadata flag into an actual trade-sizing effect.

---

Validation Tier: **MINOR** — research report, no runtime change
Claim Level: **FOUNDATION** — audit of existing integration state
Validation Target: all Heisenberg agent call sites (574/568/575/585/584/581), token guard paths, live signal pipeline entrypoint
Not in Scope: trading logic, risk gate, execution engine, frontend
Suggested Next Step: WARP🔹CMD sets `HEISENBERG_API_TOKEN` via `fly secrets set`, then decides on the 585 confidence-multiplier lane (1-line change, ~5 regression tests).
