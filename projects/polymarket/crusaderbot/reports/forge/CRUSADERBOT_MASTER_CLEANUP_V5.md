# WARP•FORGE TASK: Master Cleanup & Sync (V5 Beta Readiness)
============
**Repo Path**     : projects/polymarket/crusaderbot
**Validation Tier**: MAJOR
**Claim Level**   : FULL RUNTIME INTEGRATION

## 1. OBJECTIVE
Resolve critical functional mismatches in the Copy Trade engine, inject trade reasoning, and perform final UX width stabilization.

---

## 2. TASK 1: Copy Trade Engine Sync (CRITICAL)
- **Problem:** The new 8-step wizard writes to `copy_trade_tasks`, but the engine (`domain/strategy/strategies/copy_trade.py`) still reads from the legacy `copy_targets` table.
- **Action:** 
  - Refactor `_load_active_copy_targets` in `copy_trade.py` to query `copy_trade_tasks`.
  - Map fields: `target_wallet_address` -> `wallet_address`, `status` -> `status` (ensure 'active' logic matches).
  - Update any dependent logic in the scan loop to respect the new task structure.

## 3. TASK 2: Analysis Engine "Reasoning" Injection
- **Problem:** Bot opens trades without explaining "Why," reducing user trust.
- **Action:**
  - Update `SignalCandidate` dataclass in `domain/signal/base.py` to include:
    - `reasoning: str = ""` 
    - `confidence: float = 0.0` 
  - Update all active strategies (Copy Trade, Signal Following, Momentum) to populate these fields.
  - *Example Reasoning:* "CopyTrade: Mirroring high-winrate leader [Address]." or "Signal: Heisenberg feed breakout."

## 4. TASK 3: Tactical Terminal UX Polish
- **Action:**
  - Update `DIV` in `bot/messages.py` from 26 characters to **32 characters** (`"━" * 32`).
  - In `dashboard_text` and other templates, ensure headers and separators are wide enough to force Telegram bubbles to 90%+ mobile width.
  - Standardize all `<code>` blocks to use the new wider width.

---

## 5. DONE CRITERIA
- [ ] Copy Trade engine successfully triggers trades from tasks created via the new UI.
- [ ] Every trade notification includes a "Reasoning" line.
- [ ] Dashboard layout is wide, clean, and 100% English.
- [ ] Zero regressions in existing functional paths.
- [ ] `python3 -m compileall` PASS.