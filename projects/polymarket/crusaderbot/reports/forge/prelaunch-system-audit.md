# WARP•R00T — Pre-Public-Launch Full System Check (CrusaderBot)

Role: WARP•R00T (principal system auditor / hardening authority)
Branch: WARP/ROOT/prelaunch-system-audit
Date: 2026-05-31 Asia/Jakarta
Project: projects/polymarket/crusaderbot
Env: staging audit + prod config READ-ONLY validation (zero prod mutation)
Validation Tier: MINOR (read-only audit — no production code modified)
Claim Level: FOUNDATION
Validation Target: full-system pre-launch safety + data-integrity audit across Backend / WebTrader frontend / Telegram bot
Not in Scope: implementing Part 2 / Sprint 1–4 directive logic (HARD FENCE — new execution logic must follow the directive build+validate track, never hot-implemented before launch)

---

## 0. TWO VERDICTS (headline)

**(1) PAPER PUBLIC LAUNCH: GO (conditional).**
P0 = 0 on all paper surfaces. Execution open+close paths for all 3 canonical strategies + copy-trade are sound and risk-gate-coupled. Zero fabricated/cosmetic data on any surface. Admin/user boundary is enforced server-side. Kill switch + force-close work and are never gated by halt. The single qualifier on a *strict* "parity verified" claim is the set of P1 cross-surface **display-parity divergences** (equity / P&L-window / unrealized-mark are re-derived differently on web vs telebot). These are derived-analytics divergences — balance, mode, and positions are shared-source and consistent — and carry no capital-safety risk in paper. Recommend GO with the P1 parity reconciliation on the immediate post-launch fix list.

**(2) LIVE FLIP-READINESS: NOT-READY.**
Exact blocking gaps (live path only — none affect paper):
- **B1 — Bankroll circuit breaker is dark-launch-OFF** (`BANKROLL_CIRCUIT_BREAKER_ENABLED=False`, config.py:405). By the task's own criterion (circuit breaker not active ⇒ uncapped-drawdown exposure ⇒ NOT-READY). Mitigated-but-not-replaced by the always-on 8% drawdown halt (gate step 6). Per HARD FENCE: enable + validate via the directive track (unit → 7d paper → 7d live-25% → live-100%); do NOT hot-enable now.
- **B2 — BNB monitor-only bypass** (default-asset fallback reintroduces BNB into the trade path). Paper-contained today; routes real BNB orders the instant guards flip. Must close before LIVE.
- **B3 (confirm) — Sizing caps diverge from the ~2%/~50% spec** (`MAX_SINGLE_POSITION_PCT=0.10`, `MAX_TOTAL_EXPOSURE_PCT=0.80`). Owner must confirm intended (Kelly reduces effective per-trade to ~2.5% aggressive, but the absolute single-position cap is 10%).
- **B4 (harden) — `_preset_allows` fail-open default** + one live prod row sitting on it (see F2). Deny-by-default before LIVE.

LIVE machinery itself is well-built: 8 guard conditions, both guard layers enforced at the execution gate (not cosmetic), flip needs no redeploy, mode-switch is state-safe + reversible, kill switch active in LIVE.

---

## 1. P0 / P1 / P2 COUNTS PER SURFACE

| Surface | P0 | P1 | P2 |
|---|---|---|---|
| Backend (domain/services/integrations/api/webtrader-backend) | 0 | 6 | 8 |
| WebTrader frontend | 0 | 0* | 4 |
| Telegram bot | 0 | 0* | 4 |
| Cross-surface (web↔telebot parity) | 0 | 3 | 2 |
| Docs / state drift | 0 | 0 | 2 |
| **TOTAL** | **0** | **9** | **20** |

\* The frontend/telebot have no standalone P1s; the 3 parity P1s are counted once under Cross-surface (they manifest on both surfaces).

---

## 2. MECHANICAL P0 SCAN — ALL CLEAN

Repo-wide grep battery (excluding tests). Every one of the CLAUDE.md / task P0 patterns came back clean:

