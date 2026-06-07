# Feed Vendor Scoping — Weather + Playbook Dark Modules (WARP-80 Sub-Lane 1c')

**Branch:** WARP/feed-vendor-scoping
**Date:** 2026-06-07
**Role:** WARP•FORGE
**Validation Tier:** MINOR
**Claim Level:** FOUNDATION
**Validation Target:** Vendor research for 3 dark feed slots (Weather ensemble + InjuryAlpha + PublicFade). Zero code written; no vendor commitments made.
**Not in Scope:** Integration code, API key provisioning, MarketResolver wiring, threshold changes, ev_comparator / scorer_trainer / orchestrator paths.
**Suggested Next Step:** WARP🔹CMD reviews this report, decides per-module budget envelope, then greenlights wiring lane (1c integration) per module.

---

## 1. What Was Built (Investigation)

This is a pure research/scoping report. No code was written. The investigation:

1. Read `strategies/weather/forecast.py` to map which weather forecast sources are currently live and what the gap is.
2. Read `domain/playbook/modules.py`, `router.py`, `feeds.py`, and `feeds_http.py` to identify all 4 alpha modules, their feed dependencies, and which 2 are dark on `NullFeed`.
3. Retrieved Linear WARP-80 issue for the "opportunistic edge starvation" framing and confirmed the 1c deferred scope.
4. Researched current (2026) vendor pricing, API shapes, licensing, and realistic time-to-live for each dark feed slot.

---

## 2. Current System Architecture — Dark Module Analysis

### 2.1 The 4 Playbook Alpha Modules

| Module | Status | Feed Dependency | Phase |
|---|---|---|---|
| `closing_edge` | **LIVE** — Polymarket-native MVP | None (native orderbook) | Phase-1 shipped |
| `sharp_money` | **LIVE** — formula built; on-chain buffer wired (WARP/realtime-trade-buffer) | `heisenberg_buffer` (in-memory, WARP-82) | Phase-2b complete |
| `injury_alpha` | **DARK** — `InjuryAlphaModule.evaluate` abstains on `injury_present=False` | `SportsFeed.get_injury_event` -> `InjuryEvent` | Phase-2d, stub |
| `public_fade` | **DARK** — `PublicFadeModule.evaluate` abstains on `public_side == ""` | `SportsFeed.get_public_flow` -> `PublicFlow` | Phase-2e, stub |

The `feeds_http.py` module already ships reference adapters (`EspnInjuryFeed` + `OddsApiFeed`) and a factory `build_sports_feed()` that returns `NullFeed` unless flags are on AND a `MarketResolver` is supplied. The infrastructure is code-complete; the gap is: (a) feed flags off, (b) no `MarketResolver` wired, (c) no API keys provisioned.

### 2.2 Weather Strategy — Current Feed State

`strategies/weather/forecast.py` runs `fetch_all()` which calls three sources concurrently:

| Source | Status | Auth | Notes |
|---|---|---|---|
| Open-Meteo ECMWF model | **LIVE** — no key required | None | Free tier (non-commercial); ECMWF IFS 0.4 deg resolution |
| Open-Meteo HRRR model | **LIVE** (US cities only) | None | Free tier; CONUS only |
| Visual Crossing Timeline API | **CONDITIONAL** — live only if `VISUALCROSSING_API_KEY` is set | `VISUALCROSSING_API_KEY` env var | Skipped with a warning when key absent |
| METAR (aviationweather.gov) | **NOT wired** — `fetch_metar` is implemented but not called in `fetch_all()` | None | Would add current observation temperature; minor gap |

**The gap:** Open-Meteo free tier forbids commercial use. If CrusaderBot is deployed commercially, the ECMWF+HRRR calls are out-of-compliance without a paid Open-Meteo subscription. Visual Crossing is the paid ensemble source, and it only fires when the env key is set. If the key is absent in prod, the strategy runs on Open-Meteo only (two sources, both non-commercial).

Additionally, `fetch_all()` omits METAR, meaning the 3-source ensemble described in the code is actually a 2-source ensemble today for US cities and a 1-source ensemble for non-US.

### 2.3 How a Feed Would Plug In (Conceptual)

**Weather:** `VISUALCROSSING_API_KEY` is already the wiring point. Setting the key in Fly secrets activates VC as the third ensemble source immediately — no code change needed. For commercial Open-Meteo, swap the base URL to `customer-api.open-meteo.com` and add the `apikey` param.

**Injury Alpha + Public Fade:** `build_sports_feed(settings, resolver)` in `feeds_http.py` is the factory. Wiring requires:
1. Set `PLAYBOOK_INJURY_FEED_ENABLED=true` / `PLAYBOOK_PUBLIC_FEED_ENABLED=true` in Fly secrets.
2. Set `ODDS_API_KEY` in Fly secrets (for Public Fade).
3. Implement a `MarketResolver(market_id) -> FeedTarget | None` that maps Polymarket `market_id` strings to ESPN team IDs + Odds API event IDs. This is the non-trivial integration piece (~1-2 days of mapping work per sport covered).

