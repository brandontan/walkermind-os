#!/usr/bin/env python3
"""WARP Auto Gate v2: FORGE -> GATE -> CMD deputy router."""
from __future__ import annotations
import json, os, re, sys, urllib.request
from typing import Any

API="https://api.github.com"; MARK="<!-- WARP•GATE -->"; ROOT="projects/polymarket/crusaderbot"
FIELDS=["Validation Tier","Claim Level","Validation Target","Not in Scope"]

def h(tok:str)->dict[str,str]:
    return {"Authorization":f"Bearer {tok}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"WARP-Gate/2"}
def req(path:str,tok:str,body:dict[str,Any]|None=None,method:str|None=None)->Any:
    data=None if body is None else json.dumps(body).encode()
    hd=h(tok) if body is None else {**h(tok),"Content-Type":"application/json"}
    r=urllib.request.Request(API+path,headers=hd,data=data,method=method)
    with urllib.request.urlopen(r,timeout=30) as resp: return json.loads(resp.read())
def get_files(repo:str,num:int,tok:str)->list[dict[str,Any]]:
    out=[]; p=1
    while True:
        b=req(f"/repos/{repo}/pulls/{num}/files?per_page=100&page={p}",tok)
        if not b: break
        out+=b
        if len(b)<100: break
        p+=1
    return out
def checks(repo:str,sha:str,tok:str)->list[dict[str,Any]]:
    return req(f"/repos/{repo}/commits/{sha}/check-runs?per_page=100",tok).get("check_runs",[])
def pr_by_sha(repo:str,sha:str,tok:str)->int|None:
    for pr in req(f"/repos/{repo}/pulls?state=open&per_page=100",tok):
        if pr.get("head",{}).get("sha")==sha: return int(pr["number"])
    return None
def comment_id(repo:str,num:int,tok:str)->int|None:
    p=1
    while True:
        cs=req(f"/repos/{repo}/issues/{num}/comments?per_page=100&page={p}",tok)
        if not cs: return None
        for c in cs:
            if MARK in (c.get("body") or ""): return int(c["id"])
        if len(cs)<100: return None
        p+=1
def put_comment(repo:str,num:int,tok:str,body:str)->None:
    cid=comment_id(repo,num,tok)
    if cid: req(f"/repos/{repo}/issues/comments/{cid}",tok,{"body":body},"PATCH")
    else: req(f"/repos/{repo}/issues/{num}/comments",tok,{"body":body},"POST")

def names(fs:list[dict[str,Any]])->list[str]: return [str(f.get("filename","")) for f in fs]
def runtime(n:str)->bool: return "/reports/" not in n and "/state/" not in n and n.endswith((".py",".ts",".tsx",".js",".sh",".yml",".yaml"))
def field(body:str,k:str)->str:
    m=re.search(rf"^{re.escape(k)}\s*[:\-]\s*(.+)$",body or "",re.I|re.M); return m.group(1).strip() if m else ""
def tier(body:str)->str:
    x=(field(body,"Validation Tier") or field(body,"Tier")).upper()
    return "MAJOR" if "MAJOR" in x else "STANDARD" if "STANDARD" in x else "MINOR" if "MINOR" in x else "UNKNOWN"
def claim(body:str)->str:
    x=field(body,"Claim Level").upper()
    return "FULL RUNTIME INTEGRATION" if "FULL RUNTIME INTEGRATION" in x else "NARROW INTEGRATION" if "NARROW INTEGRATION" in x else "FOUNDATION" if "FOUNDATION" in x else (field(body,"Claim Level") or "UNKNOWN")
def slug(br:str)->str: return br.split("/",1)[1] if br.startswith("WARP/") else br.replace("/","-")

def branch_findings(br:str)->list[str]:
    # Non-blocking by design. CMD remains final; GATE asks FORGE to fix/replace branch.
    f=[]
    if not br.startswith("WARP/"): return [f"Branch `{br}` should be recreated/renamed under `WARP/{{feature}}` before CMD final merge review."]
    s=slug(br)
    if "/" in s: f.append(f"Branch `{br}` has nested slash.")
    if "_" in s or "." in s: f.append(f"Branch `{br}` contains underscore/dot; use hyphen.")
    if re.search(r"(?:20\d{6}|20\d{2}-\d{2}-\d{2})",s): f.append(f"Branch `{br}` looks date-suffixed.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*",s): f.append(f"Branch `{br}` has invalid slug characters.")
    return f
def body_findings(body:str)->list[str]:
    miss=[x for x in FIELDS if x not in (body or "")]
    return ["PR body is missing all gate fields: Validation Tier, Claim Level, Validation Target, Not in Scope."] if len(miss)==4 else [f"PR body missing `{x}`." for x in miss]
def report_findings(fs:list[dict[str,Any]],br:str)->tuple[list[str],str]:
    ns=names(fs)
    if not (any(runtime(n) for n in ns) or any("/reports/forge/" in n for n in ns)): return [],""
    exp=f"{ROOT}/reports/forge/{slug(br)}.md"
    reps=[n for n in ns if "/reports/forge/" in n and n.endswith(".md")]
    if exp in ns: return [],exp
    if reps: return [f"Forge report path should align with branch. Expected `{exp}`, found `{reps[0]}`."],reps[0]
    return [f"Forge report missing. Expected `{exp}`."],exp
def state_findings(fs:list[dict[str,Any]])->list[str]:
    ns=names(fs)
    return [f"`{ROOT}/state/PROJECT_STATE.md` not updated for code-bearing FORGE PR."] if any(runtime(n) for n in ns) and f"{ROOT}/state/PROJECT_STATE.md" not in ns else []
def p0_findings(fs:list[dict[str,Any]])->list[str]:
    out=[]; pats=[(r"(?:^|\s)import\s+threading\b|from\s+threading\s+import","threading import"),
    (r"\bkelly_fraction\s*=\s*1\.0\b|\ba\s*=\s*1\.0\b.*[Kk]elly|[Kk]elly.*\ba\s*=\s*1\.0\b","full Kelly / a=1.0"),
    (r"except\s*:\s*pass\b|except\s+Exception\s*:\s*(?:\n\s*)?pass\b","silent exception"),
    (r"ENABLE_LIVE_TRADING\s*=\s*True\b(?!\s*#\s*overridden)","live trading guard hardcoded True")]
    sec=re.compile(r"(?:api[_-]?key|secret[_-]?key|password|private[_-]?key|access[_-]?token)\s*[=:]\s*['\"][A-Za-z0-9+/=_\-]{12,}['\"]",re.I)
    for fi in fs:
        fn=str(fi.get("filename","")); patch=fi.get("patch","") or ""
        add="\n".join(l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
        if re.search(r"(^|/)phase\d+[/_]",fn): out.append(f"P0: forbidden phase*/ folder introduced: `{fn}`.")
        if sec.search(add): out.append(f"P0: potential hardcoded credential in `{fn}`.")
        for p,lbl in pats:
            if re.search(p,add,re.M|re.I): out.append(f"P0: {lbl} in `{fn}`.")
    return out
def drift_findings(fs:list[dict[str,Any]],br:str)->list[str]:
    out=[]
    for fi in fs:
        fn=str(fi.get("filename",""))
        if "/reports/forge/" not in fn: continue
        for ref in re.findall(r"Branch\s*:\s*(WARP/[^\s`]+)",fi.get("patch","") or ""):
            if ref!=br: out.append(f"Forge report branch reference `{ref}` should match PR head `{br}`.")
    return out
def ci_findings(crs:list[dict[str,Any]])->list[str]:
    return [f"CI check `{r.get('name')}` completed with `{r.get('conclusion')}`." for r in crs if r.get("name")!="WARP Auto Gate" and r.get("status")=="completed" and r.get("conclusion") in {"failure","timed_out","cancelled"}]
def sentinel_ready(t:str,body:str,rep:str,fix:list[str])->bool:
    return t=="MAJOR" and bool(rep) and not fix and all(x in (body or "") for x in ["Report:","State:","Validation Tier:","Claim Level:"])

def forge_task(br:str,t:str,c:str,fix:list[str])->str:
    fixes="\n".join(f"- {x}" for x in fix)
    return f"""WARP•FORGE TASK: Gate fix before CMD review
============
Repo      : https://github.com/bayuewalker/walkermind-os
Project   : CrusaderBot
Repo path : {ROOT}
Branch    : {br}

ISSUE FOUND:
WARP•GATE found actionable items before WARP🔹CMD merge review.

FIX REQUIRED:
{fixes}

SCOPE:
- Keep behavior unchanged unless the finding explicitly requires behavior correction.
- Preserve PAPER ONLY posture. Do not enable live trading, real CLOB execution, capital, or risk guards.

VALIDATION:
Validation Tier   : {t if t!="UNKNOWN" else "STANDARD"}
Claim Level       : {c}
Validation Target : Gate findings only
Not in Scope      : New features, live trading activation, unrelated cleanup

DONE CRITERIA:
- [ ] Fix applied in same PR or replacement PR
- [ ] Forge report/state references updated truthfully
- [ ] CI/gate re-run clean or remaining items documented

NEXT GATE:
- WARP•GATE re-check -> WARP🔹CMD review
"""
def sentinel_task(br:str,c:str,rep:str)->str:
    return f"""WARP•SENTINEL TASK: Validate MAJOR FORGE output
=============
Repo         : https://github.com/bayuewalker/walkermind-os
Project      : CrusaderBot
Repo path    : {ROOT}
Branch       : {br}
Tier         : MAJOR
Claim Level  : {c}
Source       : {rep}

SENTINEL REQUIRED BECAUSE:
Validation Tier is MAJOR and WARP•GATE found no pre-handoff fix blockers.

REQUIRED CHECKS:
- Verify claim against actual code, not report wording.
- Verify runtime/test evidence for claimed behavior.
- Verify risk / execution / state integrity if touched.
- Verify PROJECT_STATE.md remains truthful.
- Preserve PAPER ONLY posture.

DELIVERABLES:
- Sentinel report under {ROOT}/reports/sentinel/
- Verdict: APPROVED / CONDITIONAL / BLOCKED
- NEXT GATE: return to WARP🔹CMD
"""
def build_comment(br:str,num:int,route:str,p0:list[str],fix:list[str],info:list[str],sent:str,t:str,c:str)->str:
    parts=[MARK,f"## WARP•GATE v2 — {route}","",f"**Branch:** `{br}` &nbsp; **PR:** #{num}",f"**Tier:** {t} &nbsp; **Claim:** {c}",""]
    if p0: parts+=["### P0 — real blocker",""]+[f"- {x}" for x in p0]+[""]
    if fix: parts+=["### Fix required","",forge_task(br,t,c,fix),""]
    if sent: parts+=["### Sentinel required","",sent,""]
    if info: parts+=["### Advisory",""]+[f"- {x}" for x in info]+[""]
    if route=="READY_FOR_CMD": parts+=["Ready for WARP🔹CMD final review. WARP•GATE does not merge.",""]
    parts+=["---","_WARP•GATE is deputy automation only. WARP🔹CMD remains final._"]
    return "\n".join(parts)

def main()->int:
    tok=os.getenv("GITHUB_TOKEN",""); repo=os.getenv("GITHUB_REPOSITORY",""); pn=os.getenv("PR_NUMBER","").strip(); sha=os.getenv("WR_HEAD_SHA","").strip()
    if not tok or not repo: print("ERROR: missing GITHUB_TOKEN or GITHUB_REPOSITORY",file=sys.stderr); return 1
    num=int(pn) if pn else pr_by_sha(repo,sha,tok)
    if not num: print(f"No open PR found for SHA {sha} — nothing to gate."); return 0
    pr=req(f"/repos/{repo}/pulls/{num}",tok); br=pr["head"]["ref"]; head=pr["head"]["sha"]; body=pr.get("body") or ""; title=pr.get("title") or ""
    if title.lower().startswith("sync:") or "post-merge sync" in title.lower(): print(f"Skipping sync PR: {title!r}"); return 0
    fs=get_files(repo,num,tok); cr=checks(repo,head,tok); t=tier(body); c=claim(body)
    p0=p0_findings(fs)
    repfix,rep=report_findings(fs,br)
    fix=branch_findings(br)+body_findings(body)+repfix+state_findings(fs)+drift_findings(fs,br)+ci_findings(cr)
    info=["MAJOR tier detected. WARP•SENTINEL is required before merge."] if t=="MAJOR" else []
    sent=sentinel_task(br,c,rep) if sentinel_ready(t,body,rep,fix) and not p0 else ""
    route="BLOCKED" if p0 else "SENTINEL_REQUIRED" if sent else "FIX_REQUIRED" if fix else "READY_FOR_CMD"
    try: put_comment(repo,num,tok,build_comment(br,num,route,p0,fix,info,sent,t,c)); print("Gate comment posted/updated.")
    except Exception as e: print(f"WARN: failed to post gate comment: {e}")
    print(f"\nWARP Auto Gate v2 branch={br} pr=#{num}\nRoute: {route}\nP0 blockers: {len(p0)}\nFix items: {len(fix)}")
    if p0:
        print("\nResult: FAILED — real blocker present."); return 1
    print("\nResult: PASSED — routed by WARP•GATE. WARP🔹CMD remains final."); return 0
if __name__=="__main__": sys.exit(main())