| Pattern | Result |
|---|---|
| Full Kelly (`a=1.0` / `kelly_fraction=1.0`) | NONE. `KELLY_FRACTION=0.25` (domain/risk/constants.py:4); gate clamps `min(profile_kelly, 0.25)` + hard invariant `0 < v <= 0.25` (gate.py:388-393) |
| `import threading` / ThreadPool / multiprocessing | NONE (asyncio only) |
| bare `except:` / `except: pass` in runtime | NONE (only a docstring mention in exit_watcher.py) |
| `phase*/` folders | NONE |
| Hardcoded secrets / API keys / private-key literals | NONE |
| Frontend `Math.random` in metrics | NONE |
| mock/dummy/fake/sample/placeholder fake-data on surfaces | NONE (all hits are HTML `placeholder=` props or comments) |
| `NotImplementedError` / stubs in runtime | NONE |

Activation guards + key flags (config.py), confirmed defaults:
`ENABLE_LIVE_TRADING=False` (202), `EXECUTION_PATH_VALIDATED=False` (203), `CAPITAL_MODE_CONFIRMED=False` (204), `RISK_CONTROLS_VALIDATED=False` (209), `SECURITY_HARDENING_VALIDATED=False` (210), `USE_REAL_CLOB=False` (155), `SWEEP_ONCHAIN_ENABLED=False` (189). `AUTO_REDEEM_ENABLED=True` (226). All 4 directive dark-launch knobs `=False` (CB 405, dynamic-sizing 354, safe-close-override 451, flip-hunter-topup 481, close-sweep-dual-leg 513).

---

## 3. ACTIVE-STRATEGY MATRIX (per strategy + copy-trade)

Preset roster of record = exactly 3, all routing to `late_entry_v3` (domain/preset/presets.py:101-162): **close_sweep / safe_close / flip_hunter**. Legacy multi-strategy presets (whale_mirror, signal_sniper, hybrid, value_hunter, full_auto) were already removed in WARP/R00T/strategy-system-cleanup. `VISIBLE_PRESET_ORDER` = the 3 canonical only.

| Strategy | Enabled / Mode | OPEN path | CLOSE: TP/SL | force-close | hold-to-resolve | auto-redeem | Risk-gate | Error-isolation | Idempotency |
|---|---|---|---|---|---|---|---|---|---|
| **late_entry_v3** (close_sweep/safe_close/flip_hunter) | PASS / PAPER (live guards off) | PASS — scan→`_process_candidate`→`_engine.execute` (signal_scan_job.py:2498,2826,2216) | PASS — exit_watcher on applied tp/sl snapshot (exit_watcher.py:416,429) | PASS — `force_close_intent` top priority (exit_watcher.py:380,717) | PASS — holds to candle resolution | PASS — winners→redeem_queue (redeem_router.py:195,281) | PASS — gate mandatory in engine before router (engine.py:142→173) | PASS — per-user + per-candidate try/except+continue (signal_scan_job.py:2438,2531) | PASS — paper ON CONFLICT (paper.py:44) + gate step 10 dedup (gate.py:352) |
| **copy_trade** | CONDITIONAL (copy_trade_tasks + admin toggle) / PAPER | PASS — monitor→`_engine.execute` (monitor.py:348) | PASS (DEFAULT 25/10, copy_trade.py:41) | PASS (same chain) | PASS — follows leader exit (copy_trade.py:195) | PASS (same redeem) | PASS — gate mandatory (monitor.py:348) | PASS — per-wallet/task isolation + kill-switch gate (monitor.py:97,115) | PASS — copy_trade_idempotency pre-check (copy_trade.py:383) |
| **signal_following** | RUNTIME-DEAD (gated off) / would-be PAPER | N/A — `_preset_allows` denies for all candle presets; lib fallback set is EMPTY (lib_strategy_runner.py:38-39) | PASS-if-open (preset-agnostic exit) | PASS-if-open | PASS-if-open | PASS-if-open | PASS (no bypass) | PASS — scan returns [] on error (signal_following.py:82) | PASS — execution_queue UNIQUE(user,publication) |

CLOSE-path independence (the worst-defect class) — VERIFIED SAFE: exit_watcher reads **no** kill-switch / `auto_trade_on` / admin-toggle anywhere; exits + force-close run regardless of halt or strategy-toggle state. Manual close on BOTH surfaces uses the identical **force-close marker flow** (sets `positions.force_close_intent=TRUE`, reconciled by the always-on watcher): web `close_position_endpoint` (router.py:585) + `/emergency`→`mark_force_close_intent_for_user` (router.py:1588); telebot `force_close_confirm` (positions.py) + `/emergency` (emergency.py:171,194). A toggled-OFF strategy / STOP-AUTO-TRADE / kill switch halts NEW entries only — never strands an open position.

