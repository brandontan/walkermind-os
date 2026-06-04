# LIVE-path readiness audit — WARP-73

**Role:** WARP•R00T (read-only)
**Branch:** `WARP/ROOT/live-readiness-audit`
**Validation Tier:** MINOR (read + map + flag, no code changes)
**Claim Level:** FOUNDATION
**Validation Target:** the 8 LIVE-path correctness questions in WARP-73; verify paper vs live is one flag-switched code path (no paper-only landmines), with restart recovery / reconciliation / idempotency / fail-safe / kill switch / limits / secrets each accounted for.
**Not in Scope:** code changes, PR for fixes, public-readiness (custody isolation / legal / compliance — tracked separately), WARP-72 scoring orchestrator work (runs parallel).

Verdict alphabet per row: **SAFE** = correctly implemented for LIVE; **GAP** = present but with a documented hole that becomes a live landmine; **MISSING** = no implementation; **N/A** = irrelevant.

This audit gates any real-money LIVE flip. It does NOT block paper-mode trading or WARP-72.

---

## 1. Single path — paper vs live differ only by flag? *(Q1)*

Headline: the entry router is single-path and flag-gated correctly, BUT three documented behaviors are paper-only branches that would silently change behavior on the LIVE flip.

| Spec element | Code location | Verdict | Notes |
|---|---|---|---|
| Single router dispatches paper/live by `chosen_mode` | `domain/execution/router.py:26-107 execute()` | SAFE | One entry function; both engines share signature; `chosen_mode` set by risk gate, not by the engine. |
| LIVE engine re-asserts ALL 5 activation guards inside `execute` | `domain/execution/live.py:52-83 assert_live_guards`, `:117-151` | SAFE | Defense in depth: router calls `assert_live_guards` (`router.py:37`), then `live.execute` re-checks the same guards + logs CRITICAL on guard bypass attempt (`live.py:123-137`). |
| Pre-submit failure → safe paper fallback; post-submit failure → DO NOT paper-duplicate | `router.py:67-102` (`LivePostSubmitError`/`LivePreSubmitError`) | SAFE | Typed errors split the two windows; post-submit re-raises after `fallback.trigger_for_clob_error` flips the user to paper for the NEXT signal. |
| Close path re-uses the engine that opened the position | `router.py:123-136 close()` | SAFE | Routes by `position["mode"]`; live close intentionally skips open-time guards (an on-chain position must always be unwindable). |
| Paper engine writes order as `status='filled'` instantly; live engine writes `'pending'` then `'submitted'` | `paper.py:41-51` vs `live.py:240-251`, `:325-331` | GAP | This IS the paper-only shortcut. Paper completes the position + ledger debit in one transaction; live splits across submit + poll + ws fill. Anything downstream that assumes "if order row exists then position exists" is wrong on the LIVE flip — see Q2 and Q4. |
| Slippage guard + aggressive limit + tick/neg-risk fetch | `live.py:177-228`, `slippage.compute_aggressive_limit_price` | SAFE | LIVE only; PAPER fills at the signal price unconditionally. Acceptable asymmetry (paper is a frictionless harness), but means paper PnL ≠ live PnL — flagged as a known modeling gap, NOT a landmine. |
| WS streaming live fills (`handle_ws_fill` / `handle_ws_order_update`) | `lifecycle.py:942-1112`; wired at `scheduler.py:701-740 ws_connect/ws_watchdog` | SAFE | No-op when `USE_REAL_CLOB=False`; bridges into the same `_on_fill` / `_terminal_close` paths the poller uses. Dedup with poller is via `UPDATE … RETURNING id` race + `ON CONFLICT (fill_id) DO UPDATE`. |
| Lifecycle poller bail when `USE_REAL_CLOB=False` even on `mode='live'` rows | `lifecycle.py:192-194 _resolve_one` | SAFE | Paper-mode safety bail: a `mode='live'` row left over from a prior LIVE run is touched but never falsely "filled" while operator has the toggle off. |

