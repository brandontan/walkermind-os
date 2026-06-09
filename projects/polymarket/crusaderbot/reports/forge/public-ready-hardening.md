# WARP•R00T — Public-Ready Hardening Audit

Branch: WARP/ROOT/public-ready-hardening
Role: WARP•R00T
Date: 2026-05-27
Validation Tier: MAJOR (touches live-trading readiness + security posture)
Claim Level: FOUNDATION (audit + one safe doc fix; LIVE/security lanes deferred)
Validation Target: end-to-end readiness for (a) public multi-user exposure and (b) flip-to-LIVE capability, guards remaining OFF
Not in Scope: enabling live trading, wiring real on-chain capital movement, rewriting ops auth, applying production migrations
Suggested Next Step: WARP🔹CMD selects which CRITICAL/HIGH lanes to open; each MAJOR lane runs through WARP•SENTINEL before merge

---

## 1. What was built

A read-only readiness audit of the crusaderbot package against two goals set
by WARP🔹CMD: public multi-user exposure, and flip-to-LIVE capability with
safety guards kept OFF. One safe, public-facing fix was applied in this lane:
`privacy-policy.md` rewritten from a stale "Custom GPT" stub into a real
privacy policy for the trading bot. All higher-risk findings are enumerated as
declared lanes — not changed in this sweep.

## 2. Current system architecture

Audit confirmed the safety core is intact and the locked pipeline
(DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING) is honored.

PASS (verified this audit, file:line):
- No hardcoded secrets in the bot package (0 matches); `.env` gitignored, only
  `.env.example` tracked.
- `ENABLE_LIVE_TRADING=False` (config.py:148) and `="false"` in fly.toml;
  `CAPITAL_MODE_CONFIRMED="false"`; `EXECUTION_PATH_VALIDATED=False`
  (config.py:149). Three-guard live sequence gated at config.py:353.
- No `threading` use (only docstring mentions); asyncio-only honored.
- Kelly clamped to `K.KELLY_FRACTION` (domain/risk/gate.py:382), profiles cap
  at 0.25 (domain/risk/constants.py); full Kelly impossible.
- No silent failures: every `except` is typed (InvalidOperation / BadRequest /
  SystemExit); no `except: pass`.
- Outbound rate limiting present: CLOB token-bucket `CLOB_RATE_LIMIT_RPS=10`
  (config.py:305); Telegram 429 RetryAfter honored (notifications.py).
- Live-readiness validator exists (services/validation/readiness_validator.py)
  and FAILs if any guard is prematurely True.

## 3. Files created / modified (full repo-root paths)

- `privacy-policy.md` — rewritten into a real CrusaderBot privacy policy.
- `projects/polymarket/crusaderbot/reports/forge/public-ready-hardening.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — 7-section update.
- `projects/polymarket/crusaderbot/state/WORKTODO.md` — public-ready lanes added under CMD direction.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry.

## 4. What is working

PAPER posture is public-safe today: guards OFF, secrets clean, RLS on 42/43
tables, risk fences enforced, no silent failures, outbound throttling in place.
The privacy policy now accurately describes the trading bot rather than an
unrelated GPT.

## 5. Known issues — findings (severity-ordered, file:line)

CRITICAL (LIVE blocker — must be a SENTINEL-gated lane, owner decision required):
- C1 — On-chain fund movement NOT wired. `wallet/withdrawals.py:158` raises
  `NotImplementedError` for the live withdraw path; nightly sweep is
  logical-only and on-chain redeem is gated behind `EXECUTION_PATH_VALIDATED`
  (scheduler.py:711, services/redeem/redeem_router.py:459). Consequence: the
  system CANNOT be flipped fully live for deposit/withdraw/settlement flows —
  it is paper-complete, not live-complete. Wiring real capital is a MAJOR,
  high-blast-radius change; do NOT do it in a sweep.

HIGH (pre-public / pre-live hardening):
- H1 — Ops auth is intentionally minimal: shared `OPS_SECRET` accepted via
  `?token=` in the URL, no per-operator login, no token rotation
  (api/ops.py:26-36). Documented as acceptable for paper beta; for public/live
  it is a real security item (token leaks via browser history / referrer).
- H2 — No INBOUND rate limiting / abuse control for untrusted public users on
  the API and bot surfaces (only outbound CLOB/Telegram throttling exists). A
  public launch exposes scan/trade/SSE endpoints to abuse.
- H3 — (FIXED THIS LANE) `privacy-policy.md` was a stale stub describing a
  "Walker AI Trading Team Custom GPT" with contact `cbayue@gmail.com` — wrong
  product and wrong contact for a public trading bot. Rewritten.

MEDIUM:
- M1 — 1 of 43 public tables remains RLS-disabled (per PROJECT_STATE NEXT
  PRIORITY); close before public exposure.
- M2 — WebTrader ships a ~690 kB single-chunk bundle and has no frontend test
  framework (no vitest/jest in webtrader/frontend/package.json).
- M3 — `check_alchemy_ws` (monitoring/health.py:132) is TCP-only; does not
  perform a full WS handshake, so health can read green on a broken WS.
- M4 — structlog migration deferred for top-8 stdlib-logging files (M-3 lane).
- M5 — F-HIGH-2 secondary: Phase C `evaluate_publications_for_user` may yield
  zero candidates (6,964 publications, 0 trades) — separate follow-up.

LOW:
- L1 — README badges still frame the repo as `Private` / `Paper Beta`; update
  framing when the public posture is decided.
- L2 — Pending Fly.io redeploy for PR #1392 + #1394 (state-tracked).

## 6. What is next

WARP🔹CMD to choose which lanes to open. Recommended order for "LIVE anytime":
1. H2 inbound rate limiting (self-contained, STANDARD, testable).
2. H1 ops auth hardening (token-out-of-URL + per-operator) — MAJOR, SENTINEL.
3. M1 RLS last table + M3 WS handshake (small, MAJOR-adjacent).
4. C1 live capital wiring — MAJOR, owner decision + SENTINEL + staged rollout;
   the single biggest blocker to genuine LIVE readiness.

Validation handoff:
WARP•SENTINEL validation required for any C1/H1 lane before merge.
Source: projects/polymarket/crusaderbot/reports/forge/public-ready-hardening.md
Tier: MAJOR
