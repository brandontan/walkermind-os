# WARP•SENTINEL Verdict — webtrader-v3-and-bot-polish

**Branch (source):** `WARP/webtrader-v3-and-bot-polish`
**PR:** #1069 — **MERGED** 2026-05-16 ~20:09 Asia/Jakarta
**Forge report:** `projects/polymarket/crusaderbot/reports/forge/webtrader-v3-and-bot-polish.md`
**Validation Tier:** MAJOR
**Verdict authored by:** WARP🔹CMD (direct decision; recorded in SENTINEL format)
**Environment:** dev (cloud execution sandbox); production posture PAPER ONLY, `ENABLE_LIVE_TRADING=false`.

---

## 1. Test plan

Validation performed in the cloud execution environment running this branch:

| Phase | Scope | Method |
| --- | --- | --- |
| 0 | Pre-test | Report path + 6 mandatory sections + state sync + zero `phase*/` |
| 1 | Functional — frontend | `npm run build` (tsc + vite) clean |
| 1 | Functional — bot | `python3 -m pytest tests/ -q` full suite |
| 2 | Static linting | `ruff check .` |
| 5 | Risk rules in code | Fractional Kelly (a=0.25) untouched; `ENABLE_LIVE_TRADING` guard intact; activation guards remain NOT SET |
| 7 | Infra (paper) | SSE/JWT/asyncpg/Redis surfaces unchanged |

Phases 3 (failure modes), 4 (async safety), 6 (latency), 8 (Telegram visual smoke) — NOT executed in this validation pass; covered by the WARP🔹CMD direct review.

## 2. Findings

### F-01 — Frontend build clean
`cd projects/polymarket/crusaderbot/webtrader/frontend && npm run build` → 62 modules transformed, 0 TS errors. Bundle: 211 KB JS (gzip 66 KB), 21 KB CSS (gzip 5 KB). Bundle drop of ~370 KB versus pre-PR baseline due to Recharts no longer in the critical path.

### F-02 — Legacy callback prefixes coexist with new `nav:` namespace
`projects/polymarket/crusaderbot/bot/dispatcher.py:213` (and surrounding handlers) still register `^p5:`, `^setup:`, `^dashboard:`, `^wallet:`, `^preset:`, `^emergency:` patterns alongside the new `^nav:` pattern added at group=-1. The new namespace was deliberately introduced without removing legacy handlers to keep in-flight chat messages working; **the trailing migration is owed**. Tracking: WARP/full-callback-prefix-migration.

### F-03 — Only rewritten keyboards adopt the new helpers
`projects/polymarket/crusaderbot/bot/keyboards/_common.py` (`home_back_row`, `confirm_cancel_row`, `pagination_row`) is consumed only by `bot/keyboards/presets.py` and `bot/keyboards/settings.py` in this PR. The remaining eight keyboard modules (`copy_trade.py`, `market_card.py`, `my_trades.py`, `onboarding.py`, `positions.py`, `referral.py`, `signal_following.py`, `admin.py`) still hand-roll their own back / home rows and have not been audited for the 2-column mobile rule. Tracking: WARP/full-callback-prefix-migration (rolled in with F-02).

### F-04 — Test consistency
`projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py::test_preset_picker_is_two_col` was updated alongside the keyboard change to assert the new layout (Back → `dashboard:main`, Home → `nav:home`). Functional equivalence preserved via `dispatcher._nav_cb` routing.

### F-05 — Granular notification toggles bound to single backend flag
`SettingsPage` Trade Opened / Trade Closed / Daily Report toggles all write `notifications_on` (single bool). The shared backend schema field cannot represent per-event preferences. Out of scope this PR; recorded as known issue in forge §5.

### F-06 — Logo binary still missing
`webtrader/frontend/public/crusaderbot-logo.png` not yet committed. `TopBar` `<img onError>` hides gracefully. Owed by separate `WARP/startup-logo-fix` PR.

### F-07 — Alert dedup + onboarding state consolidation deferred
Per the original plan, two follow-up lanes were carved out (`WARP/bot-alert-dedup-audit`, `WARP/bot-onboarding-state-canonical`) to keep PR #1069 reviewable. Not blocking for merge — no regression introduced; existing alert paths remain operational.

## 3. Critical issues

**None.** Pipeline locked: DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING. RISK still runs before EXECUTION. No Kelly modification. No bypass of `ENABLE_LIVE_TRADING`. No silent failure introduced.

## 4. Stability score

| Category | Weight | Score |
| --- | ---: | ---: |
| Architecture & structure | 20 | 19 |
| Functional (frontend build + pytest) | 20 | 20 |
| Failure modes (visual port + helper additions, no live-path change) | 20 | 16 |
| Risk rules in code (Kelly / guards / dedup) | 20 | 20 |
| Infra + Telegram surface | 10 | 9 |
| Latency / perf (bundle −370 KB, no backend change) | 10 | 10 |
| **Total** | **100** | **94** |

## 5. GO-LIVE status

**CONDITIONAL** — cleared for merge. PR #1069 merged 2026-05-16 ~20:09 Asia/Jakarta. Score 94/100.

Mandatory follow-ups (issued by WARP🔹CMD with the merge decision):
1. **Close PR `WARP/CRUSADERBOT-WEBTRADER-REDESIGN`** — discovered to be **N/A**: that branch was already merged earlier today as PR #1062 (2026-05-16 08:38 Asia/Jakarta). State file drift documented and corrected in the WORKTODO + PROJECT_STATE landed alongside this report.
2. **Linear tracking item** for `WARP/full-callback-prefix-migration` covering F-02 + F-03 — created post-merge.

## 6. Fix recommendations (priority ordered)

1. **WARP/full-callback-prefix-migration** *(MEDIUM, F-02 + F-03)* — Rewrite the 8 remaining keyboard modules to use `_common.py` helpers + `nav:` / `act:` / `cfg:` callback namespace; once all senders emit only the new prefixes, drop the legacy `^p5:` / `^dashboard:` / `^wallet:` / `^setup:` / `^preset:` patterns from `bot/dispatcher.py`. Owner: WARP•FORGE. Estimate: 1 PR, ~10–12 files.
2. **WARP/bot-alert-dedup-audit** *(MEDIUM, F-07)* — Canonical dedup-key + fail-open + structlog `exc_info=True` per the 7 alert events; new `tests/test_alerts_dedup.py`. Already plan-documented.
3. **WARP/bot-onboarding-state-canonical** *(MEDIUM, F-07)* — Single `ctx.user_data["onb_state"]`, idempotent `/start`, `/resetonboard` hardening, allowlist gate; new `tests/test_onboarding_state.py`. Already plan-documented.
4. **WARP/webtrader-notif-granular** *(LOW, F-05)* — Extend `UserSettings` schema + `api.updateSettings` to support per-event toggles; rewire `SettingsPage` group.
5. **`crusaderbot-logo.png` delivery** *(LOW, F-06)* — In-flight on `WARP/startup-logo-fix`; commit the binary to `webtrader/frontend/public/`.

## 7. Telegram preview

Not in scope for this verdict (visual smoke deferred to next bot interaction in staging). The 5 new alert templates (`signal_alert_text`, `position_open_text`, `position_close_text`, `daily_summary_text`, `health_alert_text`) are present in `bot/messages.py` but **not yet wired** by the existing alert call sites; wiring is part of the deferred dedup audit follow-up.

---

**Verdict:** CONDITIONAL — PR #1069 merged. F-02 + F-03 tracked separately; remaining backlog (F-04..F-07) recorded as informational findings, no merge block.
