#!/usr/bin/env python3
"""WARP•GATE Event Dispatcher — stdlib only.

Normalizes GitHub webhook payloads into a clean WARP•GATE event envelope
and posts to Base44 agent API + gateWebhook endpoint.
"""
from __future__ import annotations
import json, os, sys, urllib.request, urllib.error
from typing import Any

BASE44_AGENT_URL = "https://app.base44.com/api/agents/69f0641f438b21f8ef2e1218/conversations"
GATE_WEBHOOK_URL = "https://warpcmd-ef2e1218.base44.app/functions/gateWebhook"

def _headers_base44(api_key: str) -> dict:
    return {
        "Content-Type": "application/json",
        "api_key": api_key,
        "User-Agent": "WalkerMind-WARP-Gate/3.0",
    }

def _headers_webhook(secret: str) -> dict:
    return {
        "Content-Type": "application/json",
        "x-warp-secret": secret,
        "User-Agent": "WalkerMind-WARP-Gate/3.0",
    }

def post(url: str, headers: dict, body: dict, timeout: int = 20) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()[:600]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return 0, str(e)

def build_envelope() -> dict[str, Any]:
    ev   = os.environ.get("GITHUB_EVENT_NAME", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    # PR events
    pr_action = os.environ.get("PR_ACTION", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    pr_title  = os.environ.get("PR_TITLE", "")
    pr_body   = os.environ.get("PR_BODY", "")
    pr_branch = os.environ.get("PR_BRANCH", "")
    pr_sha    = os.environ.get("PR_SHA", "")
    pr_author = os.environ.get("PR_AUTHOR", "")
    pr_url    = os.environ.get("PR_URL", "")

    # Issue events
    issue_action = os.environ.get("ISSUE_ACTION", "")
    issue_number = os.environ.get("ISSUE_NUMBER", "")
    issue_title  = os.environ.get("ISSUE_TITLE", "")
    issue_body   = os.environ.get("ISSUE_BODY", "")
    issue_url    = os.environ.get("ISSUE_URL", "")
    issue_labels = os.environ.get("ISSUE_LABELS", "")

    # Comment events
    comment_body   = os.environ.get("COMMENT_BODY", "")
    comment_author = os.environ.get("COMMENT_AUTHOR", "")
    comment_url    = os.environ.get("COMMENT_URL", "")

    actor = os.environ.get("GITHUB_ACTOR", "")

    envelope: dict[str, Any] = {
        "event": ev,
        "repo": repo,
        "actor": actor,
        "warp_gate": True,
    }

    if ev in ("pull_request", "pull_request_target"):
        envelope["action"] = pr_action
        envelope["pull_request"] = {
            "number": int(pr_number) if pr_number else 0,
            "title": pr_title,
            "body": pr_body,
            "branch": pr_branch,
            "sha": pr_sha,
            "author": pr_author,
            "url": pr_url,
        }

    elif ev == "pull_request_review_comment":
        envelope["action"] = pr_action
        envelope["pull_request"] = {
            "number": int(pr_number) if pr_number else 0,
            "title": pr_title,
            "branch": pr_branch,
            "url": pr_url,
        }
        envelope["comment"] = {
            "body": comment_body,
            "author": comment_author,
            "url": comment_url,
        }

    elif ev == "issue_comment":
        if pr_number:
            # comment on a PR
            envelope["action"] = "pr_comment"
            envelope["pull_request"] = {
                "number": int(pr_number),
                "title": pr_title,
                "branch": pr_branch,
                "url": pr_url,
            }
        else:
            envelope["action"] = "issue_comment"
            envelope["issue"] = {
                "number": int(issue_number) if issue_number else 0,
                "title": issue_title,
                "url": issue_url,
            }
        envelope["comment"] = {
            "body": comment_body,
            "author": comment_author,
            "url": comment_url,
        }

    elif ev == "issues":
        envelope["action"] = issue_action
        envelope["issue"] = {
            "number": int(issue_number) if issue_number else 0,
            "title": issue_title,
            "body": issue_body,
            "labels": issue_labels,
            "url": issue_url,
        }

    return envelope

def human_message(env: dict) -> str:
    ev     = env.get("event", "")
    action = env.get("action", "")
    repo   = env.get("repo", "")
    actor  = env.get("actor", "")

    if ev in ("pull_request", "pull_request_target"):
        pr = env.get("pull_request", {})
        return (
            f"WARP\u2022GATE EVENT: pull_request.{action}\n\n"
            f"Repo   : {repo}\n"
            f"PR     : #{pr.get('number')} — {pr.get('title')}\n"
            f"Branch : {pr.get('branch')}\n"
            f"Author : {pr.get('author')}\n"
            f"URL    : {pr.get('url')}\n\n"
            f"Run gate review per AGENTS.md rules. "
            f"Read PR diff, check tier, declarations, hard stops, forge report, state files. "
            f"Post one batched DECISION comment on the PR."
        )

    elif ev == "pull_request_review_comment":
        pr  = env.get("pull_request", {})
        cmt = env.get("comment", {})
        return (
            f"WARP\u2022GATE EVENT: pr_review_comment.{action}\n\n"
            f"Repo    : {repo}\n"
            f"PR      : #{pr.get('number')} — {pr.get('title')}\n"
            f"Comment : {cmt.get('body','')[:300]}\n"
            f"Author  : {cmt.get('author')}\n"
            f"URL     : {cmt.get('url')}\n\n"
            f"Classify comment: BLOCKER / MINOR SAFE FIX / IGNORE. "
            f"If BLOCKER: post hold reason. If MINOR SAFE FIX: batch into WARP\u2022FORGE task. "
            f"If IGNORE: no action."
        )

    elif ev == "issue_comment":
        cmt = env.get("comment", {})
        if "pull_request" in env:
            pr = env["pull_request"]
            return (
                f"WARP\u2022GATE EVENT: issue_comment on PR\n\n"
                f"Repo    : {repo}\n"
                f"PR      : #{pr.get('number')} — {pr.get('title')}\n"
                f"Comment : {cmt.get('body','')[:300]}\n"
                f"Author  : {cmt.get('author')}\n\n"
                f"Classify and route per PR REVIEW AUTO-TRIAGE rules in COMMANDER.md."
            )
        iss = env.get("issue", {})
        return (
            f"WARP\u2022GATE EVENT: issue_comment\n\n"
            f"Repo    : {repo}\n"
            f"Issue   : #{iss.get('number')} — {iss.get('title')}\n"
            f"Comment : {cmt.get('body','')[:300]}\n"
            f"Author  : {cmt.get('author')}\n\n"
            f"Assess if comment requires a WARP\u2022FORGE task or WARP\u2022SENTINEL routing."
        )

    elif ev == "issues":
        iss = env.get("issue", {})
        return (
            f"WARP\u2022GATE EVENT: issues.{action}\n\n"
            f"Repo   : {repo}\n"
            f"Issue  : #{iss.get('number')} — {iss.get('title')}\n"
            f"Labels : {iss.get('labels')}\n"
            f"Actor  : {actor}\n"
            f"URL    : {iss.get('url')}\n\n"
            f"Assess issue. If label contains warp:sentinel or major, "
            f"prepare WARP\u2022SENTINEL routing. "
            f"Otherwise classify and route per AGENTS.md."
        )

    return f"WARP\u2022GATE EVENT: {ev}.{action} — {repo}"


def main() -> int:
    api_key = os.environ.get("BASE44_API_KEY", "")
    secret  = os.environ.get("WARP_WEBHOOK_SECRET", "")

    if not api_key or not secret:
        print("WARN: BASE44_API_KEY or WARP_WEBHOOK_SECRET not configured — dispatch skipped")
        return 0

    envelope = build_envelope()
    message  = human_message(envelope)
    ev       = envelope.get("event", "")
    action   = envelope.get("action", "")

    print(f"Event  : {ev}.{action}")
    print(f"Repo   : {envelope.get('repo')}")

    # 1 — Post to Base44 agent (creates a new conversation = new gate session)
    agent_body = {
        "messages": [{"role": "user", "content": message}],
        "metadata": {"source": "github-action", "event": ev, "action": action},
    }
    status, body = post(BASE44_AGENT_URL, _headers_base44(api_key), agent_body)
    print(f"Base44 agent   : HTTP {status} — {body[:200]}")
    if status not in (200, 201):
        print("WARNING: Base44 agent post failed.", file=sys.stderr)

    # 2 — Also fire gateWebhook for legacy compatibility
    status2, body2 = post(GATE_WEBHOOK_URL, _headers_webhook(secret), envelope)
    print(f"Gate webhook   : HTTP {status2} — {body2[:200]}")
    if status2 not in (200, 201, 204):
        print("WARNING: gateWebhook post failed.", file=sys.stderr)

    # Only hard-fail on agent post failure
    return 0 if status in (200, 201) else 1

if __name__ == "__main__":
    sys.exit(main())