---

## 4. CRITICAL-SAFETY GATE MATRIX

| Gate | Status | Reference | Flag state | LIVE implication |
|---|---|---|---|---|
| Complete-set edge gate (skip if `1−(ask_UP+ask_DOWN) < 0.5%`; never `<0`) | **IMPLEMENTED** | enforce signal_scan_job.py:2010-2065; const `MIN_COMPLETE_SET_EDGE` config.py:551 | always-on for stamped late_entry_v3 candidates | PRESENT-AND-ON → guaranteed-loss entry blocked |
| TOB staleness (skip if quote age > 2000ms) | **IMPLEMENTED** | signal_scan_job.py:1952-1991; `TOB_STALE_MS=2000` config.py:567 | always-on (stamped) | OK |
| Bankroll circuit breaker (~20% loss halt, ~110% hysteresis resume) | **IMPLEMENTED** | latch signal_scan_job.py:325-372; call 1605-1684; thresholds config.py:405-415 | **DARK-LAUNCH-OFF** (config.py:405) | **PRESENT-BUT-OFF → LIVE NOT-READY** |
| Dual-leg inventory tracking + imbalance | **PARTIAL (foundation-only)** | domain/strategy/inventory.py; consumer signal_scan_job.py:738 | consumers dark-launch-OFF | not LIVE-blocking alone |
| Sizing caps (max_order_fraction ~2%, max_total_exposure ~50%) | **IMPLEMENTED, DIVERGES** | config.py:217 `MAX_SINGLE_POSITION_PCT=0.10`; 218 `MAX_TOTAL_EXPOSURE_PCT=0.80` | always-on | P1 — looser than spec (F7) |

Core risk gate (domain/risk/gate.py) — **16 steps (0–15), always-on, fail-closed.** Docstring says "13-step" (doc drift, F12). Every failure branch returns `GateResult(approved=False)`; the only `raise` is the Kelly safe-range invariant (fail-closed crash = no order). Steps: balance>0 (194), single-pos cap (202), total-exposure cap (213), daily-loss floor (219), open-count (229), kill-switch (255), pause/auto-off (269), live-role admin (278), strategy-availability (284), daily-loss-hard-stop −$2000 (305), drawdown 8% (314), concurrent (325), correlated-exposure 40% (333), signal-staleness (343), dedup 300s (352), liquidity-floor $10k (363), edge-floor 200bps (373), Kelly+size+market-status (382), slippage/impact 5% (415), per-user LIVE capital cap (433).

**No order path skips the gate** — all 4 NEW-order entrypoints are gate-first: main scan (signal_scan_job.py:2216), fast top-up (1040, still routes engine), copy-trade monitor (monitor.py:348), legacy scheduler (scheduler.py:534, only proceeds if `result.approved`). WebTrader has **no manual-buy endpoint** (all trade endpoints are config/toggle or read). Kill switch (3 paths: telegram /kill, DB `system_settings.kill_switch_active`, env `KILL_SWITCH`) halts every NEW order via gate step 1, fail-safe TRUE on DB error.

---

## 5. RBAC + ADMIN/USER BOUNDARY

Access control reconciles to RBAC (`users.role` ∈ {admin, user}) on every **enforced** surface. No tier model is load-bearing.

- WebTrader admin endpoints all gate on `_require_admin` (role re-read from DB per request, not trusted from JWT) — router.py:2354-2363; `/admin/overview` (2369), `/admin/users` (2476), `/admin/strategies` (2522), `/admin/strategies/toggle` (2540), `/admin/users/{id}` GET (2584) + PATCH (2799). Admin PATCH still enforces the same physical bounds as user endpoints (2572-2581) — admin cannot bypass the system fence. **No user→admin leak.**
- Telegram operator commands all gated by `_is_operator` / `_is_admin_user` with silent reject (admin.py:96,1067,1090,1104,1118,1195,1241,876; operator_panel.py:159). No operator command reachable by a normal user.
- `services/allowlist.py` (integer-tier module) is **DEAD** — zero runtime importers; its self-describing "imported by…" comment (line 58) is false → **P1 cleanup (F9)**. The wired tier module `services/tiers.py` is a FREE/PREMIUM/ADMIN string helper whose own docstring states runtime gating uses `users.role`; `get_user_tier()==ADMIN` is an admin-equivalence check that reconciles to RBAC (P2 consolidation, F13).
- Frontend `/admin` route is guarded on auth only, not `is_admin` (App.tsx:498-499) with a soft client check (AdminPage.tsx:34) — **P2 only** (backend `_require_admin` is authoritative; bypass hits 403). Residual "Tier" strings (main.py:203 audit-note text; StatCard.tsx:10 JSDoc; AutoTradePage.tsx:70 comment) are inert P2.