**Paper-only shortcuts enumerated (the three landmines):**
1. `paper.execute` writes `orders.status='filled'` + `positions.status='open'` in ONE txn (no submit/poll/fill split). LIVE flow has three distinct status transitions and four failure windows. Any consumer (UI, analytics, exit_watcher) that assumes "open position ↔ no in-flight order" can mis-handle the in-flight gap on LIVE.
2. `paper.close_position` resolves PnL synchronously from `exit_price` arg; LIVE close submits a SELL and assumes it fills at the limit (`live.py:462-470` posts SELL @ `exit_price`, doesn't await broker confirmation, marks `closed` immediately at `:490-495`). On a partial fill or non-fill the position is closed in DB without on-chain confirmation. **GAP** flagged separately in §3 as live-close reconciliation hole.
3. `paper.execute` records no `strategy_metadata` gap: it DOES persist `strategy_metadata` (paper.py:62-70). `live.execute` ALSO persists it (`live.py:336-347`). So that earlier "WARP/ROOT/candle-auto-router known gap" item is now **CLOSED** — both engines persist metadata. No landmine here today. (Cross-referencing the candle-auto-router report which still calls this a LIVE gap: the report is stale.)

---

## 2. Restart / crash recovery — TOP landmine *(Q2)*

Headline: **MISSING for on-chain truth.** What exists is DB-side resume only.

| Spec element | Code location | Verdict | Notes |
|---|---|---|---|
| One-shot startup log of paper+live open-position counts | `scheduler.py:612-644 log_resumed_open_positions`, registered at `:1106-1110` | SAFE | Logs `startup_recovery: Resumed monitoring N open positions` once at boot. Useful audit trail, but it does NOT touch broker truth. |
| Exit watcher resumes monitoring every DB-side open position on every tick | `scheduler.py:1029-1030` (`check_exits` @ `EXIT_WATCH_INTERVAL`); `registry.list_open_for_exit` | SAFE | TP/SL/resolution scan runs against `positions WHERE status='open'` on every tick — pre-existing rows are picked up automatically. |
| In-flight order poller resumes every `mode='live'` order in `STATUS_OPEN` after restart | `lifecycle.py:107-122` (`poll_once` SELECT); `scheduler.py:1043-1045` | SAFE | Submitted / pending / partial-filled rows ride the broker poll loop after restart. **Crucially:** only orders the bot WROTE to the `orders` table before crash. |
| Reconcile DB ↔ broker for orders the broker accepted but the bot crashed BEFORE writing the row | — | **MISSING** | `live.execute` writes `orders` as `'pending'` BEFORE `post_order` (`live.py:240-254`), so the normal path is safe. BUT: if the process crashes between `post_order` returning and the `UPDATE orders SET status='submitted'` (`live.py:325-331`), the order row stays `'pending'` with no `polymarket_order_id` → poller marks it stale after `ORDER_POLL_MAX_ATTEMPTS` (`lifecycle.py:202-208`), NEVER reconciles the broker-side filled order. Operator gets a stale alert, must reconcile via Polymarket dashboard. Phantom live exposure window. |
| Reconcile DB ↔ broker for positions opened on Polymarket but never recorded in DB (e.g. manual orders placed on the funder address outside the bot) | — | **MISSING** | No `client.get_open_orders()` boot pass exists. `get_open_orders` is implemented on the adapter (`integrations/clob/adapter.py:382`) but is never called from any startup or scheduled job. |
| Resume in-flight COMPLETE-SET orders | `domain/execution/complete_set_exec.py:1413-1488 reconcile_complete_set_orders`; `scheduler.py:1048-1051` | SAFE — but scoped only to complete-set | Job is registered only when `COMPLETE_SET_ARB_ENABLED`. Reconciles `orders.status IN ('pending','unknown')` against broker truth, halts + pages on uncertainty. **This is the exact pattern missing for the late_entry_v3 / signal_following path** — and it would be ~75 lines of follow-on work to generalize. |
| Resume `positions.status='closing'` (atomic close claim taken at `live.py:436-441` before the SELL submit) on crash | — | **MISSING** | If the bot crashes between the `closing` claim and the broker SELL ack, the position stays `'closing'` forever. Nothing in the boot path scans for orphaned `'closing'` rows. Operator-driven recovery only. **HIGH** before LIVE — the close path's atomic claim is what guarantees no double-SELL, but it leaves a stuck-state if interrupted. |
| Crash mid-`_on_fill` (broker says filled, DB write fails before `RETURNING id` clears) | `lifecycle.py:308-334` | SAFE | Wrapped in `conn.transaction()` with `UPDATE … WHERE status = ANY(STATUS_OPEN) RETURNING id`. On retry, the still-`'submitted'` row is re-resolved against broker, fills again. Idempotent. |

**Recommendation:** generalize `reconcile_complete_set_orders` into `reconcile_live_orders` that scans every `mode='live'` row in `('pending', 'unknown', 'closing')` past a stale threshold, queries broker per row, and halts+pages on uncertainty (mirrors the existing per-row resolution pattern). The `'closing'` recovery is the single most important add — without it a crash during close strands the position in DB-only purgatory while the on-chain exposure is unknown. This is the *exact* gap the operator's prompt called out ("the observed paper behavior clears in-flight positions").

---

## 3. On-chain ↔ DB position+balance reconcile *(Q3)*

| Spec element | Code location | Verdict | Notes |
|---|---|---|---|
| Periodic position-state reconcile (broker open-orders ↔ DB open positions) | — | **MISSING** | No scheduled job exists. Closest analog is `reconcile_complete_set_orders` (scoped to complete-set only). Without it, a position closed/cancelled outside the bot (operator manual on dashboard, market resolution-cancel) drifts. |
| Periodic on-chain USDC balance reconcile vs internal ledger | `wallet/ledger.py` (internal); on-chain only read via `polygon.usdc_balance` in withdrawal preflight | **MISSING** | Custodial wallet design uses internal ledger as authoritative (per `max-trade-per-user.md` report: "internal ledger is authoritative"). For PAPER this is fine — no real USDC. For LIVE, no scheduled reconcile of master-pool actual balance vs sum-of-user ledger balances. Drift would manifest as silent capital divergence; only detected at withdrawal preflight (per-user) or manual /admin check. |
| Per-order broker truth poll | `lifecycle.py:212 get_order(broker_id)` per polling tick | SAFE | Tight loop; recovers from broker-side state changes (fill, cancel, expire) the bot didn't initiate. |
| WebSocket live updates ↔ DB | `lifecycle.py:942-1112`; dedup via `ON CONFLICT (fill_id) DO UPDATE` + `UPDATE … RETURNING id` race | SAFE | Two writer paths (WS + poll) coexist without double-counting. |
| Drift detection / alerting | — | **MISSING** | No periodic "broker says N open, DB says M open, diff=K" check that pages operator on diff > 0. Combined with Q2 MISSING items, this is the single biggest LIVE-readiness gap. |

**Recommendation:** add `reconcile_live_state` (every 5–15 min): `client.get_open_orders()` → diff vs `orders WHERE mode='live' AND status IN STATUS_OPEN`. Diff > 0 in either direction halts + pages. Cheap (one CLOB call per tick) and is the operational tripwire that catches all 5 of the MISSING patterns above.

---

## 4. Idempotency — retry/restart cannot double-submit *(Q4)*

| Spec element | Code location | Verdict | Notes |
|---|---|---|---|
| `orders.idempotency_key` UNIQUE constraint + `INSERT … ON CONFLICT DO NOTHING RETURNING id` | `live.py:238-253`, `paper.py:39-54`; underlying schema `migrations/001_init.sql` | SAFE | Same DB primitive on both paths. On race, second writer sees `None` and returns `{"status": "duplicate"}`. |
| Pre-submit duplicate fast-path read | `live.py:161-175` | SAFE | Avoids unnecessary CLOB metadata fetches when key is already a known dup. |
| Idempotency_key derivation includes UTC date → cross-day re-entry intentional, same-day blocked | `services/signal_scan/signal_scan_job.py:1720-1733 _build_idempotency_key` (`sf:<sha256_32>`) | SAFE | `f"{user_id}:{market_id}:{side}:{utc_date}"` is stable across publications, restart-safe. |
| Legacy copy-trade idem_key uses `src_tx` substring | `scheduler.py:512-513` | SAFE | Different prefix, different scope, distinct UNIQUE slot. |
| Risk gate step 10 also short-circuits on `idempotency_keys` 30-min window | `gate.py:464-470 _idempotent_already_seen`, `:589 _record_idempotency` | SAFE | Belt-and-suspenders dedup. |
| Idempotency_key reaches both engines unmodified | `router.py:26-107` (signature carries `idempotency_key` through both branches) | SAFE | No transformation in router. |
| Restart between `INSERT orders 'pending'` and `client.post_order` — retry replays same key → second `INSERT` no-ops, second `post_order` blocked | `live.py:238-275` | SAFE | Yes: on restart the `orders` row exists; the LATER tick will read it via the pre-check OR the broker poll will discover it; `_dup` precheck at `live.py:164-175` returns `{"status": "duplicate"}` before re-entering `post_order`. **But:** the order is still `'pending'` with no `polymarket_order_id` until the original `post_order` ack happened — and that ack was lost in the crash. See Q2 GAP — the `'pending'` row stays orphaned. Idempotency stops a DOUBLE submit; reconciliation is what would resolve the unknown first submit. |
| In-flight FAILED-after-submit → marked `'unknown'`, operator alert | `live.py:288-312` | SAFE | Ambiguous submit path. Re-raises `LivePostSubmitError`. |

**Net:** idempotency itself is solid. The hole is what happens when the primary submit succeeds at broker but the ack never reaches the bot — there's no idempotency-replayable retry of that order (because the broker won't accept the same client-side nonce / signed order twice). The remedy is RECONCILIATION (Q3), not stronger idempotency.

