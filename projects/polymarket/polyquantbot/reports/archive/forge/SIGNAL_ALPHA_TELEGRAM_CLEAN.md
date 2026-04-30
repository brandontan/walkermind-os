# FORGE-X REPORT — Signal Alpha Activation + Telegram Hard Clean

Date: 2026-04-02
Task: Signal Alpha Injection + Legacy Telegram UI Elimination

---

## 1. Alpha Logic

### Implementation

File: `core/signal/signal_engine.py`

Alpha is injected immediately after reading the market price, before edge calculation:

```python
# TEMP ALPHA INJECTION
alpha: float = random.uniform(0.01, 0.05)
p_model: float = min(max(p_market + alpha, 0.01), 0.99)
```

- `alpha` is a uniform random draw in `[0.01, 0.05]`
- `p_model` is clamped to `[0.01, 0.99]` to stay within probability bounds
- Edge is then computed as `edge = p_model - p_market`, which equals `alpha` (always positive)

Additional changes:
- Default edge threshold lowered from `0.02` → `0.01` to ensure signals pass through
- `signal_debug` log emitted on every market tick:
  ```json
  {"event": "signal_debug", "market_id": "...", "p_market": 0.45, "p_model": 0.48, "edge": 0.03}
  ```

---

## 2. Signal Activation Result

With alpha injection active:

- Every market with `p_market > 0` and `liquidity_usd > $10,000` will generate a signal
- Edge is always positive (alpha ≥ 0.01)
- Edge always exceeds the 0.01 threshold (alpha ∈ [0.01, 0.05])
- `signals_generated > 0` guaranteed for any non-empty market list with valid liquidity

Expected log sequence per market tick:
1. `signal_debug` — alpha + edge values logged
2. `signal_generated` — EV and sizing computed
3. `trade_executed` — paper or live fill recorded

---

## 3. Files Removed (Legacy)

Legacy Telegram handler files were already eliminated in a prior cleanup:

| File | Status |
|------|--------|
| `telegram/handlers/health.py` | Does not exist — previously removed |
| `telegram/handlers/performance.py` | Does not exist — previously removed |
| `telegram/handlers/strategies.py` | Does not exist — previously removed |

The legacy routes were disabled via hard block in `callback_router.py`.

---

## 4. Final Telegram Structure

### Handler Registration (main.py polling loop)

- `action:*` callbacks → `CallbackRouter` (editMessageText, inline UI)
- Text commands → `CommandRouter`
- `/start` → main menu via CommandRouter

### CallbackRouter Changes (`telegram/handlers/callback_router.py`)

Two changes applied:

1. **Debug handler trace** — logged on every incoming callback:
   ```python
   log.info("telegram_handler", handler="NEW_SYSTEM")
   ```

2. **Enhanced legacy block** — broader substring match (covers variants like `action:health_*`):
   ```python
   if any(x in cb_data for x in ("health", "performance", "strategies")):
       log.warning("callback_legacy_blocked", callback_data=cb_data)
       raise RuntimeError("LEGACY UI DISABLED")
   ```
   - This is inside the dispatch try-except → error screen shown to user, no bot crash
   - Also complemented by exact-match block in `_dispatch()` for double protection

### Main Menu (4 buttons only)

```
[📊 Status]     [💰 Wallet ]
[⚙️ Settings]   [▶ Control ]
```

All buttons use `action:<name>` format → routed through `CallbackRouter` → `editMessageText`.

---

## 5. Logs Proof (Expected)

### Signal Debug Log
```json
{
  "event": "signal_debug",
  "market_id": "0x...",
  "p_market": 0.42,
  "p_model": 0.455,
  "edge": 0.035
}
```

### Signal Generated Log
```json
{
  "event": "signal_generated",
  "market_id": "0x...",
  "edge": 0.035,
  "ev": 0.0603,
  "p_model": 0.455,
  "p_market": 0.42
}
```

### Trade Executed Log
```json
{
  "event": "trade_executed",
  "signal_id": "abc123ef4567",
  "market_id": "0x...",
  "side": "YES",
  "size_usd": 25.0,
  "mode": "PAPER"
}
```

### Telegram Handler Trace Log
```json
{
  "event": "telegram_handler",
  "handler": "NEW_SYSTEM"
}
```

### Legacy Block Log
```json
{
  "event": "callback_legacy_blocked",
  "callback_data": "action:health"
}
```

---

## 6. Known Limitations

1. **Alpha is temporary** — `random.uniform(0.01, 0.05)` provides artificial positive edge. Real model-based `p_model` should replace this when the intelligence layer is fully integrated.

2. **Liquidity filter still active** — Markets with `liquidity_usd ≤ $10,000` are skipped. In test environments with mock data, ensure liquidity exceeds this threshold.

3. **p_model from market data ignored** — The original `p_model` from the market dict is overridden by alpha injection. This is intentional for activation testing only.

4. **MultiStrategyMetrics** — Still present in core trading infrastructure (strategy/orchestrator.py, execution/feedback_loop.py). Not removed from Telegram command_handler.py but all UI callbacks to performance/strategies/health are blocked. No runtime errors expected.

5. **Strategy toggle buttons** — `build_strategy_menu()` still exists in settings but `strategy_toggle_*` callbacks fall through to unknown-action → main menu. Not a blocking issue.

---

## Files Modified

| File | Change |
|------|--------|
| `core/signal/signal_engine.py` | Alpha injection, lowered threshold (0.02→0.01), signal_debug log |
| `telegram/handlers/callback_router.py` | NEW_SYSTEM handler trace log, enhanced legacy block |

## Files Created

| File | Purpose |
|------|---------|
| `reports/forge/SIGNAL_ALPHA_TELEGRAM_CLEAN.md` | This report |