---

## 3. Files Created / Modified

| File | Action |
|---|---|
| `projects/polymarket/crusaderbot/reports/forge/weather-playbook-feed-vendor-scoping.md` | Created (this report) |
| `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` | Updated (NEXT PRIORITY + Last Updated) |
| `projects/polymarket/crusaderbot/state/CHANGELOG.md` | Appended (one line) |

No source code was created or modified.

---

## 4. What Is Working (Findings)

### Weather Forecast — Recommended Path: Open-Meteo Commercial ($29/mo) + Visual Crossing Free Key

The free Open-Meteo tier already powers ECMWF+HRRR in prod. The commercial violation risk is real but low-severity today (paper trading, no real USDC). The cheapest compliant path is the Open-Meteo Standard plan at **$29/month** — it covers 1M calls/month, which is more than sufficient for 20-city hourly scans (~480 calls/day = ~14,400/month). Visual Crossing's free 1,000 records/day tier is enough to add it as the third ensemble source at no cost (1 call per city per day = 20 calls/day = ~600/month, well under the 1,000/day free limit).

### Injury Alpha — Recommended Path: ESPN Free Unofficial API (no cost; accept stability risk)

`EspnInjuryFeed` already uses ESPN's undocumented public endpoint (`site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}/injuries`). This is the only zero-cost path. The adapter is implemented and unit-tested. The risk is endpoint instability (no SLA, can be pulled without notice). For a paper-trading context this is the correct starting point.

### Public Fade — Recommended Path: The Odds API 20K plan ($30/mo)

`OddsApiFeed` is already implemented in `feeds_http.py`. It uses The Odds API's h2h odds from Pinnacle (sharp) vs DraftKings (soft) to construct a public-lean proxy. The Odds API 20K plan at **$30/month** covers the use case: 20 sports markets x hourly scan x 12 hours = ~240 calls/day = ~7,200/month, within the 20K credit budget.

---

## 5. Per-Module Vendor Comparison Tables

### 5a. Weather Forecast Feed

| Vendor | Cost (setup + monthly) | Integration Complexity | Licensing / Legal | Time-to-Live | Notes |
|---|---|---|---|---|---|
| **Open-Meteo free tier — current** | $0 | Already integrated | Non-commercial only — **violation risk for commercial deployment** | Live now | Must upgrade for compliance |
| **Open-Meteo Standard — RECOMMENDED** | $0 + **$29/mo** | Minimal: swap base URL + add `apikey` param | Commercial licence; CC BY 4.0 attribution required | ~1 day | Fixed price; 1M calls/mo; 99.9% SLA |
| **Open-Meteo Professional** | $0 + $99/mo | Same as Standard | Commercial + advanced datasets | ~1 day | Overkill for 20-city hourly scan |
| **Visual Crossing Free Tier** | $0 | Already integrated (set `VISUALCROSSING_API_KEY` env var) | Commercial attribution required | Minutes | 1,000 records/day free; sufficient for 20 cities/day |
| **Visual Crossing Professional** | $0 + $35/mo | Already integrated | Commercial; attribution on Pro tier | Minutes | 10M records/mo; 1 concurrent request |
| **NOAA / NWS API** | $0 (free, commercial OK) | New adapter required (different shape; US only) | Public domain; no attribution | 2-3 days | US cities only; GFS model; no key required |
| **Tomorrow.io** | $0 + ~$49/mo (est.) | New adapter | Commercial; proprietary model | 3-5 days | Better hyperlocal; pricing not publicly listed |

**Recommendation:** Set `VISUALCROSSING_API_KEY` immediately (free, zero code change) + upgrade Open-Meteo to Standard ($29/mo). Combined cost: **$29/mo**. Integration effort: < 2 hours.

No weather vendor exceeds $500/mo at any recommended tier. No CMD budget flag triggered for Weather.

---

### 5b. Injury Alpha Feed (`InjuryAlphaModule` — Phase-2d)

| Vendor | Cost | Integration Complexity | Licensing / Legal | Time-to-Live | Notes |
|---|---|---|---|---|---|
| **ESPN Unofficial API — RECOMMENDED (PAPER only)** | **$0** | Adapter code-complete (`EspnInjuryFeed` in `feeds_http.py`); only `MarketResolver` needed | No ToS for public endpoints; undocumented — can be pulled / IP-banned without notice; **NOT commercial-compliant** | 1-2 days (resolver only) | No key; no SLA; appropriate for PAPER only — see compliance note below |
| **Sportradar Injury API** | Custom enterprise pricing (contact sales; realistically **$1,000s/mo + annual commitment**, not low hundreds) | New adapter; OAuth; different JSON shape | Commercial licence; enterprise contract | 5-10 days | Industry standard; enterprise sports feeds routinely run into the thousands/mo — **assume CMD budget flag** |
| **OddsJam API (injury data)** | **~$500-$1,000+/mo est.** (enterprise; not publicly listed) | New adapter; proprietary shape | Custom commercial licence | 5-10 days | Includes injury data per docs; likely > $500/mo |
| **Stats Perform / Opta** | Custom enterprise (likely **> $500/mo**) | New adapter; XML/JSON feeds | Strict commercial; per-sport packages | 10-20 days | Gold standard for injury/lineup; expensive |