---

## 5. Fail-safe on dependency loss *(Q5)*

| Spec element | Code location | Verdict | Notes |
|---|---|---|---|
| CLOB market metadata (tick_size, neg_risk) unavailable → pre-submit fail, paper-fallback | `live.py:182-197` (`MarketDataClient`) | GAP — silent degradation | Wraps in `LivePreSubmitError` → router routes to PAPER (`router.py:80-102`). Operator gets an audit row + Telegram only on the explicit `ENABLE_LIVE_TRADING=false` branch (`router.py:91-97`), NOT on plain MDC unavailability. **This is exactly the "paper-only landmine" pattern WARP-73 calls out:** "CLOB down → silent paper fallback" not "halt safely". For a low-volume CLOB API hiccup this is benign; for a sustained MDC outage every LIVE signal silently degrades to paper without paging. |
| CLOB CircuitBreaker trips after N consecutive transport failures | `integrations/clob/circuit_breaker.py`; package singleton via `get_clob_breaker`; alert via `_on_circuit_open` → `notify_operator` | SAFE | When OPEN, `post_order` raises `ClobCircuitOpenError` → caught by router as generic Exception path. Operator paged immediately. Auto half-opens on `CIRCUIT_BREAKER_RESET_SECONDS`. Admin-path calls (`cancel_all_orders` / `get_open_orders` / etc) intentionally NOT breaker-wrapped so recovery is reachable when order-path is tripped (`reports/sentinel/resilience.md:104`). |
| CLOB auth failure (signing failure pre-network) | `live.py:277-287 ClobAuthError` | SAFE | Distinguished from network failure → `LivePreSubmitError` (router falls back to paper, NOT raises). Treated as definitively pre-submit-safe. |
| Polygon RPC down → on-chain reads (deposits, sweeps, fast-topup price fallback) | `scheduler.py:182-194 watch_deposits`; `signal_scan_job._maybe_fire_fast_topup` price fallback | SAFE | All wrap in try/except + log + bail without advancing cursor. Deposit recovery on next tick. |
| Gamma / RTDS / oracle down | not consumed in the trade decision path directly (per WARP-71 audit) | N/A | Oracle metadata is advisory-only; no production gate reads it. Gamma is the seed for `markets.yes_price` / `no_price` — used as a FALLBACK in `_maybe_fire_fast_topup` and a sub-cent guard exists (`reports/forge/fast-topup-tick-guard.md`). |
| TOB freshness gate rejects stale entry_price (>= `TOB_STALE_MS`, default 2000) | `signal_scan_job.py` step 3b-0 (per `reports/forge/tob-freshness-gate.md`) | SAFE | Pre-submit guard on every late_entry_v3 candidate. |
| WebSocket disconnect → `ws_watchdog` reconnects | `scheduler.py:720-740` | SAFE | Watchdog tick checks `is_alive`, force-reconnects on drop. |

