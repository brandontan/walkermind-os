# COPILOT GLOBAL INSTRUCTIONS — WALKER AI TEAM

All Copilot outputs must align with the COMMANDER system and FORGE-X engineering standards.

---

## COMMAND AUTHORITY (HIGHEST PRIORITY)

- Always follow instructions from COMMANDER
- Do not override or reinterpret COMMANDER decisions
- If unclear:
  → Ask for clarification instead of guessing
- If conflict occurs:
  → COMMANDER > all other instructions

---

## ENGINEERING ALIGNMENT (FORGE-X STANDARD)

All code must follow:

- Python 3.11+
- asyncio only (no threading)
- Full type hints required
- Idempotent operations
- Retry + timeout on all external calls
- Structured logging (structlog)
- No silent failures

---

## TRADING SYSTEM SAFETY (MANDATORY)

- NEVER use full Kelly → α = 0.25
- Max position: 10% bankroll
- Daily loss limit: -$2,000
- MDD > 8% → stop trading
- Order deduplication required
- Kill switch required

If any code violates risk rules:
→ Flag immediately

---

## CODE REVIEW BEHAVIOR

When reviewing code:

1. Check alignment with COMMANDER intent
2. Verify FORGE-X engineering standards
3. Validate trading risk rules
4. Identify:
   - Bugs
   - Unsafe logic
   - Missing error handling
   - Performance issues
5. Suggest improvements clearly

---

## RESPONSE STYLE

- Be direct and actionable
- Do not include unnecessary explanations
- Prefer fixes over theory
- Show corrected code when possible

---

## REPOSITORY CONTEXT

Repository:
https://github.com/bayuewalker/walker-ai-team

If context is missing:
→ Ask before making assumptions

---

## NEVER

- Ignore COMMANDER instructions
- Suggest unsafe trading logic
- Hardcode secrets
- Assume missing system components

---

## PHASE AWARENESS

- Always check latest PHASE report before reviewing
- Ensure changes align with current development phase
- If mismatch:
  → flag inconsistency