**Recommendation:** ESPN unofficial API via existing `EspnInjuryFeed` adapter for PAPER. Cost: **$0/mo**.

> COMPLIANCE NOTE (CMD DECISION): Recommending the undocumented ESPN endpoint at $0 is *inconsistent* with upgrading Open-Meteo to a paid tier for commercial compliance. The ESPN public API has no commercial ToS, no SLA, and can break or IP-ban without notice. It is fine for PAPER; for a commercial / LIVE deployment a licensed feed (Sportradar / Stats Perform) is advised. This compliance inconsistency is surfaced for CMD to decide explicitly — do not assume the $0 path is LIVE-safe.

> CMD BUDGET DECISION REQUIRED: A production-grade SLA-backed injury feed (Sportradar / OddsJam / Stats Perform) is enterprise-tier — realistically **$1,000s/month + annual commitment**, well above $500/mo. Do not procure without explicit CMD approval.

---

### 5c. Public Fade Feed (`PublicFadeModule` — Phase-2e)

| Vendor | Cost | Integration Complexity | Licensing / Legal | Time-to-Live | Notes |
|---|---|---|---|---|---|
| **The Odds API 20K plan — RECOMMENDED** | $0 + **$30/mo** | Adapter code-complete (`OddsApiFeed`); needs `ODDS_API_KEY` + `MarketResolver` | Developer ToS; commercial use permitted | 1-2 days | Pinnacle (sharp) vs DraftKings (soft) divergence proxy; 20K credits/mo; 40+ books; 70+ sports |
| **The Odds API 100K plan** | $59/mo | Same | Same | Same | Headroom for expanded coverage; not needed initially |
| **The Odds API Free Tier** | $0 | Same | Same | Same | 500 credits/mo — insufficient for hourly scan |
| **OddsJam API** | **~$500-$1,000+/mo est.** (not publicly listed) | New adapter | Custom commercial licence | 5-10 days | 100+ books; genuine public ticket % data; likely > $500/mo |
| **Action Network** | No API (website only) | Scraping — fragile, ToS violation risk | Not viable | N/A | Not a viable path |
| **SharpSports** (sharpsports.io) | Unlisted | New adapter | Commercial | 3-5 days | Sportsbook-integration / bet-tracking API; pricing unverified |

**Recommendation:** The Odds API 20K plan at **$30/mo** using existing `OddsApiFeed` adapter.

> CMD BUDGET DECISION REQUIRED: If CMD wants genuine ticket-count public betting percentages (beyond the Pinnacle/DraftKings soft/sharp proxy), vendors like OddsJam are estimated **> $500/month**. Do not procure without explicit CMD approval.

---

## 6. Summary: Recommended Options + Total Cost

| Module | Recommended Vendor | Monthly Cost | Code Change | Time-to-Live |
|---|---|---|---|---|
| **Weather ensemble** | Open-Meteo Standard + Visual Crossing free key | **$29/mo** | URL param change + set env key | < 1 day |
| **Injury Alpha** | ESPN unofficial API (free) † | **$0/mo** | MarketResolver only | 1-2 days |
| **Public Fade** | The Odds API 20K plan | **$30/mo** | `ODDS_API_KEY` + MarketResolver | 1-2 days |
| **Total** | | **$59/mo** | | |

† PAPER only — the ESPN endpoint is undocumented and NOT commercial-compliant (no ToS, no SLA, breakage/IP-ban risk). For commercial / LIVE it needs a licensed feed (enterprise-tier, $1,000s/mo). See the compliance note in §5b — surfaced for explicit CMD decision.

**No recommended vendor exceeds $500/month for the PAPER configuration. CMD budget flag NOT triggered for recommended options; a LIVE-compliant injury feed would change this (see §5b).**

> CONDITIONAL FLAG: Enterprise-grade alternatives (Sportradar injury feed, OddsJam public %) are estimated > $500/month each and require a separate explicit CMD budget decision before any procurement or integration work.

---

## Sources

- Open-Meteo pricing: https://open-meteo.com/en/pricing / https://openmeteo.substack.com/p/api-subscriptions-for-commercial
- Visual Crossing pricing: https://www.visualcrossing.com/weather-data-pricing/
- The Odds API pricing: https://the-odds-api.com/
- ESPN unofficial API: https://github.com/pseudo-r/Public-ESPN-API / https://scrapecreators.com/blog/espn-api-sports-data
- OddsJam API: https://oddsjam.com/odds-api
- Sportradar: https://developer.sportradar.com/api_pricing
- NOAA/NWS: https://www.weather.gov/documentation / https://weather-gov.github.io/api/general-faqs
