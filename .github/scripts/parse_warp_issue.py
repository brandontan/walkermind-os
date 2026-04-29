#!/usr/bin/env python3
"""Parse a WARP task brief issue and validate required fields.

Reads issue body from ISSUE_BODY env var (set by GitHub Actions).
Writes parsed fields to GITHUB_OUTPUT.
Exits 1 and posts error details to MISSING_FIELDS output if validation fails.

Usage:
    ISSUE_BODY="..." python3 parse_warp_issue.py
"""
from __future__ import annotations

import os
import re
import sys

BRANCH_RE = re.compile(r"^WARP/[a-z0-9][a-z0-9\-]*$")

VALID_ROLES = {"WARP•FORGE", "WARP•SENTINEL", "WARP•ECHO"}
VALID_TIERS = {"MINOR", "STANDARD", "MAJOR"}

# Sentinel pairs that GitHub issue forms emit for empty optional fields
EMPTY_MARKERS = {"_No response_", ""}


def extract_field(body: str, heading: str) -> str:
    """Extract the content under a markdown ### heading."""
    pattern = re.compile(
        rf"###\s+{re.escape(heading)}\s*\n(.*?)(?=\n###|\Z)",
        re.DOTALL,
    )
    m = pattern.search(body)
    if not m:
        return ""
    return m.group(1).strip()


def write_output(key: str, value: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            # Use heredoc delimiter for multi-line values
            delimiter = "EOF_WARP"
            f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
    else:
        print(f"OUTPUT {key}={value!r}")


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    if not body:
        print("ERROR: ISSUE_BODY is empty", file=sys.stderr)
        write_output("valid", "false")
        write_output("missing_fields", "ISSUE_BODY is empty — cannot parse")
        return 1

    role = extract_field(body, "Role")
    branch = extract_field(body, "Branch")
    tier = extract_field(body, "Validation Tier")
    scope = extract_field(body, "Scope")
    done_criteria = extract_field(body, "Done Criteria")
    context = extract_field(body, "Context")

    missing: list[str] = []

    # Role validation
    if not role or role in EMPTY_MARKERS:
        missing.append("**Role** — must be one of: WARP•FORGE, WARP•SENTINEL, WARP•ECHO")
    elif role not in VALID_ROLES:
        missing.append(f"**Role** `{role}` is invalid — must be one of: {', '.join(sorted(VALID_ROLES))}")

    # Branch validation
    if not branch or branch in EMPTY_MARKERS:
        missing.append("**Branch** — must be declared in `WARP/{feature}` format")
    elif not BRANCH_RE.match(branch):
        missing.append(
            f"**Branch** `{branch}` is invalid — must match `WARP/{{feature}}` "
            "(lowercase, hyphens only, no dots/underscores/dates)"
        )

    # Tier validation
    if not tier or tier in EMPTY_MARKERS:
        missing.append("**Validation Tier** — must be one of: MINOR, STANDARD, MAJOR")
    elif tier not in VALID_TIERS:
        missing.append(f"**Validation Tier** `{tier}` is invalid — must be one of: {', '.join(VALID_TIERS)}")

    # Scope validation
    if not scope or scope in EMPTY_MARKERS:
        missing.append("**Scope** — cannot be empty")

    # Done criteria validation
    if not done_criteria or done_criteria in EMPTY_MARKERS:
        missing.append("**Done Criteria** — cannot be empty")

    # SENTINEL on non-MAJOR is a hard stop
    if role == "WARP•SENTINEL" and tier in {"MINOR", "STANDARD"}:
        missing.append(
            f"**Hard stop:** WARP•SENTINEL cannot run on {tier} tier — "
            "reclassify to MAJOR or change role"
        )

    if missing:
        missing_text = "\n".join(f"- {m}" for m in missing)
        write_output("valid", "false")
        write_output("missing_fields", missing_text)
        write_output("role", role or "")
        write_output("branch", branch or "")
        write_output("tier", tier or "")
        print(f"VALIDATION FAILED:\n{missing_text}", file=sys.stderr)
        return 1

    # All fields valid — write outputs
    write_output("valid", "true")
    write_output("missing_fields", "")
    write_output("role", role)
    write_output("branch", branch)
    write_output("tier", tier)
    write_output("scope", scope)
    write_output("done_criteria", done_criteria)
    write_output("context", context if context not in EMPTY_MARKERS else "")

    print(f"VALID: role={role} branch={branch} tier={tier}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
