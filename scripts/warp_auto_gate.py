#!/usr/bin/env python3
"""WARP Auto Gate v1: metadata-only PR gate.

Runs from pull_request_target. Do not checkout or execute PR-head code.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

MARKER = "<!-- warp-auto-gate -->"
API = os.getenv("GITHUB_API_URL", "https://api.github.com")
VALID_TIERS = {"MINOR", "STANDARD", "MAJOR"}
VALID_CLAIMS = {"FOUNDATION", "NARROW INTEGRATION", "FULL RUNTIME INTEGRATION"}
BRANCH_RE = re.compile(r"^WARP/[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
REPORT_RE = re.compile(r"^projects/.+/reports/(forge|sentinel)/[^/]+\.md$")
REQ_FIELDS = ("Validation Tier", "Claim Level", "Validation Target", "Not in Scope")
GUARDS = (
    "ENABLE_LIVE_TRADING",
    "EXECUTION_PATH_VALIDATED",
    "CAPITAL_MODE_CONFIRMED",
    "RISK_CONTROLS_VALIDATED",
    "USE_REAL_CLOB",
)


def gh(method: str, path: str, token: str, data: dict | None = None) -> object:
    body = None if data is None else json.dumps(data).encode("utf-8")
    url = path if path.startswith("https://") else API + path
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "WalkerMind-WARP-Auto-Gate/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def gh_list(path: str, token: str) -> list[dict]:
    sep = "&" if "?" in path else "?"
    url = f"{path}{sep}per_page=100"
    out: list[dict] = []
    while url:
        full = url if url.startswith("https://") else API + url
        req = urllib.request.Request(
            full,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "WalkerMind-WARP-Auto-Gate/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            out += json.loads(resp.read().decode("utf-8"))
            link = resp.headers.get("Link", "")
        url = ""
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part[part.find("<") + 1 : part.find(">")]
                break
    return out


def pr_number() -> int:
    direct = os.getenv("PR_NUMBER", "").strip()
    if direct:
        return int(direct)
    with open(os.environ["GITHUB_EVENT_PATH"], "r", encoding="utf-8") as fh:
        event = json.load(fh)
    if event.get("pull_request"):
        return int(event["pull_request"]["number"])
    prs = event.get("workflow_run", {}).get("pull_requests", [])
    if prs:
        return int(prs[0]["number"])
    print("No PR for this event; skip.")
    sys.exit(0)


def body_field(body: str, name: str) -> str | None:
    rx = re.compile(rf"^\s*(?:[-*]\s*)?(?:\*\*)?{re.escape(name)}(?:\*\*)?\s*[:：]\s*(.+?)\s*$", re.I | re.M)
    m = rx.search(body or "")
    return m.group(1).strip() if m else None


def added_lines(files: list[dict]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for f in files:
        for line in (f.get("patch") or "").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                out.append((f["filename"], line[1:]))
    return out


def requires_report(files: list[dict]) -> bool:
    for f in files:
        name = f["filename"]
        if name.startswith((".github/workflows/", "scripts/", "projects/", "lib/")):
            if name.endswith(".md") and "/reports/" not in name and "/state/" not in name:
                continue
            return True
    return False


def scan(repo: str, token: str, pr: dict, files: list[dict], checks: list[dict]) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    branch = pr["head"]["ref"]
    body = pr.get("body") or ""

    if not BRANCH_RE.match(branch):
        blockers.append(f"BRANCH — `{branch}` is not valid `WARP/{{feature}}` format.")
    if branch.startswith(("claude/", "NWAP/")) or "_" in branch or "." in branch:
        blockers.append(f"BRANCH — forbidden prefix or character in `{branch}`.")

    for field in REQ_FIELDS:
        if not body_field(body, field):
            blockers.append(f"PR_BODY — missing `{field}` declaration.")

    tier = body_field(body, "Validation Tier")
    claim = body_field(body, "Claim Level")
    if tier and tier.upper() not in VALID_TIERS:
        blockers.append(f"TIER — invalid Validation Tier `{tier}`.")
    if claim and claim.upper() not in VALID_CLAIMS:
        blockers.append(f"CLAIM — invalid Claim Level `{claim}`.")

    report_files = [f["filename"] for f in files if REPORT_RE.match(f["filename"])]
    if requires_report(files) and not report_files:
        blockers.append("REPORT — required forge/sentinel report path not found.")

    for name in report_files:
        blob = gh(
            "GET",
            f"/repos/{repo}/contents/{urllib.parse.quote(name, safe='')}?ref={urllib.parse.quote(branch, safe='')}",
            token,
        )
        import base64

        text = base64.b64decode(blob["content"]).decode("utf-8", errors="replace")
        if branch not in text:
            blockers.append(f"REPORT_BRANCH — `{name}` does not contain exact branch `{branch}`.")

    for filename, line in added_lines(files):
        lower = line.lower()
        for guard in GUARDS:
            if guard in line and re.search(r"[:=]\s*(true|1)\b", lower):
                blockers.append(f"GUARD — enabling `{guard}` in `{filename}`.")
        if re.search(r"(kelly_fraction|alpha|α)\s*[:=]\s*1(\.0+)?\b", line, re.I):
            blockers.append(f"KELLY — full Kelly sizing in `{filename}`.")
        if re.search(r"except(\s+Exception|\s+BaseException)?\s*:\s*pass\b", line):
            blockers.append(f"SILENT_EXCEPTION — inline silent exception in `{filename}`.")

    for run in checks:
        name = run.get("name", "")
        if "WARP Auto Gate" in name:
            continue
        conclusion = run.get("conclusion")
        if conclusion in {"failure", "cancelled", "timed_out", "action_required"}:
            blockers.append(f"CHECK — `{name}` concluded `{conclusion}`.")
        elif run.get("status") != "completed":
            warnings.append(f"CHECK — `{name}` is `{run.get('status')}`.")

    return blockers, warnings


def comment_body(pr: dict, blockers: list[str], warnings: list[str]) -> str:
    status = "PASS" if not blockers else "NEEDS-FIX"
    lines = [
        MARKER,
        "## WARP Auto Gate v1",
        "",
        f"Status: **{status}**",
        f"Branch: `{pr['head']['ref']}`",
        f"Head: `{pr['head']['sha']}`",
        "",
    ]
    if blockers:
        lines += ["### Blockers", *[f"- {b}" for b in blockers], ""]
    else:
        lines += ["No P0/P1 blockers detected by the automated gate.", ""]
    if warnings:
        lines += ["### Warnings", *[f"- {w}" for w in warnings], ""]
    lines += ["Auto-merge: **not implemented in v1**.", "WARP🔹CMD final review/merge authority still applies."]
    return "\n".join(lines)


def upsert(repo: str, token: str, number: int, body: str) -> None:
    comments = gh_list(f"/repos/{repo}/issues/{number}/comments", token)
    for c in comments:
        if MARKER in (c.get("body") or ""):
            gh("PATCH", f"/repos/{repo}/issues/comments/{c['id']}", token, {"body": body})
            return
    gh("POST", f"/repos/{repo}/issues/{number}/comments", token, {"body": body})


def main() -> int:
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    number = pr_number()
    pr = gh("GET", f"/repos/{repo}/pulls/{number}", token)
    files = gh_list(f"/repos/{repo}/pulls/{number}/files", token)
    checks = gh("GET", f"/repos/{repo}/commits/{pr['head']['sha']}/check-runs", token).get("check_runs", [])
    blockers, warnings = scan(repo, token, pr, files, checks)
    body = comment_body(pr, blockers, warnings)
    upsert(repo, token, number, body)
    print(body)
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
