# 24_8_market_scanning_presence

## Validation Metadata
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target:
  - strategy evaluation loop in `projects/polymarket/polyquantbot/core/pipeline/trading_loop.py`
  - Telegram scan-presence message formatting in `projects/polymarket/polyquantbot/telegram/message_formatter.py`
  - candidate selection / no-trade decision output in scan-presence notifier flow
- Not in Scope:
  - execution logic changes
  - risk logic changes
  - strategy algorithm changes
  - order placement
  - observability redesign
  - trade lifecycle alerts
- Suggested Next Step: Codex auto PR review + COMMANDER review required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_8_market_scanning_presence.md`. Tier: STANDARD

## 1. What was built
- Added premium scan-presence Telegram messaging support for non-execution cycles with strict hierarchical `|- field: value` formatting.
- Implemented three new formatter outputs:
  - `🔎 MARKET SCAN` heartbeat
  - `🧠 TOP CANDIDATE` preview
  - `⚠️ NO TRADE` explanation
- Added `MarketScanPresenceNotifier` to throttle scan-presence updates and prevent repeat spam for unchanged no-trade reasons and duplicate candidate signatures.
- Integrated notifier into the strategy evaluation loop so messages are emitted only when no trade executes in a tick and when throttle conditions pass.

## 2. Current system architecture
- Strategy evaluation loop (`run_trading_loop`) computes scan/no-trade context after signal generation and execution attempts.
- New notifier layer (`MarketScanPresenceNotifier`) decides whether to emit scan-presence messages based on:
  - tick cadence + heartbeat interval
  - no-trade reason change / cooldown
  - top-candidate uniqueness + cooldown + minimum edge threshold
- Telegram message strings remain centralized in `message_formatter.py` (single formatting authority).
- Trade entry/exit lifecycle alerts remain unchanged and continue to be higher-priority operational alerts.

## 3. Files created / modified (full paths)
- Modified: `projects/polymarket/polyquantbot/core/pipeline/trading_loop.py`
- Modified: `projects/polymarket/polyquantbot/telegram/message_formatter.py`
- Created: `projects/polymarket/polyquantbot/tests/test_market_scanning_presence_20260409.py`
- Created: `projects/polymarket/polyquantbot/reports/forge/24_8_market_scanning_presence.md`
- Modified: `PROJECT_STATE.md`

## 4. What is working
- Scan heartbeat emits in strict hierarchy format and is throttled by both tick cadence and minimum interval.
- Repeated identical no-trade reasons are not spammed continuously.
- Top candidate preview selects strongest candidate (by edge), uses strict format, and suppresses duplicate repeated candidate previews.
- No-trade explanation emits only for no-trade cycles; execution cycles skip no-trade messaging.
- All scan-presence messages conform to mandatory hierarchy-line rule.

Throttling behavior proof:
- Heartbeat: notifier requires both tick cadence (`_SCAN_HEARTBEAT_EVERY_TICKS`) and minimum interval (`_SCAN_HEARTBEAT_MIN_INTERVAL_S`) before sending.
- No-trade: notifier sends only when reason changes or cooldown window passes (`_NO_TRADE_MIN_INTERVAL_S`).
- Candidate preview: notifier suppresses unchanged candidate signature and enforces `_TOP_CANDIDATE_MIN_INTERVAL_S` cooldown.

Test evidence:
- `python -m py_compile projects/polymarket/polyquantbot/telegram/message_formatter.py projects/polymarket/polyquantbot/core/pipeline/trading_loop.py projects/polymarket/polyquantbot/tests/test_market_scanning_presence_20260409.py` ✅
- `PYTHONPATH=/workspace/walker-ai-team pytest -q projects/polymarket/polyquantbot/tests/test_market_scanning_presence_20260409.py` ✅ (5 passed)

Runtime proof (message examples):
1) Scan heartbeat
```text
🔎 MARKET SCAN
|- Markets scanned: 42
|- Active candidates: 1
|- Status: Waiting for confirmation
```

2) Top candidate preview
```text
🧠 TOP CANDIDATE
|- Market: HIGH
|- Side: YES
|- Edge: 4.50%
|- Status: borderline
|- Reason: edge below execution threshold
```

3) No-trade explanation
```text
⚠️ NO TRADE
|- Reason: insufficient edge
```

## 5. Known issues
- Existing pytest environment warning persists (`Unknown config option: asyncio_mode`), but focused tests pass.
- Live Telegram device screenshot proof remains unavailable in this container environment.

## 6. What is next
- COMMANDER review for STANDARD-tier narrow integration delivery.
- Merge decision after Codex auto PR review baseline + COMMANDER review.
- No SENTINEL escalation required unless COMMANDER explicitly reclassifies task impact.