**Live-readiness GAP:** the silent paper-fallback on MDC/CLOB pre-submit failure means an operator running LIVE for hours during a sustained CLOB outage would generate paper-only PnL while believing they were live. Recommend: distinguish "intentional paper fallback (`live_blocked_fallback_paper`)" from "dependency failure paper fallback" and page operator on the second class.

---

## 6. Kill switch — global + per-user halt *(Q6)*

| Spec element | Code location | Verdict | Notes |
|---|---|---|---|
| Risk gate step 1 reads kill-switch state on every signal | `domain/risk/gate.py:340-353` | SAFE | Uses 30s in-process cache (`domain/ops/kill_switch.py` `_Cache` w/ `CACHE_TTL_SECONDS=30.0`). |
| DB read fails → **assume kill switch ACTIVE** (fail-safe) | `domain/ops/kill_switch.py:127-133` | SAFE | "A risk gate that opens the floodgates because the read failed would be the worst possible default." Exactly right. |
| Three convergence paths — Telegram /kill, scanner DB-flag check, env `KILL_SWITCH=true` at startup | `domain/risk/kill_switch_exec.py:1-11` + `main.py:225-229` (env-var check) | SAFE | All three → `execute_kill_switch(reason, triggered_by)` → audit row guaranteed (no silent activations). |
| `lock` mode forces every user `auto_trade_on=FALSE` + flips `live` users back to `paper` | `domain/ops/kill_switch.py:226-246 set_active(action='lock')` | SAFE | R12 live-to-paper cascade: after a lock event, releasing the kill switch alone does NOT re-arm live users — each must re-run `/live_checklist`. Correct safety posture. |
| User-mode flip to paper if kill trips while user was live | `domain/risk/gate.py:347-351 live_fallback.trigger_for_kill_switch_halt` | SAFE | Belt + suspenders alongside the lock cascade above. |
| `_cancel_pending_orders` on kill switch trips | `domain/risk/kill_switch_exec.py:58-69` | GAP | Marks `orders.status='cancelled'` in DB but does NOT call `client.cancel_all_orders()` on the broker. For a kill triggered while real GTC orders rest in the book, the DB says cancelled but the broker still has them — a fill arriving via WS after kill would corrupt accounting. The acknowledged future lane is the "active order cancellation half of directive #6 deferred to a future live-mode lane (paper has nothing to cancel)" (`bankroll-circuit-breaker.md`). **HIGH** before LIVE. |
| Per-user kill switch (operator pause a single user) | `users.set_paused(True)` consumed by risk gate step 2 (`gate.py:359-361`) | SAFE | Operator route from Admin Console + Telegram `/admin` HUD. |
| Kill switch test coverage | `tests/test_kill_switch.py`, `test_kill_switch_paths.py` (3 paths) | SAFE | All three activation paths have hermetic tests. |