## 6. TRADEABLE-ASSET ENFORCEMENT

Tradeable allowlist `_CRYPTO_SHORT_ASSETS=("BTC","ETH","SOL")` (router.py:832); monitor-only `_MONITOR_ONLY_ASSETS=frozenset({"BNB"})` + `_filter_monitor_only_assets` (signal_scan_job.py:137-180) applied server-side at scan time (1324, 2454, 2804). Frontend offers BTC/ETH/SOL only (AutoTradePage.tsx:66, AdminUserDrawer.tsx:21). Persistence rejects non-allowlist assets server-side (preset activation `_sanitize_selected_assets` router.py:937; admin PATCH hard-400 router.py:2783) — not UI-only.

- **XRP / DOGE / HYPE → provably NON-tradeable** (rejected at persistence AND absent from the scanner default coin list).
- **BNB → REACHES the trade path (P1, F3).** Bypass chain: empty/BNB-only `selected_assets` (filter strips BNB→empty) → `late_entry_v3.scan` sets `assets=None` (late_entry_v3.py:202) → `get_crypto_window_markets(tf, None)` defaults to `["btc","eth","sol","bnb"]` and fetches BNB candles (integrations/polymarket.py:220) → upsert makes them resolvable (signal_scan_job.py:616, no asset filter) → eligibility `market_matches_assets(m, None)` matches full whitelist incl BNB (eligibility.py:70,87) → candidate → gate (no asset-identity check) → execution. Paper-only now; routes real BNB on guard-flip. Fix: drop BNB from the `get_crypto_window_markets` default list and/or apply `_MONITOR_ONLY_ASSETS` to fetched markets / the `assets=None` eligibility path.

## 7. LIVE FLIP-READINESS MATRIX (prove safe; do NOT enable)

| Element | Status | Reference |
|---|---|---|
| 8 guard conditions (5 flags + USE_REAL_CLOB + role==admin + mode==live) | all default False / enforced at execution (NOT cosmetic) | live.py:51-81; gate.py:166-179; router.py:36 |
| `assert_live_guards` called BEFORE live engine | YES | router.py:36 precedes live_engine.execute (56) |
| GUARD_BYPASS_ATTEMPT logged CRITICAL + paper-fallback | YES | router.py:40,50-54,78-100 |
| paper/live mutually exclusive; post-submit error does NOT paper-duplicate | YES (no order bleed) | router.py:65-77,127-133 |
| both guard layers enforced at execution | YES — Layer A system (gate.py:403-412), Layer B per-user `live_capital_cap_usdc>0` (gate.py:433-449) | gate.py |
| flip needs redeploy? | **NO** — operator env flags + per-user `POST /live/enable` (confirm phrase + 8-gate `live_checklist.evaluate` + capital-cap bounds) | router.py:2175-2216; live_checklist.py:39-48 |
| PAPER→LIVE switch state-safe + reversible | YES — flips only `trading_mode`; preserves cap; does NOT close open positions; audited `mode_change_events` | router.py:2229-2277; live_opt_in_gate.py:125-154 |
| kill switch works in LIVE | YES — gate step 1 before every trade, drops live→paper on trip | gate.py:255-265 |

LIVE machinery is sound. Readiness is gated only by B1–B4 in §0.

## 8. CROSS-SURFACE PARITY (backend = sole source of truth)

