#!/usr/bin/env python3
"""WARP Auto Gate v2 — function-first deputy PR router.

Flow:
  WARP•FORGE -> WARP•GATE -> WARP🔹CMD

Behavior:
  - P0 safety/runtime/capital/credential/live-trading blockers fail the workflow.
  - Non-critical actionable issues are posted as one WARP•FORGE fix task.
  - MAJOR PRs that are pre-handoff ready are routed to WARP•SENTINEL by comment.
  - Clean PRs are marked ready for WARP🔹CMD review.
  - WARP•GATE never merges.

This script is stdlib-only and intended for GitHub Actions.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any


API_BASE = "https://api.github.com"
GATE_COMMENT_MARKER = "<!-- WARP•GATE -->"
PROJECT_ROOT = "projects/polymarket/crusaderbot"

REQUIRED_BODY_FIELDS = [
    "Validation Tier",
    "Claim Level",
    "Validation Target",
    "Not in Scope",
]


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "WARP-Gate/2",
    }


def gh_get(path: str, token: str) -> Any:
    req = urllib.request.Request(f"{API_BASE}{path}", headers=_headers(token))
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def gh_post(path: str, token: str, body: dict[str, Any]) -> Any:
    data = json.dumps(body).encode("utf-8")
    headers = {**_headers(token), "Content-Type": "application/json"}
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def gh_patch(path: str, token: str, body: dict[str, Any]) -> Any:
    data = json.dumps(body).encode("utf-8")
    headers = {**_headers(token), "Content-Type": "application/json"}
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method="PATCH")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_pr_files(repo: str, pr_number: int, token: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = gh_get(
            f"/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}",
            token,
        )
        if not batch:
            break
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return files


def get_check_runs(repo: str, ref: str, token: str) -> list[dict[str, Any]]:
    result = gh_get(f"/repos/{repo}/commits/{ref}/check-runs?per_page=100", token)
    return result.get("check_runs", [])


def find_pr_by_sha(repo: str, sha: str, token: str) -> int | None:
    prs = gh_get(f"/repos/{repo}/pulls?state=open&per_page=100", token)
    for pr in prs:
        if pr.get("head", {}).get("sha") == sha:
            return int(pr["number"])
    return None


def find_existing_gate_comment(repo: str, pr_number: int, token: str) -> int | None:
    page = 1
    while True:
        comments = gh_get(
            f"/repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}",
            token,
        )
        if not comments:
            return None
        for comment in comments:
            if GATE_COMMENT_MARKER in (comment.get("body") or ""):
                return int(comment["id"])
        if len(comments) < 100:
            return None
        page += 1


def post_or_update_comment(repo: str, pr_number: int, token: str, body: str) -> None:
    existing_id = find_existing_gate_comment(repo, pr_number, token)
    if existing_id:
        gh_patch(f"/repos/{repo}/issues/comments/{existing_id}", token, {"body": body})
    else:
        gh_post(f"/repos/{repo}/issues/{pr_number}/comments", token, {"body": body})


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def changed_filenames(files: list[dict[str, Any]]) -> list[str]:
    return [str(file_info.get("filename", "")) for file_info in files]


def added_text_from_patch(patch: str) -> str:
    return "\n".join(
        line[1:]
        for line in (patch or "").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def is_runtime_code(filename: str) -> bool:
    if "/reports/" in filename or "/state/" in filename:
        return False
    return filename.endswith((".py", ".ts", ".tsx", ".js", ".sh", ".yml", ".yaml"))


def is_forge_pr(filenames: list[str]) -> bool:
    return any(is_runtime_code(name) for name in filenames) or any(
        "/reports/forge/" in name for name in filenames
    )


def extract_field(body: str, field: str) -> str:
    """Return a PR body field value.

    Accepts both:
      Field: value
      Field - value

    This fixes the Codex finding where MAJOR routing could be skipped when a
    dash separator was used instead of a colon.
    """
    pattern = re.compile(
        rf"^\s*(?:\*\*)?{re.escape(field)}(?:\*\*)?\s*[:\-]\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(body or "")
    return match.group(1).strip() if match else ""


def has_field(body: str, field: str) -> bool:
    return bool(extract_field(body, field))


def validation_tier(body: str) -> str:
    raw = extract_field(body, "Validation Tier") or extract_field(body, "Tier")
    upper = raw.upper()
    if "MAJOR" in upper:
        return "MAJOR"
    if "STANDARD" in upper:
        return "STANDARD"
    if "MINOR" in upper:
        return "MINOR"
    return "UNKNOWN"


def claim_level(body: str) -> str:
    raw = extract_field(body, "Claim Level")
    upper = raw.upper()
    if "FULL RUNTIME INTEGRATION" in upper:
        return "FULL RUNTIME INTEGRATION"
    if "NARROW INTEGRATION" in upper:
        return "NARROW INTEGRATION"
    if "FOUNDATION" in upper:
        return "FOUNDATION"
    return raw or "UNKNOWN"


def branch_slug(branch: str) -> str:
    return branch.split("/", 1)[1] if branch.startswith("WARP/") else branch.replace("/", "-")


def has_final_output_line(body: str, name: str) -> bool:
    return bool(extract_field(body, name))


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------

def check_branch(branch: str) -> list[str]:
    """Branch findings are routed as fix-required, not hard workflow failures.

    Mr. Walker's intended behavior:
      - accept WARP/HOTFIX-KEYBOARD-MISSING
      - accept WARP/hotfix-keyboard-missing
      - reject/fix lowercase prefix and other invalid formats before CMD merge
      - do not let branch slug cosmetics outrank function/safety
    """
    findings: list[str] = []

    if not branch.startswith("WARP/"):
        findings.append(
            f"Branch `{branch}` should be recreated/renamed under `WARP/{{feature}}` before CMD final merge review."
        )
        return findings

    slug = branch_slug(branch)
    if "/" in slug:
        findings.append(f"Branch `{branch}` has a nested slash. Use one `WARP/{{feature}}` slug.")
    if "_" in slug or "." in slug:
        findings.append(f"Branch `{branch}` contains underscore/dot. Use hyphens only.")
    if re.search(r"(?:20\d{6}|20\d{2}-\d{2}-\d{2})", slug):
        findings.append(f"Branch `{branch}` looks date-suffixed. Use a stable feature slug.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", slug):
        findings.append(f"Branch `{branch}` has invalid slug characters. Use alnum + hyphen only.")

    return findings


def check_pr_body(body: str) -> list[str]:
    missing = [field for field in REQUIRED_BODY_FIELDS if not has_field(body, field)]
    if len(missing) == len(REQUIRED_BODY_FIELDS):
        return [
            "PR body is missing all gate fields: Validation Tier, Claim Level, Validation Target, Not in Scope."
        ]
    return [f"PR body missing `{field}`." for field in missing]


def check_forge_report(files: list[dict[str, Any]], branch: str) -> tuple[list[str], str]:
    filenames = changed_filenames(files)
    if not is_forge_pr(filenames):
        return [], ""

    expected = f"{PROJECT_ROOT}/reports/forge/{branch_slug(branch)}.md"
    forge_reports = [
        name for name in filenames if "/reports/forge/" in name and name.endswith(".md")
    ]

    if expected in filenames:
        return [], expected
    if forge_reports:
        return [
            f"Forge report path should align with branch slug. Expected `{expected}`, found `{forge_reports[0]}`."
        ], forge_reports[0]
    return [f"Forge report missing. Expected `{expected}`."], expected


def check_project_state(files: list[dict[str, Any]]) -> list[str]:
    filenames = changed_filenames(files)
    if any(is_runtime_code(name) for name in filenames) and f"{PROJECT_ROOT}/state/PROJECT_STATE.md" not in filenames:
        return [f"`{PROJECT_ROOT}/state/PROJECT_STATE.md` not updated for code-bearing FORGE PR."]
    return []


def check_hard_stops(files: list[dict[str, Any]]) -> list[str]:
    """Return true P0 findings.

    Pattern strings are built from small pieces to avoid self-triggering when
    this gate script itself is modified and the PR patch contains the scanner
    definitions.
    """
    issues: list[str] = []

    hard_stop_patterns: list[tuple[re.Pattern[str], str]] = [
        (
            re.compile(r"(?:^|\s)import\s+" + "threading" + r"\b|from\s+" + "threading" + r"\s+import", re.MULTILINE),
            "threading import in runtime path",
        ),
        (
            re.compile(
                r"\b" + "kelly_fraction" + r"\s*=\s*" + "1" + r"\.0\b|"
                r"\b" + "a" + r"\s*=\s*" + "1" + r"\.0\b.*[Kk]elly|"
                r"[Kk]elly.*\b" + "a" + r"\s*=\s*" + "1" + r"\.0\b",
                re.IGNORECASE,
            ),
            "full Kelly sizing",
        ),
        (
            re.compile(
                r"except\s*:\s*" + "pass" + r"\b|"
                r"except\s+Exception\s*:\s*(?:\n\s*)?" + "pass" + r"\b",
                re.MULTILINE,
            ),
            "silent exception handling",
        ),
        (
            re.compile(
                "ENABLE_" + "LIVE_" + "TRADING" + r"\s*=\s*" + "True" + r"\b(?!\s*#\s*overridden)",
                re.IGNORECASE,
            ),
            "live-trading guard hardcoded true",
        ),
    ]

    secret_pattern = re.compile(
        r"(?:api[_-]?key|secret[_-]?key|password|private[_-]?key|access[_-]?token)"
        r"\s*[=:]\s*['\"][A-Za-z0-9+/=_\-]{12,}['\"]",
        re.IGNORECASE,
    )

    for file_info in files:
        filename = str(file_info.get("filename", ""))
        added_text = added_text_from_patch(file_info.get("patch", "") or "")

        if re.search(r"(^|/)phase\d+[/_]", filename):
            issues.append(f"P0: forbidden phase*/ folder introduced: `{filename}`.")

        if secret_pattern.search(added_text):
            issues.append(f"P0: potential hardcoded credential in `{filename}`.")

        for pattern, label in hard_stop_patterns:
            if pattern.search(added_text):
                issues.append(f"P0: {label} in `{filename}`.")

    return issues


def check_report_drift(files: list[dict[str, Any]], branch: str) -> list[str]:
    issues: list[str] = []
    for file_info in files:
        filename = str(file_info.get("filename", ""))
        if "/reports/forge/" not in filename or not filename.endswith(".md"):
            continue
        patch = file_info.get("patch", "") or ""
        refs = re.findall(r"Branch\s*:\s*(WARP/[^\s`]+)", patch)
        for ref in refs:
            if ref != branch:
                issues.append(
                    f"Forge report branch reference `{ref}` should match actual PR head `{branch}`."
                )
    return issues


def check_ci(check_runs: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for run in check_runs:
        name = str(run.get("name", ""))
        if name == "WARP Auto Gate":
            continue
        if run.get("status") == "completed" and run.get("conclusion") in {
            "failure",
            "timed_out",
            "cancelled",
        }:
            issues.append(f"CI check `{name}` completed with `{run.get('conclusion')}`.")
    return issues


def sentinel_ready(tier: str, body: str, forge_report: str, fix_items: list[str]) -> bool:
    """Return True only when a MAJOR PR is ready for Sentinel routing.

    This uses tolerant field parsing, so both `Field: value` and
    `Field - value` are accepted. It fixes the Codex review issue where
    literal colon checks could let MAJOR work skip SENTINEL.
    """
    if tier != "MAJOR":
        return False
    if fix_items:
        return False
    if not forge_report:
        return False

    required = ["Report", "State", "Validation Tier", "Claim Level"]
    return all(has_final_output_line(body, field) for field in required)


# ---------------------------------------------------------------------------
# Comment builders
# ---------------------------------------------------------------------------

def build_forge_task(branch: str, tier: str, claim: str, fix_items: list[str]) -> str:
    fixes = "\n".join(f"- {item}" for item in fix_items)
    return f"""WARP•FORGE TASK: Gate fix before CMD review