**Net:** the read/write/cache plumbing is hardened. The one gap is broker-side order cancellation on kill — currently the bot's local view diverges from broker truth for the kill window. Mitigated short-term by the gate refusing any NEW order; not mitigated for orders already resting.

---

## 7. Limits on live path — exposure, daily-loss, drawdown, max-position *(Q7)*

| Spec element | Code location | Verdict | Notes |
|---|---|---|---|
| Hard risk caps (step 0): per-user open + sizing caps | `gate.py:327-338 validate_risk_caps` | SAFE | Fires BEFORE any per-step logging — fail-fast. |
| Daily loss limit (most-restrictive of profile / override / env `MAX_DAILY_LOSS_USD`) | `gate.py:402-412` step 5 | SAFE | Correctly takes minimum cap. |
| Max drawdown circuit | `gate.py:415-422` step 6 + `_max_drawdown_breached` | SAFE | Triggers `live_fallback.trigger_for_drawdown_halt` for live users. |
| Concurrent trades (per-profile or override) | `gate.py:425-433` step 7 | SAFE | |
| Correlated exposure cap (most-restrictive of system constant + `MAX_TOTAL_EXPOSURE_PCT`) | `gate.py:436-453` step 8 | SAFE | |
| Liquidity floor (per-profile, user override + 1k hard floor) | `gate.py:473-483` step 11 | SAFE | |
| Edge bps floor | `gate.py:485-492` step 12 | SAFE | No-ops when candidate has no measured edge. |
| Market status guard (`active` only) | `gate.py:495-498` step 13 | SAFE | |
| **Kelly fraction hard cap = 0.25** (CLAUDE.md rule) | `gate.py:499-510` | SAFE | `K.KELLY_FRACTION` asserted in `(0, 0.25]` at evaluation; per-profile kelly clamped to global cap; `max_pos_size = balance × max_pos_pct × kelly`. |
| Slippage / market-impact guard | `gate.py:553-559` step 14 + `check_market_impact` | SAFE | Per-trade impact rejection. |
| **Per-user LIVE capital cap** (step 15 — aggregate open + proposed must stay under cap) | `gate.py:561-587` | SAFE | Cap-0 default rejects with `live_not_opted_in` — opt-in via WebTrader `/live/enable` or Telegram `/enable_live` (typed-confirm + cap-capture). Without this gate, every live trade rejected `live_not_opted_in` historically (`live-path-hardening.md`). |
| SLIPPAGE_GUARD_PCT (5% fence) inside live engine | `live.py:215-228` | SAFE | Defense-in-depth on top of the risk gate's slippage guard. |
| Robustness downgrade — module-level UNTRADEABLE → forced paper per-candidate | `gate.py:541-549` | SAFE | Avoids user-level fallback that would block their other modules. |
| Bankroll circuit breaker (per-user drawdown trip) | `signal_scan_job._evaluate_bankroll_circuit_breaker` step 0a (per `bankroll-circuit-breaker.md`) | SAFE | Latched gate with hysteresis; default OFF; fails CLOSED on config error. |
| Active LIVE limit fence reads `live_capital_cap_usdc` from settings table | `_load_enrolled_users` extended in `live-path-hardening.md` (Lane 5/5) | SAFE | Previously omitted → every live trade rejected at gate step 15. Fixed. |

