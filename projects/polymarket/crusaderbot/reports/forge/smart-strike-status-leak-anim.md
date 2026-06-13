# WARP•R00T — smart-strike-status-leak-anim (reopened #1807)

Branch: `WARP/root-smart-strike-status-leak-anim`
Issue: #1807 (reopened)
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Role: WARP•R00T hotfix/finishing (frontend presentation only)
Date: 2026-06-13 08:05 Asia/Jakarta

Validation Target: WebTrader ScannerPanel Smart Strike status — guarantee no raw backend reason can reach normal user copy on any render path, and make the idle scanning animation clearly visible in the actual production surface.

Not in Scope: strategy rules, scan eligibility, signal generation, order intent, risk/Kelly, live guards, deposits/withdrawals.

---

## 1. Finding / honest root-cause

The owner reopened #1807 after the #1809 deploy with a live screenshot still showing
`status awaiting_signal · late_entry_v3: filter_or_no_match` and no clearly visible idle animation.

Code-truth audit (code wins over the screenshot):

- The merged #1809 status row already routes `runtime.smart_strike_no_trade_reason` through `formatNoTradeReason()` and renders `Waiting for a valid signal — <friendly detail>`. The backend builds the reason as `f"{strategy}:{reason}"` = `late_entry_v3:filter_or_no_match` (no space — `services/signal_scan/signal_scan_job.py` `record_zero_reason`), which #1809 already maps to `No matching signal yet`.
- The `awaiting_signal · ` prefix + raw reason in the screenshot is the **pre-#1809 rendering** (the old status line literally prepended `awaiting_signal · ` and trimmed only `skipped_`). The owner's screenshot is the previously-deployed build (deploy lag), not the merged code.
- `ScannerPanel` is the ONLY user-facing surface that renders the reason (grep of `webtrader/frontend/src`); `AutoTradePage` does not render it.

So there was no remaining code path leaking the raw reason in the merged tree. This pass HARDENS the formatter against every transcription/concatenation variant so a leak is provably impossible, and makes the idle animation unmistakable (the real actionable gap).

## 2. What changed

`webtrader/frontend/src/components/ScannerPanel.tsx`:

1. `formatNoTradeReason()` hardened:
   - trims surrounding whitespace and tolerates a space after the colon, so `late_entry_v3: filter_or_no_match` resolves to the `filter_or_no_match` suffix category (`No matching signal yet`) instead of the prefix category;
   - defensively strips a leading `awaiting_signal` + separator (`· : -`), so even the exact full screenshot string `awaiting_signal · late_entry_v3: filter_or_no_match` maps to `No matching signal yet`;
   - composite reasons prefer the suffix category, then the prefix; unknown reasons fall back to `Still scanning for a valid signal`. The function can NEVER return a raw snake_case/code token.
2. Idle scanning animation made clearly visible (was a 3px subtle trailing only):
   - `ScanDots` upgraded to 4–5px gold dots with a soft glow + staggered fade (`size` prop);
   - a dedicated, clearly-visible `scanning markets` line with larger dots is added to the active status block, rendered only while running with no signal/order;
   - the always-visible signals-footer placeholder now reads `Scanning live markets` + animated dots (replacing the old raw-ish `awaiting signal — scanning live markets…`);
   - `BASE_COUNT` bumped 6 -> 7 so the new scanning line is revealed by the stagger.

`tests/test_smart_strike_no_trade_reason.py`:

- Added a faithful Python port of the formatter (no JS test runner exists in the repo) exercised against the EXACT screenshot string + the no-space and space variants + every CMD-listed raw code, asserting friendly output and that no output ever contains `late_entry_v3` / `filter_or_no_match` / `skipped_` / `step_14_` / etc.
- Added source pins: formatter implements the trim + `awaiting_signal` strip + suffix-preferred composite mapping; the idle animation is wired in the actual surface (`scanning markets` line, `ScanDots size={5}`, status trailing dots, friendly footer copy, old placeholder removed).

## 3. Files modified

- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/ScannerPanel.tsx`
- `projects/polymarket/crusaderbot/tests/test_smart_strike_no_trade_reason.py`
- `projects/polymarket/crusaderbot/reports/forge/smart-strike-status-leak-anim.md` (this report)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md`

(`index.css` already carries `@keyframes scanDot` / `.animate-scan-dot` from #1809 — unchanged.)

## 4. What is working / validation

- `pytest test_smart_strike_no_trade_reason.py` -> 35 passed (incl. the exact-screenshot mapping + leak-guard parametrization + visible-animation source pins).
- `npm run build` (`tsc && vite build`) green; only the pre-existing PortfolioPage dynamic/static import warning.
- Playwright render of the built CSS + scanning markup: confirmed `Waiting for a valid signal — No matching signal yet` with clearly visible glowing animated dots and a dedicated `scanning markets •••` line (temporary harness removed after capture).
- Full suite: `pytest projects/polymarket/crusaderbot/tests/` -> 3637 passed, 15 skipped.
- `ruff` + `py_compile` clean; secret / mojibake / BOM scans clean.

## 5. Safety invariant statement

Frontend presentation only. No change to `summarize_no_trade_reason()`, `RuntimeStatus`, `/status` payload, scan telemetry, strategy/eligibility/late-entry rules, risk model, Kelly (0.25), order intent, CLOB execution, balances, deposits, withdrawals, or activation flags (`USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, `CAPITAL_MODE_CONFIRMED` untouched). No order placed, no funds moved, no live-guard flipped. Raw backend reason remains available to debug/admin/log via the unchanged `smart_strike_no_trade_reason` field — only user-facing copy is sanitized.

## 6. What is next

WARP🔹CMD first-pass; merge under WARP•R00T final gate on CI green (STANDARD UI-only; WARP•SENTINEL not required). A Fly redeploy is required for the owner's production surface to pick up the merged build.

---

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: ScannerPanel no-trade status copy + visible idle animation.
Not in Scope: strategy/risk/execution/capital/deposit logic, live-guard flags.
Suggested Next Step: WARP🔹CMD first-pass -> R00T final-gate merge on CI green -> Fly redeploy.
