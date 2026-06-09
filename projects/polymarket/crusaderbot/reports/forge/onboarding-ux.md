# onboarding-ux

Validation Tier: **STANDARD**
Claim Level: **NARROW INTEGRATION**
Validation Target: Public-launch legal surface — Terms of Service stub + WebTrader signup ToS/Privacy links, mode-neutral framing.
Not in Scope: Telegram onboarding flow changes (already polished in `onboarding-polish` lane); EmptyState audit; signup-time required-acknowledgment checkbox; jurisdiction-specific legal review; client-side legal modal.

## 1. What was built

Closed the public-launch legal gap on the WebTrader signup surface:

- New **Terms of Service** at `projects/polymarket/crusaderbot/legal/terms-of-service.md`. Mode-neutral — describes both paper and live modes, frames the bot as a "trading aid, not financial advice", explicit "no guarantee of profit" + responsible-use clause + standard liability / availability / governing-law sections. Last-updated 2026-05-28.
- **Privacy Policy** moved into the bot tree at `projects/polymarket/crusaderbot/legal/privacy-policy.md` (was repo-root `privacy-policy.md`). Single source of truth now lives with the bot it describes; the Docker build context already covers this path so the docs ship to Fly.
- New **legal router** at `projects/polymarket/crusaderbot/api/legal.py` (mounted in `main.py`). Serves both docs as HTML at `GET /legal/terms` and `GET /legal/privacy`. Minimal Markdown→HTML renderer (subset only: H1–H3, ordered/unordered lists, `[text](url)` links, `**bold**`, `_italic_`, inline code, paragraphs). All text is `html.escape`d first so untrusted content can't inject HTML even if the .md is edited externally. Anchor URLs are filtered to `http(s)://` or `/`-relative only. Pages set `<meta name="robots" content="noindex">` since this is operator-served legal content, not a marketing surface.
- Rate-limit middleware exempts `/legal/*` so an anonymous user reading the ToS before signup is never throttled.
- **AuthPage** (`webtrader/frontend/src/pages/AuthPage.tsx`) gains a footer line under the existing "Secure channel" indicator: "By continuing you agree to our **Terms of Service** and **Privacy Policy**. CrusaderBot is a trading aid, not financial advice — no profit is guaranteed." Both links open in new tabs (`target="_blank" rel="noopener noreferrer"`).

**Bundled urgent fix — `RATE_LIMIT_RPM` 120 → 600.** A live user on production hit `{"detail":"Too many requests. Please slow down..."}` on a normal WebTrader page load (screenshot via WARP🔹CMD). Root cause: `RateLimitMiddleware` was configured at 120 req/min = 2 req/s per source IP. A real WebTrader dashboard mount fires ~10–15 `/api/web/*` calls (markets, positions, portfolio summary, alerts, signals, scan history) and any quick navigation between routes adds another batch — 2 req/s tripped the ceiling within seconds. Raised default to 600 req/min (10 req/s) which still gives the limiter abuse-protection teeth while leaving 5× headroom over a normal page load. No test breakage — tests parameterise rpm rather than using the default. Tracked as a sub-line of Axis #4 because it is also a public-launch readiness blocker and ships in the same PR.

## 2. Current system architecture

```
WebTrader AuthPage (signup / login)
  ├── existing 2-tab flow (Telegram, Email)
  └── NEW footer: ToS + Privacy links + trading-aid disclaimer
        ↓ target="_blank"
        /legal/terms       ← api/legal.py reads legal/terms-of-service.md
        /legal/privacy     ← api/legal.py reads legal/privacy-policy.md
```

The two endpoints are the only public touchpoints for the legal docs. The
Telegram side is untouched in this lane — the existing MVP onboarding
already shows the operator's curated welcome flow and the legal surface
there is the Telegram T&C (out of scope per WARP🔹CMD).

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/legal/terms-of-service.md
- projects/polymarket/crusaderbot/api/legal.py
- projects/polymarket/crusaderbot/reports/forge/onboarding-ux.md

Moved (`git mv`, content preserved):
- privacy-policy.md → projects/polymarket/crusaderbot/legal/privacy-policy.md

Modified:
- projects/polymarket/crusaderbot/main.py — `api.legal` imported + router mounted alongside health/admin/ops.
- projects/polymarket/crusaderbot/api/rate_limit.py — `/legal/*` path-prefix exempted from the limiter.
- projects/polymarket/crusaderbot/config.py — `RATE_LIMIT_RPM` default 120 → 600 (urgent fix; see §1).
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AuthPage.tsx — ToS + Privacy footer added.
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- `legal/terms-of-service.md` → 5,923 bytes Markdown → 6,730 bytes HTML via the in-process renderer (smoke-tested locally with `_render_markdown`); starts with `<h1>`.
- `legal/privacy-policy.md` → 3,488 → 3,987; same shape.
- `api/legal.py` router exposes `GET /legal/{slug}` and returns 404 for unknown slugs / missing files.
- `tests/test_rate_limit.py` + `tests/test_health.py` (48 tests) still pass — middleware exempt-list change is non-breaking.
- AuthPage links open `/legal/terms` and `/legal/privacy` in new tabs.
- `py_compile` clean on all 3 modified Python files.

## 5. Known issues

- **No explicit acknowledgment gate.** The footer line ("By continuing you agree…") is implicit-consent rather than a required checkbox. Adequate for closed beta; revisit if a regulator or counsel requires hard-gating.
- **Single canonical jurisdiction.** Section 9 of the ToS refers to "the operator's primary jurisdiction" without naming it. Counsel review will pin this before public launch.
- **No legal-doc versioning surfaced to the user.** "Last updated" is in the doc header only; we do not store user-acknowledgment timestamps or force re-acceptance on a change. Tracked as a follow-up if/when material changes ship.
- The repo-root `privacy-policy.md` is gone; any external link to its repo path (e.g. an old README, an issue body) breaks. Replaced by the in-bot copy at `projects/polymarket/crusaderbot/legal/privacy-policy.md` which is the new canonical path.

## 6. What is next

- Axis #1 multi-tenant safety (MAJOR): per-user data isolation audit, RLS check, auth hardening, rate limits per user, abuse guards.
- Then Axis #3 live-trading activation flow (MAJOR), Axis #7 public-readiness audit.

## Suggested Next Step

WARP🔹CMD review + merge of this lane, then start Axis #1 `WARP/ROOT-multitenant-safety` (MAJOR — SENTINEL required on merge).
