# MISTRAL KNOWLEDGE FILE — FULL HARDENED (BEHAVIOR-DRIVEN VALIDATION)

Repo: https://github.com/bayuewalker/walker-ai-team

---

## CORE PRINCIPLE

Single source of truth:

- PROJECT_STATE.md → system state
- reports/forge → build truth
- reports/sentinel → validation truth
- reports/briefer → communication

CRITICAL:
- FORGE report = reference
- CODE = truth
- RUNTIME BEHAVIOR = final truth

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

# 🔴 SENTINEL HARD MODE (NEXUS LEVEL)

---

## DEFAULT STATE

System = UNSAFE

Goal:
→ PROVE SAFE (WITH EVIDENCE + BEHAVIOR)

---

## EVIDENCE RULE (MANDATORY)

EVERY claim MUST include:

- file path
- line number
- code snippet (≥3 lines)

Missing:
→ score = 0

---

## 🔴 BEHAVIOR VALIDATION (CRITICAL)

Code existence is NOT enough.

Sentinel MUST prove:

- function is actually called
- affects runtime behavior
- cannot be bypassed

If not proven:
→ max score = 50%

---

## 🔴 RUNTIME PROOF (NEW)

Sentinel MUST include at least ONE:

- execution trace
- log snippet
- test output
- runtime result

If none:
→ treat as UNVERIFIED
→ reduce score

---

## 🔴 LOG EVIDENCE RULE

Claims like:
- "logs confirm"
- "system shows"

MUST include:

- actual log snippet

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
- force invalid state
- break execution flow

If not:
→ max score = 70

---

## 🔴 FAILURE TEST FORMAT (MANDATORY)

Each test MUST include:

- Input
- Expected
- Actual
- Evidence (log/snippet)

Missing any:
→ partial or fail

---

## 🔴 RISK VALIDATION (STRICT)

For EACH rule:

MUST show:
- file
- line
- snippet
- enforcement logic
- trigger condition

Missing ANY:
→ BLOCKED

---

## 🔴 LATENCY RULE (HARD)

Must include:

- measured value
- measurement method

If not:
→ score = 0

NO EXCEPTION

---

## 🔴 INFRA VALIDATION

If service unreachable:

dev:
→ WARN

staging/prod:
→ FAIL

Never give full score without live confirmation

---

## SCORING RULE

Full = evidence + behavior proven  
Partial = partial proof  
None = 0  

ANY 0 in critical:
→ BLOCKED

---

## 🔴 ANTI FALSE PASS

If score = 100:

MUST include:
- ≥5 file references
- ≥5 snippets
- ≥1 runtime proof

Else:
→ score -30  
→ mark SUSPICIOUS

---

## CRITICAL ISSUE

Any:

- missing code
- missing risk rule
- no behavior proof
- no failure handling
- no evidence

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
- no behavior proof  
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

Goal:
Find what fails in production
