# Telegram Menu Structure - Founder Handoff

## 1. Executive summary
This increment delivers the Telegram menu-structure redesign and a market-scope control surface that is wired into runtime market filtering.
SENTINEL validated the target increment at **CONDITIONAL** with a **96/100** score and **no critical blockers**.

The important operational point is this: the new scope control is not cosmetic. It was behaviorally validated to allow or block downstream market processing based on Telegram selection.

This is not yet a full production-hardened approval. The remaining warnings are persistence across restart and category-inference edge cases when All Markets is OFF.

## 2. What changed
- The root menu was simplified to five founder-readable entry points:
  - 📊 Dashboard
  - 📼 Portfolio
  - 🎯 Markets
  - ⚙️ Settings
  - ❓ Help
- Refresh was simplified to a consistent `Refresh All` action across the redesigned paths.
- The Markets menu now centers the control surface:
  - Overview
  - All Markets
  - Categories
  - ✅ Active Scope
- The Dashboard now shows a market-scope summary so the active trading universe is visible at a glance.
- Telegram scope selection is wired into runtime market filtering, so scanning and trading now respect the chosen scope.

## 3. What was validated
SENTINEL validated the following behaviors:

- The new menu structure renders correctly.
- ❓ Help appears correctly.
- `Refresh All` appears in the redesigned paths.
- `All Markets` ON/OFF behavior works as intended.
- Category toggle behavior works as intended.
- The zero-category blocked case works as intended.
- The trading loop does not proceed when scope is blocked.
- Runtime scope enforcement was behaviorally validated.
- No critical blockers were found for this task objective.

This means the new Telegram control surface is not just a UI layer. It changes what the runtime is willing to scan and trade.

## 4. Known limitations
- Market scope persistence is currently in-process only. After a restart or re-init, operators must reapply the selection.
- Category inference is metadata/keyword-based, not a fully hardened classification layer.
- Uncategorized markets may be excluded when `All Markets` is OFF.
- Final on-device / live-network confirmation remains a separate production-hardening concern if you want merge-decision confidence beyond container-validated behavior.

## 5. What this means operationally
- This increment is valid for the menu/control-surface objective.
- The runtime scope control is real, not cosmetic.
- The current validation result is **CONDITIONAL**, not full APPROVED.
- Merge is not automatically recommended yet unless the founder explicitly accepts the current persistence and category-inference limitations.
- The cleanest next engineering step is to harden persistence + category inference, then re-run SENTINEL.

## 6. Decision options
A. Accept current CONDITIONAL result and proceed toward merge decision.
B. Run FORGE-X hardening pass for persistence + category inference, then re-run SENTINEL.
C. Hold and do live-device confirmation before any merge decision.

## 7. Recommendation
Recommendation: **B. Run FORGE-X hardening pass for persistence + category inference, then re-run SENTINEL.**

That path keeps the current investment intact, preserves the validated menu/control-surface gain, and closes the main remaining operational gaps before a final merge decision.
