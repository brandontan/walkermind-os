# WARP•FORGE Report — category-mapping

**Branch:** claude/fervent-hawking-yNP0Z  
**Validation Tier:** STANDARD  
**Claim Level:** NARROW INTEGRATION  
**Validation Target:** `integrations/polymarket.get_events_with_markets()`; `services/signal_scan/signal_scan_job._fetch_markets_for_lib_strategies()`; `_filter_markets_by_category()` (unchanged)  
**Not in Scope:** market_signal_scanner demo path (uses `get_markets()` directly); DB-stored `markets.category` column; dashboard frontend category selector  

---

## 1. What was built

**Lane 1 — category mapping via Gamma /events.**

Beta testers reported "I select all categories but only see 2" (categories filter non-functional). Root cause:

- `_fetch_markets_for_lib_strategies()` called `get_markets(limit=200)` → Gamma `/markets` endpoint.
- Gamma `/markets` dicts contain NO `category` field and NO `tags` — only `groupItemTitle` (item-specific description like "New Rihanna Album") and `slug` (market-specific slug like `"will-btc-hit-100k-926"`).
- `_filter_markets_by_category()` does `any(f in cat for f in lower)` where `cat` falls through to `groupItemTitle` or `slug` — neither contains taxonomy keywords like "crypto", "politics", "sports".
- Result: every category filter produced zero or near-zero matches.

**The fix:**

Gamma's `/events` endpoint (confirmed accessible in this session) carries event-level `tags` with labels like `"Crypto"`, `"Finance"`, `"Politics"`, `"Sports"` that map directly to the dashboard categories. Each event also includes a `markets` array.

**`integrations/polymarket.get_events_with_markets(limit)`** — new function:
1. Fetches `GET /events?active=true&closed=false&limit=N`
2. For each event, builds `category = " ".join(tag_labels).lower()` from the event's tags (the generic `"All"` tag is excluded)
3. Falls back to `event.category` if no useful tags exist
4. Returns each market in `event.markets` annotated with `{**market, "category": category}`
5. Cached 5 minutes (same TTL as `get_markets()`)

**`services/signal_scan/signal_scan_job._fetch_markets_for_lib_strategies()`** — swapped call:
- `get_markets(limit=200)` → `get_events_with_markets(limit=200)`

`_filter_markets_by_category()` is unchanged — it already checks `m.get("category")` first, so once the category field is populated correctly, it works.

---

## 2. Current system architecture

```
run_once()
  ├── _fetch_markets_for_lib_strategies()
  │     └── get_events_with_markets(limit=200)   ← WAS: get_markets(limit=200)
  │           ├── GET /events?active=true&closed=false&limit=200
  │           └── for each event:
  │                 tag_labels = [t.label for t in event.tags if slug != "all"]
  │                 category = " ".join(tag_labels).lower()
  │                 yield {**market, "category": category}
  │
  └── for each user:
        user_markets = _filter_markets_by_category(markets, user.category_filters)
        # "crypto" now matches markets whose event has a "Crypto" tag ✓
```

---

## 3. Files created / modified

| Action   | Path |
|----------|------|
| Modified | `projects/polymarket/crusaderbot/integrations/polymarket.py` |
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` |
| Created  | `projects/polymarket/crusaderbot/tests/test_category_mapping.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/category-mapping.md` |

**polymarket.py** — `get_events_with_markets()` added after `get_markets()` (~40 lines).

**signal_scan_job.py** — `_fetch_markets_for_lib_strategies()` docstring updated + `get_markets` call replaced with `get_events_with_markets`.

**test_category_mapping.py** — 14 hermetic tests: `get_events_with_markets` annotation (7 cases), `_filter_markets_by_category` with annotated dicts (4 cases), `_fetch_markets_for_lib_strategies` wiring (2 cases).

---

## 4. What is working

- py_compile clean on all 3 modified/created Python files.
- `get_events_with_markets()` annotates each market with lowercase space-joined tag labels.
- "All" tag excluded from category string (prevents generic noise in substring matching).
- Fallback to `event.category` field when no specific tags are present.
- Markets from events with no tags and no category get `category = ""` — they pass empty-filter queries but are correctly excluded when a specific filter is set.
- HTTP failure degrades gracefully to `[]` (lib strategies handle empty input).
- `_filter_markets_by_category(markets, ["crypto"])` now correctly matches markets from events tagged "Crypto", "Crypto Prices", "BTC", "ETH", etc.
- `_filter_markets_by_category(markets, ["sports"])` matches "Sports" events and excludes crypto, finance, etc.
- Cache TTL 5 min (same as `get_markets`) — no per-tick HTTP overhead.
- Existing `test_signal_scan_job.py` `_filter_markets_by_category` tests unaffected (they test the function directly with pre-set `category` fields).

---

## 5. Known issues

- The `/events` endpoint returns up to `limit` events, not markets. If an event has 10 markets, `limit=200` returns up to 2000 market dicts. For now this is acceptable; it can be tuned with an env knob if needed.
- The `market_signal_scanner.run_job()` demo path still uses `get_markets()` directly (fetches from `/markets`). That path uses `outcomePrices` for live pricing and does not use `_filter_markets_by_category`, so it is unaffected by this lane. A follow-up may optionally enrich it with event tags if category filtering is needed there too.
- pytest not executable in this container (asyncpg/telegram deps absent). Logic verified via py_compile + asyncio.run on isolated test helpers. WARP🔹CMD or CI should run `pytest projects/polymarket/crusaderbot/tests/test_category_mapping.py` before merge.

---

## 6. What is next

- Post-deploy: confirm that a user with `category_filters = ["crypto"]` now receives crypto market candidates instead of zero.
- Optional follow-up: enrich `market_signal_scanner.run_job()` demo path with event tags if needed.
- Lane 2 (WARP-TDC signal diversity) and Lane 3 (edge model) are now both in this branch — suggest one PR covers all three lanes or WARP🔹CMD decides on split.

---

**Suggested Next Step:** WARP🔹CMD review → merge → Fly redeploy → confirm category filters produce non-zero market sets.

**Validation Tier:** STANDARD  
**Claim Level:** NARROW INTEGRATION
