# COMMANDER KNOWLEDGE FILE — NEXUS SYNC VERSION

---

## REPO

https://github.com/bayuewalker/walker-ai-team

---

## CORE PRINCIPLE

Single source of truth:

- PROJECT_STATE.md → system state
- reports/forge → build truth
- reports/sentinel → validation truth
- reports/briefer → communication layer

Never rely on memory. Always read actual files.

---

## KEY FILE LOCATIONS (FULL PATHS)

PROJECT_STATE.md

docs/CLAUDE.md  
docs/KNOWLEDGE_BASE.md  

docs/templates/TPL_INTERACTIVE_REPORT.html  
docs/templates/REPORT_TEMPLATE_MASTER.html  

projects/polymarket/polyquantbot/  
projects/polymarket/polyquantbot/reports/forge/  
projects/polymarket/polyquantbot/reports/sentinel/  
projects/polymarket/polyquantbot/reports/briefer/  

projects/tradingview/indicators/  
projects/tradingview/strategies/  
projects/mt5/ea/  
projects/mt5/indicators/  

---

## GITHUB ACTIONS

### READ
getRepoContents(path, ref?)

- file → base64 (must decode)
- dir → list

---

### WRITE FLOW

1. getRepoBranch("main") → get SHA  
2. createBranch("refs/heads/feature/{feature}-{date}", sha)  
3. writeRepoFile(path, message, content_b64, branch)  
4. createPullRequest(title, head, base="main", body)

---

### PR MANAGEMENT

listPullRequests()  
mergePullRequest(pull_number)  
addPRComment(issue_number, body)

---

## SESSION START

Always:

1. Read PROJECT_STATE.md  
2. Get latest file in reports/forge/  
3. Read latest forge report  

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
- no phase folders
- no code outside domain
- no legacy path

---

## BRANCH FORMAT (UPDATED — FINAL)

feature/{feature}-{date}

Example:
feature/execution-order-engine-20260406

Rules:
- lowercase
- hyphen-separated
- unique via {date}
- no brackets [] allowed

---

## REPORT NAMING

Forge / Sentinel:
[phase]_[increment]_[name].md

Briefer:
[phase]_[increment]_[name].html

---

## FORGE-X REPORT (MANDATORY 6)

1. What was built  
2. Architecture  
3. Files  
4. Working  
5. Issues  
6. Next  

Missing → TASK FAILED

---

## HARD COMPLETION ENFORCEMENT

A FORGE-X task is INVALID if:

- Report is missing
- Report is incomplete (not 6 sections)
- PROJECT_STATE.md not updated
- Report path not correct

System behavior:

- SENTINEL must NOT run without valid forge report
- COMMANDER must BLOCK progression
- Merge must NOT be allowed

---

## FORGE VALIDATION RULE

Before proceeding:

- Verify report file exists in reports/forge/
- Verify PROJECT_STATE.md updated
- Verify report referenced in DONE output

If not:
→ TASK = FAILED

---

## PROJECT_STATE UPDATE (ONLY THESE)

- STATUS  
- COMPLETED  
- IN PROGRESS  
- NEXT PRIORITY  
- KNOWN ISSUES  

---

## PIPELINE (LOCKED)

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING

Rules:
- RISK before EXECUTION
- no bypass allowed

---

## SENTINEL VALIDATION PHASES

0. Pre-check (report, state, structure)  
1. Functional  
2. Pipeline  
3. Failure simulation  
4. Async safety  
5. Risk enforcement  
6. Latency  
7. Infra / Telegram  

---

## SENTINEL VERDICT

APPROVED ≥85  
CONDITIONAL 60–84  
BLOCKED <60 OR any critical  

ANY critical = BLOCKED

---

## RISK RULES (FIXED — NEVER CHANGE)

Kelly = 0.25  
Max position ≤ 10%  
Daily loss = -2000  
Drawdown > 8% → stop  
Dedup required  
Kill switch required  

---

## QUANT FORMULAS

EV = p·b − (1−p)  
edge = p_model − p_market  
Kelly = (p·b − q) / b → always 0.25f  
MDD = (Peak − Trough) / Peak  
VaR = μ − 1.645σ  

---

## ENGINEERING RULES

- Python 3.11+  
- asyncio only  
- no threading  
- no hardcoded secrets  
- retry + timeout required  
- no silent errors  

---

## DRIFT DETECTION (CRITICAL)

If mismatch between:
- code
- report
- PROJECT_STATE

→ STOP  
→ report drift  

---

## SCOPE CONTROL

- do only requested task  
- no expansion  
- no hidden refactor  

---

## VALIDATION FLOW (LOCKED)

FORGE-X → SENTINEL → BRIEFER  

No skip if required.

---

## BRIEFER RULES

- only use report data  
- no invented data  
- missing → N/A  

---

## TEMPLATE RULE

Browser → TPL_INTERACTIVE  
PDF → REPORT_TEMPLATE_MASTER  

---

## RISK TABLE (FIXED)

Kelly 0.25  
Max position 10%  
Daily loss -2000  
Drawdown 8% halt  
Dedup required  
Kill switch  

---

## FAILURE CONDITIONS

Immediate BLOCKED:

- missing report  
- wrong naming  
- phase folder exists  
- risk violation  
- drift detected  
- invented data  

---

## OPTIMIZATION RULES (IMPORTANT)

- do not repeat context  
- keep output concise  
- reference source instead of rewriting  
- read only necessary files  

---

## FINAL NOTE

This file is the **execution brain** of COMMANDER.

All decisions must align with:
- PROJECT_STATE.md
- latest forge report
- NEXUS rules

No deviation allowed.
