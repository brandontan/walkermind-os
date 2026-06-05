# WARP-74 staging proof — resolve open market via Gamma (CLOB /markets had no active filter)

Validation Tier: STANDARD (test harness; no runtime/capital path change)
Claim Level: NARROW INTEGRATION (resolver rewritten + py_compile-clean; validated by the next dispatch)
Validation Target: `_resolve_open_market` must actually find a live OPEN market.
Not in Scope: trading/execution code; LIVE gating.
Suggested Next Step: re-dispatch `staging-proof-fly.yml` case3 (nrt, defaults).

---

## 1. Problem

Run #8 (with the stale secrets correctly blanked by `pin_market=false`) ran the
resolver and raised `could not resolve any open ... market`. Root cause: the
resolver paged the **CLOB `/markets`** endpoint, which has **no active filter** and
is a cursor dump over the entire historical (mostly closed) market set — 6 pages
from the start surfaced only closed markets, so nothing matched.

## 2. Fix

Rewrote `_resolve_open_market` to source candidates from the **Gamma API**
`GET https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume24hr&ascending=false&limit=500`
(direct `httpx`, no cache/Redis). This returns LIQUID, OPEN markets directly.

- Parse Gamma fields (`conditionId`, `clobTokenIds`, `outcomePrices` — JSON-string
  or list via `_parse_json_list`), skip neg-risk, require two binary tokens.
- Metadata flags (`enableOrderBook`/`acceptingOrders`) exclude only on an EXPLICIT
  `False` — the real gate is verifying the chosen token's CLOB `/book` has an ask
  above the resting price (so the BUY rests, never crosses).
- BUY the higher-priced outcome (headroom); prefer longest-dated (no mid-test
  resolution).

Field names verified against existing repo Gamma parsers
(`late_entry_v3`, `playbook`, `redeem_router`, `snapshots`, `candle_resolution`).
Gamma is geoblocked from the dev container (403) but reachable from the nrt Fly
machine (same host family as CLOB, which already works there).

## 3. Files modified (full repo-root paths)

- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py` — `_resolve_open_market` now Gamma-sourced; added `_parse_json_list`.
- `projects/polymarket/crusaderbot/reports/forge/staging-resolver-gamma.md` — this report.
- `state/PROJECT_STATE.md`, `state/CHANGELOG.md` — lane sync.

## 4. What is working

- `py_compile` clean. CLOB `/book` verification retained as the authoritative
  rest-safety gate. Inert in CI (module skips without `STAGING_WALLET_KEY`).

## 5. Known issues / boundaries

- Cannot validate the live Gamma response shape from the dev container (403);
  field names cross-checked against the repo's other Gamma consumers.
- If the whole top-volume universe were neg-risk (not realistic), it raises a clear
  error — pin a market with `pin_market=true` to override.

## 6. What is next

1. Re-dispatch `staging-proof-fly.yml` case3 (nrt, defaults) → resolver finds a live market; a real GTC should rest + kill switch cancel.
2. `all-broker` for cases 1–2–4; confirm `signature_type` proxy inference; close GTC-only gap; pass all 5 before any LIVE flip.

---

Validation Handoff (NEXT PRIORITY): WARP🔹CMD review — STANDARD. Source: projects/polymarket/crusaderbot/reports/forge/staging-resolver-gamma.md.
