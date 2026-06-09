# WARP•FORGE REPORT — pre-launch-polish

Validation Tier: MINOR
Claim Level: FOUNDATION
Validation Target: WebTrader DesktopSidebar brand header; migration 055 repo formalisation; state file sync
Not in Scope: Backend, trading logic, Telegram, live execution
Suggested Next Step: WARP🔹CMD review required. Source: projects/polymarket/crusaderbot/reports/forge/pre-launch-polish.md. Tier: MINOR.

---

## 1. What Was Built

Two-item pre-launch polish lane:

**A — DesktopSidebar brand header**
Added CrusaderBot logo + CRUSADERBOT title to the top of the desktop sidebar. Previously the sidebar had only a "Navigation" section label; now it has a branded top block matching the app's visual identity. Logo uses `import.meta.env.BASE_URL` prefix (same fix as TopBar + AuthPage), 32×21 px landscape ratio, gold drop-shadow. Brand text: `CRUSADER` + `BOT` (gold) + `TACTICAL · PAPER` subtitle.

**B — Migration 055 repo formalisation**
`migrations/055_scan_runs_rls.sql` — formalises the `ALTER TABLE scan_runs ENABLE ROW LEVEL SECURITY` that was applied directly to Supabase on 2026-05-26. Without this file the repo migration history was inconsistent with the live DB. Now 43/43 public tables are locked both in DB and in committed migration history.

---

## 2. Current System Architecture

WebTrader layout:
- TopBar (sticky, all screen sizes) — logo + nav pills + right cluster
- DesktopSidebar (md: and up, fixed left) — **now branded** at top + nav + system status card
- BottomNav (mobile only)
- AuthPage — logo centred above login card

All four logo placements now use `${import.meta.env.BASE_URL}crusaderbot-logo.png` with correct landscape dimensions.

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| Modified | `projects/polymarket/crusaderbot/webtrader/frontend/src/components/DesktopSidebar.tsx` |
| Created | `projects/polymarket/crusaderbot/migrations/055_scan_runs_rls.sql` |
| Updated | `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` |
| Updated | `projects/polymarket/crusaderbot/state/CHANGELOG.md` |

---

## 4. What Is Working

- DesktopSidebar: logo renders from `/dashboard/crusaderbot-logo.png` (correct Vite base path); brand block appears above the Navigation section on md: and above viewports.
- Migration 055: idempotent single statement; safe to apply to a fresh DB that doesn't have it yet (Supabase already has it applied).
- State files: PROJECT_STATE Status updated, [IN PROGRESS] updated, [NEXT PRIORITY] rewritten to reflect completed lanes and remaining priorities.

---

## 5. Known Issues

- None introduced by this lane.
- Fly.io deploy of the sidebar change requires `fly deploy --remote-only` from WARP🔹CMD's machine (fly CLI not available in cloud execution environment).

---

## 6. What Is Next

- WARP🔹CMD: deploy to Fly.io to surface sidebar brand change.
- WARP🔹CMD: `fly secrets set HEISENBERG_API_TOKEN=<token> -a crusaderbot` — all Heisenberg code is already shipped; token is the only gate.
- Gate 3 + Gate 5: observation only (no code).
