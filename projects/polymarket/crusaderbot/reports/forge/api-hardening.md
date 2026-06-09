# WARP•R00T FORGE REPORT — api-hardening

Branch: WARP/ROOT/api-hardening
Date: 2026-05-29 23:08 Asia/Jakarta
Lane: 3a/5 of the WARP•R00T full-system pre-public-ready audit fix campaign

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : ops console leaks no data without a secret; ops mutators never accept a URL secret; /autotrade/customize rejects out-of-range sizing; pre-auth endpoints are IP-rate-limited
Not in Scope      : B2 SSE-token-exchange (split to Lane 3b WARP/ROOT/sse-token-exchange); CORS/security-headers + JWT TTL/revocation (tracked, separate); other audit lanes
Suggested Next    : WARP•SENTINEL (MAJOR — auth/ops surface), then Lane 3b (sse-token-exchange)

---

## 1. What was built

Backend API hardening — the contained, unambiguous items from the audit's
public-launch-blocker set:

- **B1 — ops console data exposure when `OPS_SECRET` unset.** `GET /ops`
  previously rendered the full operational dashboard (user counts, kill state,
  audit-log tail, health, version) to any anonymous visitor when no secret was
  configured. Now returns a 503 "disabled" notice with NO operational data.
- **B3 — secret-in-URL on ops mutators.** `POST /ops/kill` + `/ops/resume`
  accepted the `OPS_SECRET` via legacy `?token=` query param, which leaks into
  Fly/proxy/access logs (unauthenticated global kill-switch on leak). Removed
  the `token` param from both mutators and from `_authorize_mutation`; they now
  authenticate via `X-Ops-Token` header (scripts/CI) or the `ops_session`
  cookie (browser) only. The `GET /ops` `?token=`→cookie login auto-migration
  is preserved for operator continuity per WARP🔹CMD direction.
- **B4 — unbounded sizing inputs.** `POST /autotrade/customize` stored
  `tp_pct` / `sl_pct` / `capital_alloc_pct` / `max_position_pct` /
  `max_per_trade_usdc` / `max_per_trade_pct` with no validation (a user could
  set `capital_alloc_pct=99999`, negative TP/SL, etc.). Added range guards:
  tp∈(0,10], sl∈(0,1], capital_alloc∈(0,0.80], max_position∈(0,0.10],
  max_per_trade_usdc>0, max_per_trade_pct∈(0,1].
- **B5 — no rate limit on `/auth/register` + `/auth/login`.** Added a new
  `per_ip_rate_limit` dependency (IP-keyed sibling of the existing per-user
  limiter, sharing the same bounded bucket machinery): register 5/min, login
  10/min per source IP. Stops brute-force / email-enumeration / signup spam
  faster than the 600/min global limiter.

## 2. Current system architecture (relevant slice)

`api/per_user_rate_limit.py` now exposes two builders over one shared
sliding-window store: `per_user_rate_limit(scope, limit)` (keyed on JWT
user_id, post-auth) and `per_ip_rate_limit(scope, limit)` (keyed on
Fly-Client-IP → first XFF hop → socket peer, pre-auth). Both raise 429 +
Retry-After and are memory-bounded (50k keys, idle-evicted).

`api/ops.py` auth model after this lane: cookie session (browser, post-login)
or `X-Ops-Token` header (scripts) for mutators; `GET /ops` additionally
supports a one-time `?token=`→cookie migration; no secret configured = console
disabled (503) and mutators 503.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/api/ops.py (B1 disabled-when-unset; B3 drop ?token= from mutators + _authorize_mutation)
- projects/polymarket/crusaderbot/api/per_user_rate_limit.py (per_ip_rate_limit + shared _consume + _client_ip)
- projects/polymarket/crusaderbot/webtrader/backend/router.py (B4 customize bounds; B5 auth IP limits + import)
- projects/polymarket/crusaderbot/tests/test_api_ops.py (2 tests updated to the new B3 contract)

Created:
- projects/polymarket/crusaderbot/tests/test_api_hardening.py (13 tests: B1 no-data-503, B3 param removal + header-auth, B4 7 out-of-range params, B5 limiter + per-IP independence)

## 4. What is working

- py_compile clean; `ruff` clean on all touched Python.
- New suite 13/13 pass; existing test_api_ops.py (69) + test_rate_limit + test_multitenant_safety green (82 passed together) after updating the 2 obsolete `?token=` tests to the new contract.
- No existing test posts to `/auth/login|register` over HTTP, so the new IP limiter does not affect the suite.

## 5. Known issues

- B2 (JWT in SSE URL) intentionally deferred to Lane 3b (architecturally distinct: short-lived SSE token exchange across backend + frontend).
- JWT 24h TTL / revocation and CORS + security-headers middleware remain audit MEDIUM/LOW items — tracked, not in this lane.
- Rate-limit buckets are in-process (single Fly primary) — consistent with the existing per-user limiter's design note.

## 6. What is next

- WARP•SENTINEL validation (MAJOR — auth/ops surface).
- Lane 3b: WARP/ROOT/sse-token-exchange (B2).
- Lanes 4-5: tg-callback-routing, live-path-hardening.

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
