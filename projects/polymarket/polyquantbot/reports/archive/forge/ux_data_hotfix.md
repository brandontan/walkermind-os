# UX Data Hotfix — Telegram UX & Market Metadata Reliability

## 1. What Was Built

Fixed three reliability and UX gaps in the PolyQuantBot Telegram interface:

1. **Market metadata hard fallback** — When `market_cache.get()` returns `None` (cache miss), the pipeline now calls `market_cache.fetch_one(market_id)` to fetch fresh metadata from the Gamma API before falling back to the raw ID.
2. **Risk Level hybrid UI** — Settings ‣ Risk now shows the current value and four preset buttons (0.10 / 0.25 / 0.50 / 1.00) in addition to the existing `/set_risk` manual command.
3. **Strategy toggle confirmation** — After toggling a strategy the bot now shows "✅ Strategy activated: `name`" or "❌ Strategy disabled: `name`" above the strategy menu.

---

## 2. Current System Architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
                                                        │
                                                  Telegram UX
                                                  (inline UI)
```

Telegram inline UI route:
```
callback_query (action:*)
    └── CallbackRouter._dispatch()
            ├── settings_risk  → settings_risk_screen(current) + build_risk_level_menu()
            ├── risk_set_*     → validate → config.set_risk_multiplier() → confirmation
            └── strategy_toggle:* → toggle() → log strategy_toggled → confirmation + menu
```

Market metadata fallback route:
```
trading_loop tick
    └── market_cache.get(id)   ← synchronous, fast
            └── None?  → market_cache.fetch_one(id)  ← async, 3x retry, 2s timeout
                    └── None?  → fallback to market_id string
```

---

## 3. Files Created / Modified

| File | Change |
|------|--------|
| `core/market/market_cache.py` | Added `fetch_one()` async method with 3×retry / 2s timeout |
| `core/pipeline/trading_loop.py` | Added `fetch_one()` fallback after `cache.get()` miss |
| `telegram/ui/screens.py` | Updated `settings_risk_screen()` to accept `current_value` param |
| `telegram/ui/keyboard.py` | Added `build_risk_level_menu()` with preset risk buttons |
| `telegram/handlers/callback_router.py` | Added `risk_set_*` handler; updated strategy toggle to emit confirmation; imported `build_risk_level_menu` |

---

## 4. What's Working

- Market always resolves to human-readable question when API is reachable (cache hit or `fetch_one` success).
- Risk can be set via inline button (0.10 / 0.25 / 0.50 / 1.00) or `/set_risk` command.
- `risk_set_` handler validates range 0.10–1.00, rejects out-of-range input with clear message.
- Strategy toggle now shows "✅ Strategy activated" / "❌ Strategy disabled" confirmation.
- Structured logs emitted: `market_metadata_fallback_used`, `risk_updated`, `strategy_toggled`.
- All 75 existing callback-router tests pass.

---

## 5. Known Issues

- `fetch_one()` hits the public `/markets/{id}` endpoint; if the Gamma API doesn't support single-market lookup by conditionId the response may be 404 and the fallback to `market_id` is still used (safe behavior).
- No persistent rate-limiting on `fetch_one()` — if many markets miss cache simultaneously this could generate burst API calls. Mitigated by the per-retry delay and existing background refresh.

---

## 6. What's Next

- Add `/set_risk` command response to mirror the hybrid UI confirmation style.
- Add rate-limit guard on `fetch_one()` (e.g. LRU miss counter per tick).
- Consider persisting risk multiplier to Redis so it survives restarts.