============
Repo      : https://github.com/bayuewalker/walkermind-os
Project   : CrusaderBot
Repo path : {PROJECT_ROOT}
Branch    : {branch}

ISSUE FOUND:
WARP•GATE found actionable items before WARP🔹CMD merge review.

FIX REQUIRED:
{fixes}

SCOPE:
- Keep behavior unchanged unless the finding explicitly requires behavior correction.
- Preserve PAPER ONLY posture. Do not enable live trading, real CLOB execution, capital, or risk guards.

VALIDATION:
Validation Tier   : {tier if tier != "UNKNOWN" else "STANDARD"}
Claim Level       : {claim}
Validation Target : Gate findings only
Not in Scope      : New features, live trading activation, unrelated cleanup

DONE CRITERIA:
- [ ] Fix applied in same PR or replacement PR
- [ ] Forge report/state references updated truthfully
- [ ] CI/gate re-run clean or remaining items documented

NEXT GATE:
- WARP•GATE re-check -> WARP🔹CMD review
"""


def build_sentinel_task(branch: str, claim: str, forge_report: str) -> str:
    return f"""WARP•SENTINEL TASK: Validate MAJOR FORGE output
=============
Repo         : https://github.com/bayuewalker/walkermind-os
Project      : CrusaderBot
Repo path    : {PROJECT_ROOT}
Branch       : {branch}
Tier         : MAJOR
Claim Level  : {claim}
Source       : {forge_report}

