# WARP•R00T FORGE REPORT — hero-risk-tag-crash-fix

Branch: WARP/ROOT/hero-risk-tag-crash-fix
Date: 2026-05-30 00:49 Asia/Jakarta
Lane: production hotfix (owner-reported, SEV-1 — WebTrader HOME down)

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : WebTrader HOME (DashboardPage → HeroCard) never crashes on an unmapped risk_profile value
Not in Scope      : audit lanes 3b/4/5
Suggested Next    : WARP🔹CMD review (merge + deploy to restore HOME)

## 1. What was built
Hotfix for the owner-reported production crash on the deployed WebTrader HOME
screen: the ErrorBoundary fallback "SOMETHING BROKE ON THIS SCREEN — Cannot read
properties of undefined (reading 'bg')".

Root cause: `components/HeroCard.tsx` `RiskTag` did `const c = RISK_COLOR[risk]`,
where `RISK_COLOR` only maps `safe` / `balanced` / `aggressive`. `DashboardPage`
passes `data.risk_profile as RiskLevel` (a type cast). `custom` is a REAL risk
profile in this system (PROFILES["custom"] / VALID_RISK_PROFILES), so a user with
`risk_profile="custom"` AND `auto_trade_on=true` made `RISK_COLOR["custom"]`
undefined → `c.bg` threw → the entire HOME screen fell into the ErrorBoundary.
Pre-existing latent bug; surfaced in production for a custom-profile user.

Fix: `RiskTag` now falls back to `RISK_COLOR.balanced` for any unmapped risk and
`RISK_LABEL[risk] ?? String(risk).toUpperCase()` for the label — so an unknown
value (custom or anything else) renders as a neutral tag instead of crashing.

## 2. Current system architecture (relevant slice)
DashboardPage (HOME) → HeroCard → RiskTag (renders only when `risk` is truthy).
The two sibling `.bg` lookups (AlertCenter `CATEGORY_STYLE[cat]`,
NotificationPrefsCard `cat.bg`) iterate FIXED category lists, not raw user data,
so they cannot hit this class of crash — RiskTag was the sole data-keyed lookup.

## 3. Files created / modified (full repo-root paths)
Modified:
- projects/polymarket/crusaderbot/webtrader/frontend/src/components/HeroCard.tsx (RiskTag color + label fallback)
Created:
- projects/polymarket/crusaderbot/tests/test_hero_risk_tag_crash_fix.py (2 source-pin regression tests)

## 4. What is working
- tsc --noEmit clean; vite build clean.
- 2/2 source-pin tests pass.
- Logic: custom / any unmapped risk → balanced styling + uppercased label, no throw.

## 5. Known issues
- Frontend has no JS unit-test runner; regression is pinned via source inspection
  (matches repo convention). A future lane could add a vitest harness.
- Optional UX follow-up: give `custom` its own first-class tag color/label rather
  than reusing balanced.

## 6. What is next
- Merge + Fly CD deploy to restore the HOME screen.
- Resume audit lanes 3b / 4 / 5.

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