Real-time transport is genuine push: Postgres `pg_notify` (mig 029 triggers cb_orders/cb_fills/cb_positions/cb_portfolio) → dedicated asyncpg LISTEN (sse.py:146-178) → per-user queue → EventSource (sse.ts:60-86), with a 15s `setInterval` + `visibilitychange` belt-and-suspenders refresh. Surfaces re-fetch authoritative REST snapshots on signal — they do NOT cache-as-truth. **Zero fabricated values** on any surface; leaderboard / copy-trade stats (Win Rate / PnL / Sharpe / Sybil) trace to real tables (`leaderboard_stats`, leaderboard_sync.py:120-185) + the Falcon wallet-360 API, with every null rendered as `—` (CopyTradePage.tsx:585-612,731-749). **Mode (LIVE/PAPER) is sourced from `user_settings.trading_mode` on both surfaces and can never render paper-as-live** (defaults always `"paper"`).

Shared-source (parity OK): **balance** (`wallets.balance_usdc`), **trading_mode**, **open-position list/count** (minor status-set nuance). 

DIVERGENCE-RISK (P1 — same account/moment can show different DERIVED numbers across web vs telebot):
- **Equity** — 3 formulas: web `/dashboard`=balance only (router.py:341); web `/portfolio/summary`=balance+deployed+unrealized (router.py:1666); telebot=balance+Σsize_usdc, no unrealized (dashboard.py:164). (F4)
- **P&L today/7d/all-time** — web sums `positions.pnl_usdc` over rolling windows (router.py:290-305); telebot sums `ledger.amount_usdc` with calendar-day `date_trunc` (ledger.py:83-96). Different table + different "today". (F5)
- **Per-position unrealized P&L** — web uses persisted `positions.current_price` (PortfolioPage.tsx:784); telebot fetches live CLOB midpoint at render (positions.py:71-118). (F6)

Reconnect re-sync: **PARTIAL** — SSE auto-reconnects + never shows fake "live"; but no dedicated on-reconnect REST snapshot re-fetch (the `connected` handler only flips a boolean, sse.ts:62-65) → up to ~15s staleness window before the poller converges. State always converges to backend truth; stale is never permanently pinned. (F10, P2)

## 9. PROD CONFIG — READ-ONLY VERIFICATION (no mutation)

Aggregate counts only (no PII), Supabase project `CrusaderBot` (ykyagjdeqcgcktnpdhes):
- `trading_mode`: **paper × 6 (100%)** — PAPER-default posture holds.
- `pos_mode`: **paper × 129 (100%)** — zero live positions ever.
- `pos_status`: **closed × 129** — no open/stuck positions currently (prior "5 stuck" already resolved).
- `role`: **admin × 1, user × 5** — RBAC clean, no tier values.
- `active_preset`: close_sweep × 2, flip_hunter × 2, (null) × 1, **`contrarian` × 1** ← one legacy non-canonical row (see F2). Verified it fires NO trades (denied at every scan path; `_CANDLE_PRESETS` gate excludes it, `_LIB_STRATEGY_NAMES` fallback is empty).

## 10. FINDINGS DETAIL

### P0 — none.

### P1
- **F1 — Bankroll circuit breaker dark-launch-OFF.** config.py:405. LIVE backstop inactive. (LIVE blocker B1; do NOT hot-enable — directive validate track.)
- **F2 — `_preset_allows` fail-open default (latent footgun + one live prod row).** signal_scan_job.py:503 returns `strategy_name in _PRESET_ALLOWED.get(active_preset, _LIB_STRATEGY_NAMES)` — an unknown/legacy preset falls back to the lib-strategy set, NOT deny-by-default. Safe ONLY because `_LIB_STRATEGY_NAMES` is currently empty (lib_strategy_runner.py:38-39) and the loop skips `active_preset IS NULL` (2443). A real prod row `active_preset='contrarian'` sits on this exact path; the code comment (33-37) invites re-adding lib strategies — at which point every legacy-preset user would silently begin trading a non-canonical strategy. Fix: default to `frozenset()` (deny-by-default). One-line, tightening-only.
- **F3 — BNB monitor-only bypass** via default-asset fallback (see §6). LIVE blocker B2.
- **F4 — Equity divergence** web vs web vs telebot (see §8). Reconcile into one shared equity computation.
- **F5 — P&L window/source divergence** web (positions, rolling) vs telebot (ledger, calendar-day). Pick one canonical source/window.
- **F6 — Unrealized-P&L mark divergence** web (DB current_price) vs telebot (live CLOB midpoint). Same position → different P&L.
- **F7 — Sizing caps diverge from ~2%/~50% spec** (`MAX_SINGLE_POSITION_PCT=0.10`, `MAX_TOTAL_EXPOSURE_PCT=0.80`, config.py:217-218). Effective per-trade reduced by Kelly (~2.5% aggressive) but absolute single-pos cap is 10%. Confirm intended before LIVE (B3).
- **F8 — Complete-set edge + TOB gates are stamp-scoped** to late_entry_v3 candidates (signal_scan_job.py:2010-2011,1952-1953). No guaranteed-loss guard for non-late_entry_v3 strategies. OK while only late_entry_v3 presets go live; coverage gap to confirm.
- **F9 — Dead module `services/allowlist.py`** (integer tiers, zero importers). Archive/remove.