SENTINEL REQUIRED BECAUSE:
Validation Tier is MAJOR and WARP•GATE found no pre-handoff fix blockers.

REQUIRED CHECKS:
- Verify claim against actual code, not report wording.
- Verify runtime/test evidence for claimed behavior.
- Verify risk / execution / state integrity if touched.
- Verify PROJECT_STATE.md remains truthful.
- Preserve PAPER ONLY posture. Do not enable live trading, real CLOB execution, capital, or risk guards.

DELIVERABLES:
- Sentinel report under {PROJECT_ROOT}/reports/sentinel/
- Verdict: APPROVED / CONDITIONAL / BLOCKED
- NEXT GATE: return to WARP🔹CMD
"""


def build_comment(
    branch: str,
    pr_number: int,
    route: str,
    p0_items: list[str],
    fix_items: list[str],
    info_items: list[str],
    sentinel_task: str,
    tier: str,
    claim: str,
) -> str:
    lines = [
        GATE_COMMENT_MARKER,
        f"## WARP•GATE v2 — {route}",
        "",
        f"**Branch:** `{branch}` &nbsp; **PR:** #{pr_number}",
        f"**Tier:** {tier} &nbsp; **Claim:** {claim}",
        "",
    ]

    if p0_items:
        lines += ["### P0 — real blocker", ""]
        lines += [f"- {item}" for item in p0_items]
        lines.append("")

    if fix_items:
        lines += ["### Fix required", "", build_forge_task(branch, tier, claim, fix_items), ""]

    if sentinel_task:
        lines += ["### Sentinel required", "", sentinel_task, ""]

    if info_items:
        lines += ["### Advisory", ""]
        lines += [f"- {item}" for item in info_items]
        lines.append("")

    if route == "READY_FOR_CMD":
        lines += ["Ready for WARP🔹CMD final review. WARP•GATE does not merge.", ""]

    lines += ["---", "_WARP•GATE is deputy automation only. WARP🔹CMD remains final._"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def resolve_pr_number(repo: str, token: str, pr_number_str: str, wr_head_sha: str) -> int | None:
    if pr_number_str:
        try:
            return int(pr_number_str)
        except ValueError:
            raise ValueError(f"PR_NUMBER not an integer: {pr_number_str!r}") from None

    if wr_head_sha:
        return find_pr_by_sha(repo, wr_head_sha, token)

    # Fail closed. Missing PR context is a workflow configuration error.
    raise RuntimeError("Neither PR_NUMBER nor WR_HEAD_SHA is set; refusing to pass gate without PR context.")


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number_str = os.environ.get("PR_NUMBER", "").strip()
    wr_head_sha = os.environ.get("WR_HEAD_SHA", "").strip()

    if not token:
        print("ERROR: GITHUB_TOKEN not set.", file=sys.stderr)
        return 1
    if not repo:
        print("ERROR: GITHUB_REPOSITORY not set.", file=sys.stderr)
        return 1

    try:
        pr_number = resolve_pr_number(repo, token, pr_number_str, wr_head_sha)
    except (RuntimeError, ValueError, urllib.error.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if pr_number is None:
        # WR_HEAD_SHA was provided but did not resolve to an open PR. This is
        # not a success path for PR gating; fail closed so workflow wiring is fixed.
        print(f"ERROR: No open PR found for SHA {wr_head_sha}; refusing to pass gate.", file=sys.stderr)
        return 1

    try:
        pr = gh_get(f"/repos/{repo}/pulls/{pr_number}", token)
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Failed to fetch PR #{pr_number}: HTTP {exc.code}", file=sys.stderr)
        return 1

    branch = str(pr.get("head", {}).get("ref", ""))
    head_sha = str(pr.get("head", {}).get("sha", ""))
    body = pr.get("body", "") or ""
    title = pr.get("title", "") or ""

    if title.lower().startswith("sync:") or "post-merge sync" in title.lower():
        print(f"Skipping gate for sync PR: {title!r}")
        return 0

    try:
        files = get_pr_files(repo, pr_number, token)
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Failed to fetch PR files: HTTP {exc.code}", file=sys.stderr)
        return 1

    try:
        check_runs = get_check_runs(repo, head_sha, token)
    except urllib.error.HTTPError as exc:
        print(f"WARN: Failed to fetch check runs: HTTP {exc.code}", file=sys.stderr)
        check_runs = []

    tier = validation_tier(body)
    claim = claim_level(body)

    p0_items = check_hard_stops(files)

    report_fix_items, forge_report = check_forge_report(files, branch)
    fix_items = (
        check_branch(branch)
        + check_pr_body(body)
        + report_fix_items
        + check_project_state(files)
        + check_report_drift(files, branch)
        + check_ci(check_runs)
    )

    info_items: list[str] = []
    if tier == "MAJOR":
        info_items.append("MAJOR tier detected. WARP•SENTINEL is required before merge.")

    sentinel_task = ""
    if sentinel_ready(tier, body, forge_report, fix_items) and not p0_items:
        sentinel_task = build_sentinel_task(branch, claim, forge_report)

    if p0_items:
        route = "BLOCKED"
    elif sentinel_task:
        route = "SENTINEL_REQUIRED"
    elif fix_items:
        route = "FIX_REQUIRED"
    else:
        route = "READY_FOR_CMD"

    comment = build_comment(
        branch=branch,
        pr_number=pr_number,
        route=route,
        p0_items=p0_items,
        fix_items=fix_items,
        info_items=info_items,
        sentinel_task=sentinel_task,
        tier=tier,
        claim=claim,
    )

    try:
        post_or_update_comment(repo, pr_number, token, comment)
        print("Gate comment posted/updated.")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Failed to post gate comment: {exc}", file=sys.stderr)

    print(f"\nWARP Auto Gate v2  branch={branch}  pr=#{pr_number}")
    print(f"Route       : {route}")
    print(f"P0 blockers : {len(p0_items)}")
    print(f"Fix items   : {len(fix_items)}")
    print(f"Advisory    : {len(info_items)}")

    if p0_items:
        print("\nP0 blockers:")
        for item in p0_items:
            print(f"  {item}")
        print("\nResult: FAILED — real blocker present.")
        return 1

    print("\nResult: PASSED — routed by WARP•GATE. WARP🔹CMD remains final.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
