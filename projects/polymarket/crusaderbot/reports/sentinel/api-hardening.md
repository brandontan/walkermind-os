# WARP•SENTINEL VALIDATION — api-hardening (Lane 3a/5)

Validated by: WARP•R00T acting as WARP•SENTINEL (owner-directed post-merge gate)
Date: 2026-05-30 00:16 Asia/Jakarta
Source: projects/polymarket/crusaderbot/reports/forge/api-hardening.md

## Environment
- Validation surface: merged `main` @ a8653c9 (#1455), code-as-truth.
- env: dev (hermetic) — auth/ops surface reviewed as a breaker.

## Validation Context
- Validation Tier: MAJOR (auth + ops/kill-switch surface).
- Claim Level: NARROW INTEGRATION.
- Target: ops leaks no data without a secret; ops mutators never accept a URL
  secret; /autotrade/customize rejects out-of-range sizing; pre-auth endpoints
  IP-rate-limited.

## Phase 0 Checks
- Forge report present at correct path — PASS.
- PROJECT_STATE updated (MERGED #1455) — PASS.
- No `phase*/` folders; risk constants unchanged — PASS.

## Findings (code-as-truth, file:line)
- B1 PASS — `api/ops.py:603` `if not secret:` in `ops_dashboard` returns a 503
  disabled login page (no user counts / kill state / audit tail / health). The
  prior open-dashboard-when-unset data leak is closed.
- B3 PASS — `ops_kill`/`ops_resume` signatures take only
  `x_ops_token: Header(...)` (no `token` query param); `_authorize_mutation`
  no longer accepts `token` and authenticates via header OR cookie-session only
  (`_matches_secret(header)` / `_valid_session(cookie)` + same-origin on cookie).
  Negative + positive paths pinned by test_api_ops.py
  (test_ops_post_rejects_legacy_query_param_token → 403, set_active NOT awaited;
  header path → 303 + cookie, no token in redirect). KILL-SWITCH REACHABILITY
  PRESERVED: header (scripts) + cookie (browser) both still flip it — no
  operator lockout. GET /ops `?token=`→cookie login migration intentionally kept.
- B4 PASS — `webtrader/backend/router.py customize_strategy` rejects out-of-range
  tp(0,10] / sl(0,1] / capital_alloc(0,0.80] / max_position(0,0.10] /
  max_per_trade_usdc>0 / max_per_trade_pct(0,1] with HTTP 400 before the DB
  write. 7 parametrised negative cases pass.
- B5 PASS — `api/per_user_rate_limit.py:86 per_ip_rate_limit` (IP-keyed, shared
  bounded buckets, 429+Retry-After) applied to `/auth/register` (5/min) +
  `/auth/login` (10/min). Limiter + per-IP independence pinned by tests.

## Score Breakdown
- Architecture 19/20 — clean reuse of the bucket machinery; one shared `_consume`.
- Functional 20/20 — all four findings verified, positive + negative.
- Failure modes 19/20 — fail-closed (503 unset, 403 no-cred, 429 overflow, 400
  bad input). (-1: rate-limit buckets in-process — acceptable on single Fly
  primary, matches existing per-user limiter design.)
- Risk 20/20 — global kill switch NOT newly exposed (B1/B3 reduce surface); no
  per-user→global escalation; activation guards + Kelly untouched.
- Infra+TG 10/10 — no infra regressions.
- Latency 10/10 — limiter is O(1) deque ops under one asyncio.Lock.
- TOTAL: 98/100.

## Critical Issues
None found.

## Status
APPROVED.

## PR Gate Result
Already MERGED #1455 + deployed to Fly via CD; owner-directed post-merge
confirmation. No re-merge action required.

## Reasoning
Net attack surface is reduced: the ops console no longer leaks data without a
secret, the kill-switch secret no longer travels in URLs (logs), money-sizing
inputs are bounded, and auth endpoints are throttled — all fail-closed and
test-pinned. 82 ops/rate-limit/multitenant + 13 hardening tests pass; no
kill-switch lockout introduced.

## Fix Recommendations
None blocking. Follow-ups (tracked, separate lanes): B2 SSE-token-exchange
(JWT in stream URL), JWT TTL/revocation, CORS + security-headers middleware.

## Out-of-scope Advisory
B2/JWT-TTL/CORS deliberately deferred — see Lane 3b + audit MEDIUM/LOW backlog.

## Deferred Minor Backlog
- [DEFERRED] JWT 24h TTL + revocation; CORS + security-headers middleware.

## Telegram Visual Preview
N/A — auth/ops HTTP surface; ops console renders a login-only page when
OPS_SECRET is unset.