### P2
- **F2b — Legacy prod row `active_preset='contrarian'` (1 user).** Fires zero trades today (safe) but its auto-trade silently does nothing. Owner-side reconcile to a canonical preset or NULL (prod data mutation — NOT performed by this audit).
- **F10 — No on-reconnect REST snapshot re-fetch** (≤15s staleness; converges). Tighten: fire `refreshAll()` from the `connected` handler (sse.ts:62-65).
- **F11 — Dead SSE `alert` handler** (singular) — App.tsx:362 listens for `alert` but client only dispatches `alerts` (sse.ts:71). Real-time alert push via the intended path never fires (falls back to `system` handler + 15s refresh). Rename to `alerts`.
- **F12 — gate.py docstring says "13-step"** but the pipeline runs 16 steps (0–15). Doc drift.
- **F13 — `services/tiers.py` FREE/PREMIUM/ADMIN** parallel scheme + `user_tiers` table dependency — consolidate onto `users.role`.
- **F14 — Win/Loss parity gap** — web excludes `market_expired` + counts `pnl<=0` loss (router.py:308-313); telebot includes expiries + counts only `pnl<0` (dashboard.py:44-57). Different win-rate across surfaces.
- **F15 — Open-position count status-set mismatch** — web counts `open`+`pending_settlement` (router.py:287); telebot `open` only (dashboard.py:40).
- **F16 — Telebot home omits LIVE/PAPER badge** (mode shown correctly in settings/setup; home surface-coverage gap only — no mislabel risk).
- **F17 — MVP telebot dashboard default literal `"⚡ Momentum"`** (mvp/dashboard.py:25) — overwritten by real preset before display; misleading default, never shown as a real strategy.
- **F18 — `constants.py MAX_POSITION_PCT=0.10` is dead** for gate caps 1–2 (gate reads `settings.*` from config.py). Two sources of truth for one cap.
- **F19 — Circuit-breaker baseline semantics** — EMA seeded to process-start balance, in-memory latch lost on restart (measures deviation from start-equity, not peak/deposits). Relevant only when B1 is enabled.
- **F20 — Demo-feed vs LIVE-feed subscription mismatch** — users auto-subscribed to DEMO_FEED_ID; scanner publishes to LIVE_FEED_ID (market_signal_scanner.py). Harmless (signal_following is gated off) but not a working default signal path.
- **F21 — Two parallel copy_trade implementations + two scan loops** (domain/strategy/strategies/copy_trade.py vs domain/signal/copy_trade.py; copy_trade_monitor vs legacy run_signal_scan). Both gate-coupled — no safety gap; maintainability/divergence hazard.

### Docs / state drift (P2)
- **F22 — Blueprint `docs/blueprint/crusaderbot.md` is stale** on BOTH (a) access model — still presents Tier 1–4 / "closed beta" / "allowlist" (27 hits) despite the RBAC implementation note, and (b) strategy roster — describes whale_mirror / signal_sniper / hybrid / trend_breakout / contrarian / full_auto / "Momentum Reversal" that no longer exist in code (code truth = 3 presets via late_entry_v3). Open a doc-sync lane to reconcile to RBAC + the 3-preset roster (flag, do not rewrite history).
- **F23 — `state/PRODUCTION_CHECKLIST.md:19`** lists stale strategies ("Copy Trade, Signal Following, Momentum Reversal"). Reconcile to the 3 canonical presets.

---

## 11. RECOMMENDED PHASE B LANES (chunked, per-lane PRs — for WARP🔹CMD authorization)

