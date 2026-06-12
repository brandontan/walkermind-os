# WARP•R00T Report — smart-strike-live-readiness-audit

Project: CrusaderBot
Project Root: projects/polymarket/crusaderbot
Branch: WARP/root-smart-strike-live-readiness
Branch note: the issue-declared name `WARP/smart-strike-live-readiness-audit` is occupied on the remote by a stale unmerged SENTINEL lane (old #1708-era base); force-push is forbidden, so this R00T lane uses the standard `WARP/root-*` slug instead — all artifacts use this exact head branch
Issue: #1797
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: R00T audit + scoped hardening complete — R00T final gate (self-merge on CI green)
Last Updated: 2026-06-13 03:50 Asia/Jakarta

## Objective

Audit and harden Smart Strike (candle presets → `late_entry_v3`) so it matches the intended strategy rules and is genuinely live-trade capable — proving it is NOT paper-only while preserving every live safety gate. Owner scope updates: per-user equity sizing only, market universe locked to BTC/ETH 5m/15m with SOL disabled by default, admin enable/disable controls for the universe.

## Audit Findings (code truth, three parallel deep audits)

### 1. Execution routing — NOT paper-only, fail-closed ✓

- Mode decision: `domain/risk/gate.py:701` — `chosen_mode = "live" if _passes_live_guards(ctx, settings) else "paper"`. `_passes_live_guards` (gate.py:336–348) requires ALL of: `ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED`, `SECURITY_HARDENING_VALIDATED`, `USE_REAL_CLOB`, `role == "admin"`, `trading_mode == "live"`. Any miss → paper.
- Defense-in-depth: `domain/execution/router.py:62–101` re-checks the global live gate + `live_engine.assert_live_guards` (live.py:60–90 raises `LivePreSubmitError` per missing flag BEFORE any network call); pre-submit failure falls back to paper with audit.
- The LIVE path is REAL: `live.py` fetches CLOB tick_size/neg_risk via `MarketDataClient`, computes an aggressive limit price, claims idempotency (`orders` insert `'live'/'pending'` ON CONFLICT DO NOTHING), then `client.post_order(token_id, side, price, size, order_type, tick_size, neg_risk)` — token id selected from `yes_token_id/no_token_id` by side (live.py:161), never from UI percentages.
- Post-submit ambiguity raises `LivePostSubmitError` and REFUSES paper fallback (operator reconciles; no silent duplicate).
- All 5 activation guards + `USE_REAL_CLOB` default FALSE in `config.py` — dev/test boots can never silently arm live.

**Verdict: Smart Strike can reach a real CLOB live order ONLY when every prerequisite passes; every missing flag/credential fails closed. No fail-open gap found.**

### 2. Sizing + per-user capital isolation — CLEAR PASS ✓

- Strategy suggestion (`late_entry_v3.py:570–592`): `equity × CAP% × 4%`, clamped to per-trade ceiling ($1–$500); equity/balance sourced from the per-user enrolled-users row.
- Gate step 13 (`gate.py:660–681`): `kelly = min(profile_kelly, KELLY_FRACTION)` with hard assert `0 < KELLY_FRACTION <= 0.25`; live mode sizes from `live_bal` (per-user preload or `get_live_balance(ctx.user_id)`); `final_size = min(proposed, sizing_balance × max_pos_pct × kelly)`.
- Gate step 15 (`gate.py:823–849`): `live_no_funds` when per-user live balance ≤ 0; `live_capital_cap_exceeded` past `min(manual_cap, spendable)`.
- `wallet/ledger.get_live_balance` bucket excludes paper rows, pending/confirming deposits, reserved orders, in-position capital (already debited), withdraw-pending. `$5` Auto-Trade start gate reads the same per-user bucket.
- Pool-leak search NEGATIVE: `master_wallet`/pool balances appear only in custody/admin surfaces — never in strategy, UserContext, TradeSignal, or gate sizing. Every balance subquery joins on `u.id`/`user_id`.
- CAP% (20/40/60 per profile) = % of THAT user's equity as deployable pool; one trade takes 4% of it — honored as user setting, no global silent override.

**Verdict: live sizing uses only the active user's confirmed available live balance; Kelly stays fractional (≤0.25); no cross-user/pool/paper leak.**

### 3. Strategy rules — verified against code truth ✓

- Entry: final-35s window (`ENTRY_WINDOW_SEC=35.0`), best-ask lean `MIN_ASK_DIFF=0.05`, combined-asks `MAX_SPREAD=1.05`, favored-price band `FAV_PRICE_MAX=0.70`; underdog (flip_hunter) flips to the cheap side; confidence = clamped ask-diff (late_entry_v3.py:59–66, 1085–1194).
- No-trade conditions enforced: not a short crypto market, blacklisted/no conditionId, closed/not-accepting, outside window, empty CLOB book, ask-diff/spread/price-band failures.
- Oracle edge hard-reject (`_oracle_edge_hard_rejects`) is fail-open by design when oracle is off/warming (current prod posture) and rejects only on a computed-false verdict — matches #1726 design.
- `candle_auto` Auto-routing = precedence router `close_sweep → safe_close → flip_hunter` deduped by market; EV-comparator `ORCHESTRATOR_ACTIVE=False` (shadow only). `_preset_allows` is deny-by-default and respects the global strategy toggle.
- Docs/code mismatch found: none material; flip-stop doc note (line 67) is config-read at evaluate_exit (line 798) — not paper-only.

### 4. Gaps found (the scoped fixes of this lane)

- **GAP-1 (owner truth violation): SOL was enabled by default.** `_DEFAULT_TRADEABLE_COINS = ("btc","eth","sol")` and SOL absent from monitor-only sets — a candle user with no asset selection scanned and could trade SOL.
- **GAP-2 (missing requirement): no admin market-universe controls.** Only a coarse global `late_entry_v3` on/off existed — no master Smart Strike switch, no per-pair (BTC/ETH/SOL), no per-timeframe (5m/15m) control, and no skip reason when a bucket was off.

## Fixes Implemented (scoped — no strategy rewrite)

1. **Six env defaults** (`config.py`): `SMART_STRIKE_ENABLED/BTC/ETH/5M/15M = True`, **`SMART_STRIKE_SOL_ENABLED = False`** (owner lock).
2. **Six admin runtime overlays** (`domain/ops/runtime_config.py` SettingSpec bools — auto-rendered in the Admin UI, no redeploy): master, BTC, ETH, SOL (default OFF), 5m, 15m.
3. **Single shared gate** `signal_scan_job._smart_strike_admin_universe(selected_timeframe, selected_assets) -> (allowed, skip_reason, effective_assets)` — resolves master → timeframe → per-pair flags (DB overlay over env default, fail-safe to owner-lock defaults if Settings unavailable). A None/empty user selection materializes the default universe BEFORE filtering so SOL cannot be resurrected by the downstream tradeable-coins default.
4. **Wired at both scan loops** (`run_once` + `run_close_sweep_fast`): blocked bucket → explicit structured skip (`smart_strike_admin_skip` with reason `smart_strike_admin_disabled` / `smart_strike_timeframe_disabled:<tf>` / `smart_strike_assets_disabled`) + telemetry zero-reason; dropped pairs logged (`smart_strike_pair_disabled`). The admin-filtered asset list drives BOTH the candle-window fetch and the strategy's own eligibility via a new `_build_user_context(..., assets_override=)` — so a disabled bucket produces no candidates and therefore no order intent, paper or live, regardless of Auto-Trade state.
5. Admin enablement bypasses nothing: the universe gate is scan-level only — user mode, Auto-Trade, $5 balance, measured-edge policy, kill switch, and the live guard set are enforced downstream unchanged (pinned by test).

## Market-Universe Statement (done criteria)

- **Eligible market family:** Polymarket short-duration crypto Up/Down candle markets, fetched by deterministic slug `{coin}-updown-{tf}-{unix_slot}` (Gamma `/events`) — politics/sports/long-duration markets are structurally unreachable (slug construction + `is_short_crypto_market` text check).
- **Enabled pairs (default):** BTC, ETH. **Disabled pair:** SOL (present in the product model; admin overlay `SMART_STRIKE_SOL_ENABLED` can enable it later — enabling never bypasses user/risk/live gates).
- **Enabled candle intervals (default):** 5m, 15m (each independently admin-disableable).
- **Admin gating behavior:** master/pair/timeframe OFF → bucket is skipped at scan with an explicit reason; no candidate, no QR of any kind, no order intent. Complete-set arb remains a separate strategy lane (own runtime flag), not mixed into Smart Strike routing.

## Files Changed

- projects/polymarket/crusaderbot/config.py (6 env defaults)
- projects/polymarket/crusaderbot/domain/ops/runtime_config.py (6 SettingSpec overlays)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py (universe gate helper + both loop wirings + `_build_user_context` assets_override)
- projects/polymarket/crusaderbot/tests/test_smart_strike_universe.py (new, 15 tests)
- state/PROJECT_STATE.md, state/WORKTODO.md, state/CHANGELOG.md

## Validation

- New: `test_smart_strike_universe.py` — 15 passed (defaults BTC/ETH-only + SOL off; master/pair/timeframe disable + skip reasons; SOL admin-enable; empty-selection no-SOL-resurrection; ctx override threading; both-loop wiring pins; live-guard/$5 untouched pin).
- Adjacent regression (`smart_strike or late_entry or signal_scan or runtime_config or candle or preset`): 103+379 passed.
- Full suite: **3547 passed, 11 skipped**. ruff + py_compile clean on touched files.
- Secret-pattern + UTF-8/mojibake/BOM scans clean. Branch verified from `git rev-parse`.
- No frontend touched (admin bool overlays auto-render in the existing Admin runtime-settings UI).

## Inviolable Invariants — confirmed clean

No real live order placed; no real fund movement; no flip of `USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` (or the other two activation guards); risk constants untouched (Kelly hard-capped 0.25); kill switch + $5 live Auto-Trade gate + measured-edge policy unchanged; no fake live abstractions — the audited live path is the real CLOB path, gated.

## What is next

- Owner-ops only for true live fire: flip the activation guards + `USE_REAL_CLOB` per the documented go-live sequence; the strategy side is proven ready.
- Optional follow-up lane: surface the SOL-disabled state in user-facing pickers (WebTrader/Telegram asset selection currently shows SOL; scanning is now admin-blocked regardless).

## Next Gate

WARP🔹CMD first-pass PR check → WARP•R00T final gate (this lane is R00T-assigned; R00T takes final gate responsibility, self-merge on CI green) — WARP•SENTINEL not run, not claimed.