**Net:** limits stack is the strongest area of the LIVE path. All 13 gate steps + step 15 cap fire before any execution.

---

## 8. Secrets / signing keys *(Q8)*

| Spec element | Code location | Verdict | Notes |
|---|---|---|---|
| `.env`-only secrets (no hardcoded keys) | `.env.example`, `config.py` Pydantic Settings (`POLYMARKET_PRIVATE_KEY`, `POLYMARKET_API_KEY/SECRET/PASSPHRASE`, `POLYMARKET_FUNDER_ADDRESS`, builder triplet) | SAFE | All resolved via `get_settings()`; no `os.getenv` reads in trade path. |
| `POLYMARKET_PRIVATE_KEY` → auto-derive `api_key/secret/passphrase` at startup | `integrations/clob/__init__.py:150-199 ensure_clob_credentials`; called from `main.py:120-121` | SAFE | Cached in module-level `_derived`, never persisted. Env vars take priority over derived. |
| Credentials never logged | `integrations/clob/__init__.py:197-199` (`logger.info("…", _derived["api_key"][:8])` — key only, prefix-truncated) | SAFE | No full secret in logs. No `repr(settings)` debug paths. (Spot-checked — `tests/` test_clob_factory references in test fixtures only.) |
| Custodial wallet keys (per-user EOA private keys for sweeps + redeems) | `wallet/vault.py` (encrypted at rest in `wallets.encrypted_pk` via `wallet/generator.py`); `get_decrypted_pk(user_id)` in-process only | SAFE | Vault decrypt is per-call, never cached past the txn. Sweeps + redemptions read once and discard. |
| Master hot-pool key (single bot key for live CLOB auth) | `POLYMARKET_PRIVATE_KEY` env-only, single value per Fly machine | SAFE | Single point of compromise — by design for a custodial bot. Mitigated by `nonce_lock` serialization (`live-path-hardening.md` L1). |
| Builder API triplet for Polymarket builder rebates | `POLYMARKET_BUILDER_API_KEY/SECRET/PASSPHRASE` in env; passed to `ClobAdapter` constructor at `__init__.py:348-350` | SAFE | Optional; absent → no builder header, normal path. |
| HMAC signing on every L2 request | `integrations/clob/auth.py build_l2_headers + build_hmac_signature` | SAFE | Standard HMAC-SHA256 per Polymarket spec. |
| EIP-712 L1 signing | `integrations/clob/auth.py build_l1_headers + ClobAuthSigner` | SAFE | Used for credential derivation + signed-order construction. |
| Mainnet preflight validates all secrets present + signatures work | `scripts/mainnet_preflight.py` (`POLYMARKET_PRIVATE_KEY`, `POLYMARKET_API_SECRET` base64 sanity) | SAFE | Operator can run preflight before LIVE flip. |
| SSE auth scope separation (24h main JWT not leaked into URLs) | `webtrader/.../router.py` per `sse-token-exchange.md` (Lane 3b/5) | SAFE | 60s scoped token via POST; main JWT never in EventSource URL. Tangential to CLOB auth but part of the secret-hygiene story. |

