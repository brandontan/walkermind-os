# 24_32_fix_market_title_resolution_from_id

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - market context builder
  - Falcon ingestion normalization
  - portfolio payload title field source (`market_title`)
- Not in Scope:
  - execution logic
  - strategy logic
  - Telegram layout changes
  - analytics
- Suggested Next Step: Auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_32_fix_market_title_resolution_from_id.md`. Tier: STANDARD

## 1. What was built
- Implemented deterministic market title resolution from `market_id` in Falcon ingestion normalization so title derives from Falcon market metadata fields (`market_title` / `title` / `question` / `name`) instead of staying empty.
- Added safe in-memory `market_id -> market_title` cache in Falcon ingestion to avoid repeated fallback misses and improve repeated resolution stability.
- Updated market-context builder fallback behavior:
  - Uses cached title first when API fails.
  - Uses strict placeholder `Market {id}` only when API fails and no cache title exists.
- Preserved portfolio payload field contract (`market_title`) without formatter/layout changes.

## 2. Current system architecture
1. `data/ingestion/falcon_alpha.py`
   - Falcon fetchers retrieve market/trade/candle/orderbook rows.
   - Normalizer now resolves and persists `market_title` from market metadata and caches by `market_id`.
   - Fallback payload now carries cached title or strict placeholder only on API failure.
2. `data/market_context.py`
   - Internal market context attempts direct Polymarket title resolution.
   - On failure, returns cached title from local/Falcon cache before placeholder.
   - `get_market_context_with_external_alpha` keeps `market_title` authoritative for downstream portfolio payload.
3. Portfolio payload path remains unchanged structurally; it receives improved upstream `market_title` value.

## 3. Files created / modified (full paths)
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/data/ingestion/falcon_alpha.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/data/market_context.py`
- Modified: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/tests/test_p14_2_external_alpha_ingestion_falcon_20260409.py`
- Created: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_32_fix_market_title_resolution_from_id.md`
- Modified: `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. What is working
### Required tests
1. valid `market_id` resolves correct title: pass
2. multiple markets resolve all correct titles: pass
3. fallback placeholder only when API unavailable and no cached title: pass
4. no regression to numeric-only display contract in resolved payload path: pass

### Validation commands
- `python -m py_compile projects/polymarket/polyquantbot/data/market_context.py projects/polymarket/polyquantbot/data/ingestion/falcon_alpha.py projects/polymarket/polyquantbot/tests/test_p14_2_external_alpha_ingestion_falcon_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_p14_2_external_alpha_ingestion_falcon_20260409.py` ✅ (`7 passed`)

### Runtime proof
- BEFORE: `Market 540816`
- AFTER: `Will BTC close above $120k in 2026?`
- MULTI: `m100 -> Will ETH close above $6k? | m200 -> Will SOL close above $300?`

## 5. Known issues
- Environment-level pytest warning persists: `Unknown config option: asyncio_mode`.
- Runtime proof script in this environment logs Polymarket network unavailability warning before Falcon title resolution fallback path completes.

## 6. What is next
- Auto PR review + COMMANDER review required before merge.
- Optional next increment (only if requested): centralize title cache between Polymarket and Falcon sources behind one typed cache adapter.

Report: projects/polymarket/polyquantbot/reports/forge/24_32_fix_market_title_resolution_from_id.md
State: PROJECT_STATE.md updated
