# WARP•R00T — Inbound HTTP Rate Limiting (H2)

Branch: WARP/ROOT/api-rate-limit
Role: WARP•R00T
Date: 2026-05-27
Validation Tier: STANDARD (public-facing runtime behavior; no trading-core / capital / risk change)
Claim Level: NARROW INTEGRATION
Validation Target: per-client request throttling on the public API surface; health/readiness + Telegram webhook exempt
Not in Scope: per-user (JWT) keying, Redis-backed shared store, ops/admin auth changes (H1), live-trading paths
Suggested Next Step: WARP🔹CMD review + Fly redeploy; next lane H1 (ops-auth hardening)

---

## 1. What was built

`RateLimitMiddleware` — an inbound, per-client sliding-window HTTP rate
limiter wired as the outermost ASGI middleware. It closes audit finding H2
(no inbound abuse control for untrusted public users). Requests beyond the
configured ceiling get `429 Too Many Requests` with a `Retry-After` header;
each throttle event logs a structured WARNING (no silent drop).

## 2. Current system architecture

- Middleware: `BaseHTTPMiddleware` subclass, same style as the existing
  `RequestLogMiddleware`. Added last in `main.py` so it is the outermost
  layer and rejects abusive clients before any downstream work.
- Algorithm: rolling window per client key — a `deque` of monotonic
  timestamps, pruned to `now - window` on each hit; over `RATE_LIMIT_RPM`
  within the window => 429. asyncio-only (`asyncio.Lock`), no threading.
- Client key: `Fly-Client-IP` → first `X-Forwarded-For` hop → socket peer.
- Memory bound: distinct client keys capped at 10,000; idle clients evicted
  under the lock when the cap is hit, so a unique-IP spray cannot grow the
  table without bound.
- Exemptions: `/health`, `/ready`, `/api/web/health`, `/telegram/webhook`
  (platform probes + secret-gated update delivery never throttled). SSE
  `/api/web/stream` is a single long-lived GET and counts as one request.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/api/rate_limit.py` — new middleware.
- `projects/polymarket/crusaderbot/main.py` — import + `add_middleware`.
- `projects/polymarket/crusaderbot/config.py` — `RATE_LIMIT_ENABLED`,
  `RATE_LIMIT_RPM` (120), `RATE_LIMIT_WINDOW_SECONDS` (60).
- `projects/polymarket/crusaderbot/tests/test_rate_limit.py` — 6 hermetic tests.

## 4. What is working

- 6/6 new tests pass; full suite **1798 passed, 1 skipped**; ruff clean.
- Verified: under-limit allowed; over-limit → 429 + Retry-After ≥ 1; per-IP
  isolation; exempt `/health` never throttled (10× over limit); disabled
  flag = pass-through; XFF first-hop keying.
- No trading/risk/capital code touched; PAPER posture unchanged.

## 5. Known issues

- Per-process limiter (single Fly instance assumption). If the app is scaled
  horizontally, switch to a Redis-backed store — config knobs already exist.
- IP-keyed, not user-keyed: clients behind a shared NAT share a budget. The
  120 rpm default is generous enough that normal dashboard use is unaffected;
  tune `RATE_LIMIT_RPM` if a legitimate shared-egress user is throttled.

## 6. What is next

WARP🔹CMD review (STANDARD). Then Fly redeploy to activate. Next recommended
lane: H1 ops-auth hardening (token-out-of-URL + per-operator).

Validation handoff:
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/api-rate-limit.md
Tier: STANDARD