**Net:** secret handling is solid. The single residual operational risk — single hot-pool key — is inherent to custodial-bot design and is acknowledged.

---

## Rollup — LIVE readiness gap list, prioritized

| # | Severity | Gap | Where | Fix sketch (follow-on chunks) |
|---|---|---|---|---|
| **1** | **P0 — blocks real-money LIVE** | No on-chain ↔ DB reconciler for `mode='live'` orders in `('pending','unknown','closing')` past stale threshold | `domain/execution/` (no module exists) | New `reconcile_live_orders` modeled on `complete_set_exec.reconcile_complete_set_orders:1413` — generalize to all live strategies. Scheduler tick every 60–300s. Halt + page on uncertainty. |
| **2** | **P0** | Crash mid-`positions.status='closing'` strands position in DB-only purgatory | `live.py:436-441 close_position` | Boot scan for `status='closing'` AND `closed_at IS NULL` past stale window → reconcile against broker SELL truth. Part of #1's reconciler scope. |
| **3** | **P0** | Kill switch does NOT call `client.cancel_all_orders()` — DB cancels diverge from broker open book | `domain/risk/kill_switch_exec.py:58-69 _cancel_pending_orders` | Add `client.cancel_all_orders()` call gated on `USE_REAL_CLOB`. Documented as deferred in `bankroll-circuit-breaker.md`. ~15 lines. |
| **4** | **P1** | Silent paper-fallback on CLOB MDC pre-submit failure looks identical to deliberate fallback | `router.py:80-102` + `live.py:177-197` | Distinguish `live_dependency_unavailable_fallback_paper` audit action; page operator on this class (not on `ENABLE_LIVE_TRADING=false` class). |
| **5** | **P1** | No periodic broker open-orders count ↔ DB open-orders count drift detector | — | One CLOB `get_open_orders()` call per tick; diff > 0 in either direction → halt + page. Cheapest tripwire that catches #1, #3, and silent manual-on-dashboard interference. |
| **6** | **P2** | On-chain USDC balance ↔ internal ledger reconcile is manual only | `wallet/ledger.py` (authoritative); no scheduled balance probe | Periodic master-pool `polygon.usdc_balance` ↔ `SUM(ledger.balance_usdc)` — drift threshold-paged. |
| **7** | **P2** | `live.py:462-470 close_position` posts SELL @ `exit_price` and immediately marks position closed in DB without awaiting broker fill confirmation | `live.py:485-507` | Convert close to async-fill-aware: keep `'closing'` until WS / poll confirms terminal status; reconciler (#1) catches the stuck case. |
| **8** | **P3** | Paper engine "instant fill" makes paper PnL ≠ live PnL — modeling gap, not a landmine | `paper.py:41-51` | Documented; not a fix target. Operator must read paper stats as upper-bound. |

**P0 gates LIVE.** P1 should ship in the LIVE-readiness lane (same window as P0 fixes). P2/P3 ride along when convenient.

---

## Headline findings — short form for WARP🔹CMD

- **Single path:** SAFE, with three documented paper-only shortcuts. Two are benign modeling artifacts; the third (paper instant-fill obscures live's submit/poll/fill split) is the *concept* behind every P0 gap below.
- **Restart recovery:** **MISSING for on-chain truth.** DB-side resume is fine; broker-side reconcile only exists for the complete-set product. Late_entry_v3 / signal_following on LIVE would orphan in-flight and `'closing'` rows on a Fly restart.
- **Reconciliation:** **MISSING.** No periodic broker ↔ DB diff. The complete-set reconciler is the right template; generalize it.
- **Idempotency:** SAFE. UNIQUE constraint + early pre-check + UTC-date-stable key — survives retry/restart correctly. The hole is reconciliation, not idempotency.
- **Fail-safe:** SAFE for transport (breaker + retry), GAP on classification (CLOB MDC failure silently looks like a deliberate paper fallback).
- **Kill switch:** SAFE on read/cache/lock cascade, **GAP** on broker-side cancellation of resting orders.
- **Limits:** SAFE — strongest area of the LIVE path; all 13 gates + cap-15 fire before execution.
- **Secrets:** SAFE. `.env`-only, never logged, EIP-712 + HMAC-SHA256 properly scoped, mainnet preflight covers the pre-flip checks.

**Net LIVE-readiness verdict:** NOT-READY for real money. The three P0 gaps are tractable (~150–250 LOC + tests total) and form a single coherent reconciliation lane. Recommend ONE follow-on epic `WARP/ROOT/live-reconciliation` with three chunks:
- Chunk A — generalize `reconcile_complete_set_orders` → `reconcile_live_orders` (P0 #1 + #2 covered together).
- Chunk B — kill-switch broker-side cancellation (P0 #3).
- Chunk C — periodic drift detector (P1 #5) + classified paper-fallback audit (P1 #4).

These can ship in parallel with WARP-72 (scoring orchestrator) without conflict — they touch `domain/execution/` + `domain/risk/kill_switch_exec.py`, not the signal-evaluation path.

---

- **Validation Tier:** MINOR (read + map + flag)
- **Claim Level:** FOUNDATION (audit only; no code/state mutation)
- **Validation Target:** see §1–8 above
- **Not in Scope:** code changes, PR for fixes, public-readiness gate, WARP-72
- **Suggested Next Step:** WARP🔹CMD to approve the `WARP/ROOT/live-reconciliation` epic (3 chunks above) before flipping LIVE. Parallel-safe with WARP-72.
