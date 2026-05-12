#!/usr/bin/env python3
"""WARP Auto Gate v1 — stdlib-only PR gate enforcer.

Checks AGENTS.md PR gate rules (Gates 1-8 + CI status) and posts an
idempotent comment on the PR. Exits non-zero when P0/P1 blockers exist.

Environment variables required:
  GITHUB_TOKEN       — token with pull-requests:write and checks:read
  GITHUB_REPOSITORY  — owner/repo (set automatically by GitHub Actions)
  PR_NUMBER          — PR number (set explicitly for pull_request_target /
                       workflow_dispatch events)
  WR_HEAD_SHA        — commit SHA from workflow_run event (used to look up
                       the PR when PR_NUMBER is not set)
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

GATE_COMMENT_MARKER = "<!-- WARP-AUTO-GATE -->"
API_BASE = "https://api.github.com"


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "WARP-Auto-Gate/1",
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
        batch: list[dict[str, Any]] = gh_get(
            f"/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}", token
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
    prs: list[dict[str, Any]] = gh_get(
        f"/repos/{repo}/pulls?state=open&per_page=100", token
    )
    for pr in prs:
        if pr["head"]["sha"] == sha:
            return int(pr["number"])
    return None


def find_existing_gate_comment(repo: str, pr_number: int, token: str) -> int | None:
    page = 1
    while True:
        comments: list[dict[str, Any]] = gh_get(
            f"/repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}", token
        )
        if not comments:
            break
        for comment in comments:
            if GATE_COMMENT_MARKER in comment.get("body", ""):
                return int(comment["id"])
        if len(comments) < 100:
            break
        page += 1
    return None


def post_or_update_comment(repo: str, pr_number: int, token: str, body: str) -> None:
    existing_id = find_existing_gate_comment(repo, pr_number, token)
    if existing_id:
        gh_patch(f"/repos/{repo}/issues/comments/{existing_id}", token, {"body": body})
    else:
        gh_post(f"/repos/{repo}/issues/{pr_number}/comments", token, {"body": body})


# ---------------------------------------------------------------------------
# Gate checks — each returns a list of issue strings
# ---------------------------------------------------------------------------

_BRANCH_RE = re.compile(r"^WARP/[a-z0-9][a-z0-9\-]*$")


def check_gate1_branch(branch: str) -> list[str]:
    """Gate 1 — Branch format (P0 if fail)."""
    if branch.startswith("claude/"):
        return [f"P0: Branch `{branch}` uses forbidden `claude/*` prefix."]
    if branch.startswith("NWAP/"):
        return [f"P0: Branch `{branch}` uses historical `NWAP/*` prefix — not valid for new work."]
    if not _BRANCH_RE.match(branch):
        return [
            f"P0: Branch `{branch}` does not match required format "
            "`WARP/{{feature-slug}}` (lowercase slug, no dots/underscores/dates)."
        ]
    return []


_REQUIRED_BODY_FIELDS = [
    "Validation Tier",
    "Claim Level",
    "Validation Target",
    "Not in Scope",
]


def check_gate2_pr_body(pr_body: str) -> list[str]:
    """Gate 2 — Required PR body declarations (P1 each, P0 if all missing)."""
    missing = [f for f in _REQUIRED_BODY_FIELDS if f not in (pr_body or "")]
    if len(missing) == len(_REQUIRED_BODY_FIELDS):
        return ["P0: All 4 required PR body fields are missing (Validation Tier, Claim Level, Validation Target, Not in Scope)."]
    return [f"P1: Missing required PR body field: `{f}`." for f in missing]


def _is_code_pr(filenames: list[str]) -> bool:
    code_exts = {".py", ".yml", ".yaml", ".ts", ".tsx", ".js", ".sh"}
    return any(
        any(f.endswith(ext) for ext in code_exts)
        and "/reports/" not in f
        and "/state/" not in f
        for f in filenames
    )


def check_gate3_forge_report(files: list[dict[str, Any]], branch: str) -> list[str]:
    """Gate 3 — Forge report presence for code/state PRs (P1 if missing)."""
    filenames = [f["filename"] for f in files]
    if not _is_code_pr(filenames):
        return []
    feature = branch.removeprefix("WARP/") if branch.startswith("WARP/") else branch
    expected = f"projects/polymarket/crusaderbot/reports/forge/{feature}.md"
    forge_reports = [f for f in filenames if "/reports/forge/" in f and f.endswith(".md")]
    if expected not in filenames and not forge_reports:
        return [f"P1: Forge report not found. Expected `{expected}`."]
    return []


def check_gate4_project_state(files: list[dict[str, Any]]) -> list[str]:
    """Gate 4 — PROJECT_STATE.md updated in PR (P1 if missing)."""
    filenames = [f["filename"] for f in files]
    if not _is_code_pr(filenames):
        return []
    if not any("state/PROJECT_STATE.md" in f for f in filenames):
        return ["P1: `PROJECT_STATE.md` not updated in this PR."]
    return []


_HARD_STOP_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?:^|\s)import\s+threading\b|from\s+threading\s+import",
        "threading import (asyncio only)",
    ),
    (
        r"\bkelly_fraction\s*=\s*1\.0\b|\ba\s*=\s*1\.0\b.*[Kk]elly|[Kk]elly.*\ba\s*=\s*1\.0\b",
        "full Kelly fraction a=1.0",
    ),
    (
        r"except\s*:\s*pass\b|except\s+Exception\s*:\s*\n?\s*pass\b",
        "silent exception (except: pass)",
    ),
    (
        r"ENABLE_LIVE_TRADING\s*=\s*[Tt]rue\b(?!\s*#\s*overridden)",
        "ENABLE_LIVE_TRADING hardcoded True (activation guard bypass)",
    ),
]

_SECRET_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?:api[_-]?key|secret[_-]?key|password|private[_-]?key|access[_-]?token)"
        r"\s*[=:]\s*['\"][A-Za-z0-9+/=_\-]{12,}['\"]",
        "hardcoded credential",
    ),
]

_PHASE_FOLDER_RE = re.compile(r"^phase\d+[/_]")


def check_gate5_hard_stops(files: list[dict[str, Any]]) -> list[str]:
    """Gate 5 — Hard stops in added lines (P0 if found)."""
    issues: list[str] = []
    for file_info in files:
        filename = file_info["filename"]
        patch = file_info.get("patch", "") or ""
        added_lines = [
            line[1:]
            for line in patch.split("\n")
            if line.startswith("+") and not line.startswith("+++")
        ]
        added_text = "\n".join(added_lines)

        for pattern, label in _HARD_STOP_PATTERNS:
            if re.search(pattern, added_text, re.MULTILINE):
                issues.append(f"P0: Hard stop in `{filename}`: {label}.")

        for pattern, label in _SECRET_PATTERNS:
            if re.search(pattern, added_text, re.IGNORECASE):
                issues.append(f"P0: Potential {label} in `{filename}`.")

        if _PHASE_FOLDER_RE.match(filename):
            issues.append(f"P0: phase*/ folder detected: `{filename}`.")

    return issues


def check_gate6_drift(files: list[dict[str, Any]], branch: str) -> list[str]:
    """Gate 6 — Drift checks (P1 if found)."""
    issues: list[str] = []
    for file_info in files:
        filename = file_info["filename"]
        if "/reports/forge/" not in filename or not filename.endswith(".md"):
            continue
        patch = file_info.get("patch", "") or ""
        branch_refs = re.findall(r"Branch\s*:\s*(WARP/[^\s`]+)", patch)
        for ref in branch_refs:
            if ref != branch:
                issues.append(
                    f"P1: Branch reference `{ref}` in forge report "
                    f"`{filename}` does not match PR head branch `{branch}`."
                )
    return issues


def check_gate7_merge_order(files: list[dict[str, Any]], pr_title: str) -> list[str]:
    """Gate 7 — PR type and merge order (P1 if sentinel-only PR)."""
    if pr_title.lower().startswith("sync:") or "post-merge sync" in pr_title.lower():
        return []
    filenames = [f["filename"] for f in files]
    sentinel_reports = [f for f in filenames if "/reports/sentinel/" in f]
    non_meta = [
        f for f in filenames
        if "/reports/sentinel/" not in f and "/state/" not in f and "/reports/forge/" not in f
    ]
    if sentinel_reports and not non_meta:
        return [
            "P1: This PR appears to contain only a WARP•SENTINEL report. "
            "Ensure the corresponding WARP•FORGE PR is merged first."
        ]
    return []


def check_gate8_major_flag(pr_body: str) -> list[str]:
    """Gate 8 — MAJOR tier informational flag (P1 INFO)."""
    if re.search(r"Validation\s+Tier\s*[:\-]\s*MAJOR|^Tier\s*[:\-]\s*MAJOR", pr_body or "", re.MULTILINE | re.IGNORECASE):
        return ["P1 INFO: Validation Tier is MAJOR — WARP•SENTINEL audit required before merge."]
    return []


def check_ci_failures(check_runs: list[dict[str, Any]]) -> list[str]:
    """Check for completed check-run failures (P1 each)."""
    issues: list[str] = []
    for run in check_runs:
        name = run.get("name", "")
        if name == "WARP Auto Gate":
            continue
        status = run.get("status", "")
        conclusion = run.get("conclusion", "")
        if status == "completed" and conclusion in ("failure", "timed_out", "cancelled"):
            issues.append(f"P1: CI check `{name}` completed with status `{conclusion}`.")
    return issues


# ---------------------------------------------------------------------------
# Comment builder
# ---------------------------------------------------------------------------

def build_comment(branch: str, pr_number: int, all_issues: list[tuple[str, list[str]]]) -> str:
    p0 = [i for _, issues in all_issues for i in issues if i.startswith("P0")]
    p1 = [i for _, issues in all_issues for i in issues if i.startswith("P1") and "INFO" not in i]
    info = [i for _, issues in all_issues for i in issues if "P1 INFO" in i]

    if p0:
        verdict = "\U0001f534 BLOCKED"
    elif p1:
        verdict = "\U0001f7e1 NEEDS FIX"
    else:
        verdict = "\U0001f7e2 PASS"

    lines = [
        GATE_COMMENT_MARKER,
        f"## WARP Auto Gate v1 — {verdict}",
        "",
        f"**Branch:** `{branch}` &nbsp; **PR:** #{pr_number}",
        "",
    ]

    if p0:
        lines += ["### P0 — Block Merge", ""]
        lines += [f"- {i}" for i in p0]
        lines.append("")

    if p1:
        lines += ["### P1 — Must Fix Before Merge", ""]
        lines += [f"- {i}" for i in p1]
        lines.append("")

    if info:
        lines += ["### Informational", ""]
        lines += [f"- {i}" for i in info]
        lines.append("")

    if not p0 and not p1:
        lines.append("All gate checks passed. WARP\U0001f539CMD review required before merge.")
        lines.append("")

    lines += [
        "---",
        "_WARP Auto Gate v1 — repo automation only. No CrusaderBot runtime changes._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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

    # Resolve PR number
    pr_number: int | None = None
    if pr_number_str:
        try:
            pr_number = int(pr_number_str)
        except ValueError:
            print(f"ERROR: PR_NUMBER not an integer: {pr_number_str!r}", file=sys.stderr)
            return 1
    elif wr_head_sha:
        try:
            pr_number = find_pr_by_sha(repo, wr_head_sha, token)
        except urllib.error.HTTPError as exc:
            print(f"WARN: Failed to search PRs by SHA: HTTP {exc.code}", file=sys.stderr)
        if pr_number is None:
            print(f"No open PR found for SHA {wr_head_sha} — nothing to gate.")
            return 0
    else:
        print("ERROR: Neither PR_NUMBER nor WR_HEAD_SHA is set.", file=sys.stderr)
        return 1

    # Fetch PR metadata
    try:
        pr: dict[str, Any] = gh_get(f"/repos/{repo}/pulls/{pr_number}", token)
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Failed to fetch PR #{pr_number}: HTTP {exc.code}", file=sys.stderr)
        return 1

    branch: str = pr["head"]["ref"]
    pr_body: str = pr.get("body", "") or ""
    pr_title: str = pr.get("title", "") or ""
    head_sha: str = pr["head"]["sha"]

    # Skip sync / post-merge commits
    if pr_title.lower().startswith("sync:") or "post-merge sync" in pr_title.lower():
        print(f"Skipping gate for sync PR: {pr_title!r}")
        return 0

    # Fetch PR files
    try:
        files = get_pr_files(repo, pr_number, token)
    except urllib.error.HTTPError as exc:
        print(f"WARN: Failed to fetch PR files: HTTP {exc.code}")
        files = []

    # Fetch check runs (best-effort)
    try:
        check_runs = get_check_runs(repo, head_sha, token)
    except urllib.error.HTTPError as exc:
        print(f"WARN: Failed to fetch check runs: HTTP {exc.code}")
        check_runs = []

    # Run all gates
    all_issues: list[tuple[str, list[str]]] = [
        ("Gate 1 — Branch Format", check_gate1_branch(branch)),
        ("Gate 2 — PR Body Declarations", check_gate2_pr_body(pr_body)),
        ("Gate 3 — Forge Report", check_gate3_forge_report(files, branch)),
        ("Gate 4 — PROJECT_STATE.md", check_gate4_project_state(files)),
        ("Gate 5 — Hard Stops", check_gate5_hard_stops(files)),
        ("Gate 6 — Drift Checks", check_gate6_drift(files, branch)),
        ("Gate 7 — Merge Order", check_gate7_merge_order(files, pr_title)),
        ("Gate 8 — MAJOR Flag", check_gate8_major_flag(pr_body)),
        ("CI Status", check_ci_failures(check_runs)),
    ]

    # Build and post comment (best-effort — gate result still surfaced in logs)
    comment_body = build_comment(branch, pr_number, all_issues)
    try:
        post_or_update_comment(repo, pr_number, token, comment_body)
        print("Gate comment posted/updated.")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Failed to post gate comment: {exc}")

    # Print summary
    p0_count = sum(1 for _, issues in all_issues for i in issues if i.startswith("P0"))
    p1_count = sum(1 for _, issues in all_issues for i in issues if i.startswith("P1") and "INFO" not in i)

    print(f"\nWARP Auto Gate v1  branch={branch}  pr=#{pr_number}")
    print(f"P0 blockers : {p0_count}")
    print(f"P1 must-fix : {p1_count}")

    for gate_name, issues in all_issues:
        if issues:
            print(f"\n{gate_name}:")
            for issue in issues:
                print(f"  {issue}")

    if p0_count > 0 or p1_count > 0:
        print("\nResult: FAILED — blockers present.")
        return 1

    print("\nResult: PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
