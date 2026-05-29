# WARP•SENTINEL VALIDATION — silent-broken-features (Lane 2/5)

Validated by: WARP•R00T acting as WARP•SENTINEL (owner-directed post-merge gate)
Date: 2026-05-30 00:16 Asia/Jakarta
Source: projects/polymarket/crusaderbot/reports/forge/silent-broken-features.md

## Environment
- Validation surface: merged `main` @ b8692b8 (#1454), code-as-truth.
- env: dev (hermetic) — risk rules ENFORCED in code review.

## Validation Context
- Validation Tier: MAJOR (copy-trade execution path touches the risk gate).
- Claim Level: NARROW INTEGRATION.
- Target: copy-trade monitor produces a gate-valid signal; withdrawal outcome
  notifications reach users; critical WebTrader fetches surface errors instead
  of empty/spinner.

## Phase 0 Checks
- Forge report present at correct path — PASS.
- PROJECT_STATE updated (MERGED #1454) — PASS.
- No `phase*/` folders — PASS.
- Risk constants unchanged (KELLY_FRACTION=0.25, MAX_POSITION_PCT=0.10,
  MAX_DRAWDOWN_HALT=0.08, MIN_LIQUIDITY=10_000) — PASS.

## Findings (code-as-truth, file:line)
- F1 PASS — `services/copy_trade/monitor.py:318` builds
  `signal_ts=datetime.now(timezone.utc)` (tz-aware); `from datetime import date,
  datetime, timezone` at :37. The prior naive `datetime.utcnow()` that raised
  `TypeError` at gate step 9 (`domain/risk/gate.py:342`,
  `now = datetime.now(timezone.utc); age = (now - ctx.signal_ts)`) is gone. The
  engine passes `signal_ts` straight through (`services/trade_engine/engine.py`),
  so the gate now evaluates copy-trade candidates instead of crashing-and-caught.
- F2 PASS — `notifications.py:164` `notify_user_by_telegram_id(telegram_user_id,
  text, parse_mode=ParseMode.HTML)` forwards `parse_mode` to `send()`. The two
  withdrawal calls in `bot/handlers/admin.py` (approve/reject) that pass
  `parse_mode=ParseMode.MARKDOWN_V2` no longer raise `TypeError`; their
  MarkdownV2-escaped messages render. No silent failure: `send()` logs ERROR on
  permanent failure and returns bool.
- F3 PASS — WebTrader error-vs-empty: `SettingsPage` `load()` is try/caught with
  a `loadError` + Retry branch (no infinite spinner); `PortfolioPage`
  AnalyticsPanel separates fetch-error (Retry) from genuinely-empty;
  `DashboardPage` secondary loaders `console.warn` instead of fully silent.

## Score Breakdown
- Architecture 20/20 — single tz-aware source of truth; no new abstractions.
- Functional 20/20 — copy-trade gate path + notify forwarding verified by tests.
- Failure modes 18/20 — silent-failure dead-paths removed; FE surfaces errors.
  (-2: copy-trade end-to-end mirror still gated on the separate roadmap table
  swap — out of this lane's scope, pre-existing.)
- Risk 20/20 — gate logic, activation guards, Kelly all untouched.
- Infra+TG 10/10 — notify path hardened; no infra change.
- Latency 10/10 — no latency-sensitive path altered.
- TOTAL: 98/100.

## Critical Issues
None found.

## Status
APPROVED.

## PR Gate Result
Already MERGED #1454 + deployed to Fly via CD; this is the owner-directed
post-merge SENTINEL confirmation. No re-merge action required.

## Reasoning
The two backend bugs were real silent dead-paths; the fixes are minimal, correct,
and pinned by 4 hermetic tests. 269/269 tests pass across the lane + regression
neighborhood (copy_trade, trade_notifications, notification_prefs). No safety
surface touched.

## Fix Recommendations
None blocking. Carry-forward (pre-existing, tracked): copy-trade end-to-end
mirror table swap.

## Out-of-scope Advisory
FE error states are functional (text + Retry), not a designed error component.

## Deferred Minor Backlog
- [DEFERRED] jobs/daily_pnl_summary.py naive utcnow in a zoneinfo-fallback date
  label (LOW, produces a correct UTC date string) — found in api fix campaign.

## Telegram Visual Preview
Withdrawal approve → user DM: "✅ Your withdrawal of `$X` USDC has been approved.
_(Paper mode — no on-chain transfer yet)_" (MarkdownV2, now delivered).