Fix order P0→P1→P2. Lanes touching risk/execution/state route to WARP•SENTINEL (Phase C). NEVER weaken the gate/Kelly/guard to pass a check.

| Lane (branch) | Scope | Tier | Notes |
|---|---|---|---|
| `WARP/ROOT/preset-gate-deny-by-default` | F2 — `_preset_allows` default → `frozenset()` | MAJOR | tightening-only; one-line + regression tests; route SENTINEL |
| `WARP/ROOT/bnb-monitor-only-fallback-fix` | F3 — drop BNB from `get_crypto_window_markets` default + re-filter | MAJOR | closes LIVE blocker B2; route SENTINEL |
| `WARP/ROOT/cross-surface-equity-pnl-parity` | F4/F5/F6 — shared equity + P&L + unrealized computation consumed by web + telebot | MAJOR | largest lane; do NOT rush before paper launch; route SENTINEL |
| `WARP/ROOT/parity-minor` | F11/F14/F15/F16/F10 — SSE `alerts` rename, win/loss + open-count alignment, reconnect refetch | STANDARD | display reconciliation |
| `WARP/ROOT/dead-code-archive` | F9 (+ F13 review) — ARCHIVE `services/allowlist.py` (MOVE, never delete) | MINOR | final lane; cleanup, must not endanger launch |
| `WARP/ROOT/blueprint-rbac-roster-sync` | F22/F23 — blueprint + checklist doc-sync to RBAC + 3-preset roster | MINOR | docs only; flag, don't rewrite history |
| `WARP/ROOT/risk-doc-truth` | F12/F18 — gate.py docstring 13→16; constants vs config single-source note | MINOR | docs/comments only |

**Owner decisions (NOT engineering fixes):** enable bankroll circuit breaker (B1) via directive validate track before LIVE; confirm sizing-cap posture (B3); reconcile the `contrarian` prod row (F2b).

**HARD FENCE honored:** no directive Sprint-1–4 execution logic was implemented; missing/off critical gates are flagged as LIVE-NOT-READY, not hot-patched.

---

## 12. SIX-SECTION SUMMARY (WARP•FORGE report contract)

1. **What was built** — Nothing built. Read-only pre-launch audit across Backend / WebTrader / Telebot + read-only prod-config validation. Output = this report.
2. **Current system architecture** — DATA→STRATEGY→INTELLIGENCE→RISK→EXECUTION→MONITORING. 3 canonical presets → late_entry_v3 engine → 16-step risk gate → paper/live router (live behind 8 guards, all OFF) → exit_watcher (TP/SL/force-close/hold) + redeem. Copy-trade is an independent gate-coupled path. Backend is sole source of truth; web + telebot are SSE-fed read-projections + control surfaces.
3. **Files created / modified** — `projects/polymarket/crusaderbot/reports/forge/prelaunch-system-audit.md` (this file); state sync to `state/PROJECT_STATE.md` + `state/CHANGELOG.md`. No production code modified.
4. **What is working** — Zero P0. All 3 strategies + copy-trade open+close paths gate-coupled, error-isolated, idempotent. Close/force-close independent of halt. Complete-set edge gate + TOB + 16-step gate + kill switch all active. RBAC enforced server-side. XRP/DOGE/HYPE non-tradeable. LIVE machinery sound + fully guarded OFF. Zero fabricated data. PAPER posture confirmed in prod (100% paper).
5. **Known issues** — 9 × P1 (bankroll CB off, preset-gate fail-open, BNB bypass, 3× parity divergence, sizing-cap divergence, edge/TOB stamp-scope, dead allowlist), 20 × P2 (see §10). LIVE = NOT-READY pending B1–B4.
6. **What is next** — WARP🔹CMD go/no-go on PAPER public launch (recommended GO) + authorization of the Phase B fix lanes in §11. Do not flip LIVE guards until B1–B4 close + SENTINEL passes.

**Suggested Next Step:** WARP🔹CMD reviews verdicts; authorize Phase B lanes (start with `preset-gate-deny-by-default` + `bnb-monitor-only-fallback-fix`, both SENTINEL-routed). LIVE flip remains OFF until B1–B4 resolved.

NEXT GATE: Return to WARP🔹CMD for go/no-go decision.
