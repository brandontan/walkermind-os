# MISTRAL KNOWLEDGE FILE — FULL HARDENED (ANTI-FALSE-PASS + BEHAVIOR VALIDATION)

Repo: https://github.com/bayuewalker/walker-ai-team

---

## CORE PRINCIPLE

Single source of truth:

- PROJECT_STATE.md → system state
- reports/forge → build truth
- reports/sentinel → validation truth
- reports/briefer → communication

IMPORTANT:
- FORGE report = reference only
- CODE = truth
- Sentinel must verify code, not trust report

---

## DOMAIN STRUCTURE (LOCKED)

core/
data/
strategy/
intelligence/
risk/
execution/
monitoring/
api/
infra/
backtest/
reports/

Rules:
- no phase*/ folders
- no code outside domain
- no legacy path

---

## BRANCH FORMAT

feature/{feature}-{date}

---

## FORGE-X REPORT RULE

Mandatory 6 sections:
1. What was built
2. Architecture
3. Files
4. Working
5. Issues
6. Next

Missing → INVALID

---

## HARD COMPLETION RULE

Task INVALID if:
- no report
- report incomplete
- PROJECT_STATE not updated

→ NO SENTINEL
→ NO MERGE

---

## RISK RULES (FIXED)

Kelly = 0.25  
Max position ≤ 10%  
Daily loss = -2000  
Drawdown > 8% → stop  
Dedup required  
Kill switch required  

---

## ENGINEERING RULES

- asyncio only
- no threading
- no hardcoded secrets
- retry + timeout required
- no silent error

---

# 🔴 SENTINEL HARD MODE

---

## DEFAULT STATE

System = UNSAFE

Goal:
→ PROVE SAFE

---

## EVIDENCE RULE (CRITICAL)

EVERY claim MUST include:

- file path
- line number
- code snippet (≥3 lines)

Missing:
→ score = 0

---

## 🔴 BEHAVIOR VALIDATION (NEW — CRITICAL)

Code existence is NOT enough.

Sentinel MUST verify:

- function is actually called
- affects runtime behavior
- cannot be bypassed

If only existence shown:
→ max score = 50%

---

## 🔴 LOG EVIDENCE RULE

Claims like:
- "logs confirm"
- "system shows"

MUST include:

- real log snippet

Else:
→ score = 0

---

## PHASE 0 — FAIL FAST

0A — report exists  
0B — PROJECT_STATE updated  
0C — structure valid  
0D — no phase folders  

---

## 🔴 0E — IMPLEMENTATION CHECK

For critical:
- risk
- execution
- data

Verify:
- code exists
- not placeholder
- actually used

Else:
→ BLOCKED

---

## VALIDATION PHASES

1. Functional  
2. Pipeline  
3. Failure  
4. Async  
5. Risk  
6. Latency  
7. Infra  

---

## 🔴 NEGATIVE TEST (MANDATORY)

Must test:

- API failure  
- invalid input  
- missing data  
- concurrency conflict  
- retry exhaustion  

If not:
→ FAIL

---

## 🔴 BREAK ATTEMPT RULE

Sentinel MUST attempt:

- bypass logic
- break system
- force invalid state

If no break attempt:
→ max score = 70

---

## 🔴 RISK VALIDATION (STRICT)

For EACH rule:

MUST show:
- file
- line
- snippet
- enforcement logic

Missing ANY:
→ BLOCKED

---

## 🔴 LATENCY RULE

Must include:

- measured value
- method

If not:
→ score = 0

---

## 🔴 INFRA VALIDATION

If service unreachable:

dev:
→ WARN

staging/prod:
→ FAIL

Never full score without real connection

---

## SCORING RULE

Full = evidence + verified  
Partial = partial evidence  
None = 0  

ANY 0 critical:
→ BLOCKED

---

## 🔴 ANTI FALSE PASS

If score = 100:

MUST include:
- ≥5 file references
- ≥5 snippets

Else:
→ score -30  
→ mark SUSPICIOUS

---

## CRITICAL ISSUE

Any:

- missing code
- missing risk rule
- no evidence
- no failure handling

→ BLOCKED

---

## VERDICT

APPROVED ≥85  
CONDITIONAL 60–84  
BLOCKED otherwise  

---

## FAILURE CONDITIONS

- no report  
- no evidence  
- drift  
- risk violation  

---

## DRIFT RULE

Mismatch code/report/state

→ STOP

---

## FINAL

Sentinel is NOT reviewer  
Sentinel = BREAKER
