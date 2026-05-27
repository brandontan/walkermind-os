# WARP•R00T — H1: Ops-Auth Hardening (Cookie Session, Token Out of URL)

Branch: WARP/ROOT/ops-auth-cookie
Role: WARP•R00T
Date: 2026-05-27
Validation Tier: MAJOR (operator auth surface gating the emergency kill switch)
Claim Level: NARROW INTEGRATION
Validation Target: api/ops.py auth model — cookie session replaces URL-token reliance
Not in Scope: per-operator named accounts (single shared secret retained); /admin bearer auth; live-capital wiring
Suggested Next Step: WARP•SENTINEL validation before merge (MAJOR, security-critical)

---

## 1. What was built

Hardened the `/ops` operator console auth so the secret no longer travels in
the URL. An operator signs in once via `POST /ops/login` (secret in the POST
body over HTTPS) which sets an HttpOnly + Secure + SameSite=Lax cookie
(`ops_session`) holding an **HMAC of `OPS_SECRET`**, not the secret itself.
The dashboard and the kill/resume mutators then authenticate from that cookie.
`GET /ops` renders a login form when unauthenticated (no system data leaks to
anonymous visitors) and the full dashboard once the cookie is present.

Backward-compatible — no kill-switch lockout risk:
- `X-Ops-Token` header still accepted (scripts/CI).
- Legacy `?token=<secret>` still accepted on the mutators; a legacy `?token=`
  GET is auto-migrated (cookie set + 303 redirect to a clean `/ops`).
- On a successful mutator call the cookie is (re)established so a legacy-token
  caller transitions to the cookie session.

Token rotation = change `OPS_SECRET` in the env → HMAC mismatch invalidates
every outstanding cookie.

## 2. Current system architecture

`/ops` is a no-JS HTML console. Auth helpers (all timing-safe via
`secrets.compare_digest`): `_ops_secret`, `_session_token` (HMAC-SHA256),
`_matches_secret`, `_valid_session`, `_is_authenticated`, `_authorize_mutation`,
`_set_session_cookie`. Routes: `GET /ops` (gate + auto-migrate), `POST
/ops/login`, `POST /ops/logout`, `POST /ops/kill`, `POST /ops/resume`. The
mutators delegate to the shared `domain.ops.kill_switch.set_active` and write
the same `kill_switch_history` + `audit.log` rows as before. `OPS_SECRET` unset
→ mutators 503 and the dashboard stays open (cannot gate without a secret).

CSRF posture: mutators authenticate via a SameSite=Lax cookie, which browsers
do not send on cross-site POST → CSRF-safe; the header path is not CSRF-able;
the legacy token path requires the secret. The login body is parsed via
`parse_qs` (not FastAPI `Form`) so the app takes **no** hard dependency on
`python-multipart` (which would otherwise fail at import/boot).

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/api/ops.py` — cookie-session auth, login/logout routes, GET gating, mutator auth via cookie/header/legacy-token.
- `projects/polymarket/crusaderbot/tests/test_api_ops.py` — dashboard tests now authenticate; 4 token tests rewritten; 8 new tests (login/logout/cookie/gating/migration).
- `projects/polymarket/crusaderbot/reports/forge/ops-auth-cookie.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` / `WORKTODO.md` / `CHANGELOG.md` — synced.

## 4. What is working

- `tests/test_api_ops.py`: 48 passed. Full suite: 1808 passed, 1 skipped. ruff + py_compile clean.
- Verified: unauthenticated GET shows only the login form (no data leak); login sets HttpOnly+Secure cookie whose value is not the raw secret; wrong secret sets no cookie; cookie session flips the kill switch; legacy `?token=` still works and auto-migrates; logout clears the cookie; `OPS_SECRET` unset → 503.

## 5. Known issues

- Single shared secret (not per-operator named accounts) — audit rows still record `actor_role="operator"` without a distinct operator identity. Per-operator login was the larger option not chosen for this lane; can be a follow-up if multiple operators are added.
- Cookie lifetime is 7 days; there is no server-side session revocation list (rotation is via `OPS_SECRET` change). Acceptable for a single-owner bot.

## 6. What is next

- WARP•SENTINEL validation (MAJOR, security-critical) before merge — recommended given this gates the emergency kill switch.
- Remaining public-ready lane: C1 live-capital wiring (MAJOR — owner decision + SENTINEL + staged), held until explicit go-live.

Validation handoff:
WARP•SENTINEL validation required for ops-auth hardening before merge.
Source: projects/polymarket/crusaderbot/reports/forge/ops-auth-cookie.md
Tier: MAJOR
