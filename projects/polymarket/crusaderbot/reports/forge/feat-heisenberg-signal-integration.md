# WARP•FORGE REPORT — feat-heisenberg-signal-integration

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Heisenberg API client, market_sync job, market_signal_scanner live path, env wiring
Not in Scope: Live trading execution, CLOB integration, signal_following strategy execution, real capital deployment
Suggested Next Step: WARP🔹CMD review required. Deploy HEISENBERG_API_TOKEN secret via `fly secrets set`, then apply migration 025.

---

## 1. What Was Built

**Heisenberg API integration** — connects CrusaderBot's signal pipeline to real Polymarket data via the Heisenberg / Falcon parameterized-retrieval API.

Four components:

| Component | Role |
|---|---|
| `services/heisenberg.py` | Thin async HTTP client wrapping `POST /api/v2/semantic/retrieve/parameterized` |
| `jobs/market_sync.py` | 30-minute job syncing real active markets via agent 574 |
| `jobs/market_signal_scanner.py` | Extended with live signal path using agents 575 + 568 + 585 |
| `migrations/025_heisenberg_live_feed.sql` | Seeds CrusaderBot Live Feed (slug: `crusaderbot-live`) |

**Token guard**: both `market_sync` and the live scanner path check `HEISENBERG_API_TOKEN` at job start. If unset: log warning + skip cycle — no crash, no blocking the demo path.

---

## 2. Current System Architecture

```
DATA LAYER
  Heisenberg agent 574  →  jobs/market_sync.py     →  markets table (is_demo=FALSE)
  Heisenberg agent 575  →  liquidity screen         →  skip low-quality markets
  Heisenberg agent 568  →  candlestick price data   →  signal logic
  Heisenberg agent 585  →  social pulse (optional)  →  payload enrichment

SIGNAL LAYER
  jobs/market_signal_scanner.py
    Demo path  →  Polymarket API prices  →  DEMO_FEED_ID  →  is_demo=TRUE
    Live path  →  Heisenberg agents      →  LIVE_FEED_ID  →  is_demo=FALSE

DOWNSTREAM (unchanged)
  signal_publications  →  signal_following_scan  →  execution
```

Signal logic (live path):
- **edge_finder**: latest hourly close deviates > 8% from 6h rolling mean → signal
- **momentum_reversal**: 3 consecutive candles in same direction → signal
- **social_momentum**: enrichment flag when acceleration > 1.2 AND author_diversity_pct > 40

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| Created | `projects/polymarket/crusaderbot/services/heisenberg.py` |
| Created | `projects/polymarket/crusaderbot/jobs/market_sync.py` |
| Modified | `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py` |
| Modified | `projects/polymarket/crusaderbot/config.py` |
| Modified | `projects/polymarket/crusaderbot/.env.example` |
| Modified | `projects/polymarket/crusaderbot/fly.toml` |
| Modified | `projects/polymarket/crusaderbot/scheduler.py` |
| Created | `projects/polymarket/crusaderbot/migrations/025_heisenberg_live_feed.sql` |

---

## 4. What Is Working

- `services/heisenberg.py` client: async `retrieve(agent_id, params, limit)` → `data.results`; raises on non-2xx; returns `[]` if token unset; logs `agent_id + param_keys` (no token in logs).
- `jobs/market_sync.py`: calls agent 574 with `{"closed":"False","min_volume":"50000"}`, upserts real markets using `condition_id` as PK, defaults `yes_price/no_price=0.50` when absent, `is_demo=FALSE`, scheduled every 1800s via `heisenberg_market_sync` job ID.
- `jobs/market_signal_scanner.py`: demo path preserved intact; live path added: liquidity screen (agent 575) → candlestick fetch (agent 568) → edge_finder + momentum_reversal logic → optional social pulse (agent 585, non-blocking) → publish to `LIVE_FEED_ID` with `is_demo=FALSE`.
- `HEISENBERG_API_TOKEN` wired: `config.py` `Optional[str]`, `.env.example` entry, `fly.toml` placeholder.
- Migration 025: creates `CrusaderBot Live Feed` (UUID `00000000-0000-0000-0002-000000000001`, slug `crusaderbot-live`), idempotent.

---

## 5. Known Issues

- Heisenberg response field names assumed from task spec (`side_a_implied`, `side_a_token_id`, `end_date`, `volume_collapse_risk_flag`, `liquidity_tier`, `acceleration`, `author_diversity_pct`, `c`/`close` for candle close). If actual field names differ, upsert will fall back to defaults (0.50 prices, null tokens) — no crash.
- Migration 025 inserts no row if the `users` table is empty (fresh DB before first user signup). In that case `_live_feed_is_active()` returns False and the live scan logs a warning and skips. Apply migration after first user row exists.
- Branch is `claude/heisenberg-api-integration-cYG75` (harness-assigned) rather than declared `WARP/FEAT-HEISENBERG-SIGNAL-INTEGRATION`. Mismatch noted — harness override acknowledged.

---

## 6. What Is Next

- Deploy `HEISENBERG_API_TOKEN` secret: `fly secrets set HEISENBERG_API_TOKEN=<token> -a crusaderbot`
- Apply migration 025 (after at least one user row exists): `psql $DATABASE_URL -f migrations/025_heisenberg_live_feed.sql`
- Monitor `heisenberg_market_sync` job logs after deploy to confirm agent 574 returns markets and upsert count > 0
- Monitor `market_signal_scanner` live path logs for real signal publications
- If Heisenberg field names differ from assumptions, update `_safe_float`/field lookups in `market_sync.py` and scanner accordingly
