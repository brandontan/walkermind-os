# SENTINEL — Smart Strike (candle_auto) LIVE Go-Live Readiness Audit

Role: WARP•SENTINEL (read-only audit)
Branch: WARP/smart-strike-live-readiness-audit (from origin/main HEAD ab88219c)
Tier: MAJOR
Date: 2026-06-08 (Asia/Jakarta)
Verdict: READY-PENDING-OWNER (one engineering item OPEN, in-progress parallel lane)

---

## TEST PLAN / SCOPE

Scope: the candle_auto -> late_entry_v3 playbook (flip_hunter / safe_close / close_sweep) LIVE path ONLY.
Out of scope: copy_trade, signal, value, weather, complete-set arb, and all non-candle_auto strategies.
Method: code-truth verification. Each item cited to file:line. Default = UNSAFE until proven.
Status legend: VERIFIED-READY / OPEN / OWNER-GATED / N-A.

This audit changed ZERO production code. The only file created is this report.

---

## FINDINGS (per item 1-10)

### 1. LIVE order placement + strategy_metadata persist (GAP A) — VERIFIED-READY

- Real CLOB submit via ClobClientProtocol: `domain/execution/live.py:268` (`client.post_order(... side="BUY" ...)`) for entry; `domain/execution/live.py:462` (SELL) for exit.
- Idempotency claim before submit: INSERT 'pending' ON CONFLICT DO NOTHING — `live.py:240-254`; early dup precheck `live.py:164-175`.
- tick_size / neg_risk fetched pre-submit, fail-closed to LivePreSubmitError — `live.py:185-197`.
- Position persist on fill incl. `strategy_metadata`: INSERT positions lists `strategy_metadata` column at `live.py:338` and binds `json.dumps(strategy_metadata) if strategy_metadata else None` at `live.py:346` — IDENTICAL shape to paper.py:62 / paper.py:70.
- GAP A CLOSED. The WORKTODO candle-auto-router note ("live.py strategy_metadata not persisted -> force-exit fallback PAPER-only") is now STALE; live.py persists it.
- Ledger debit atomic with persist: `live.py:349`. Post-submit DB failure raises LivePostSubmitError (`live.py:359`) so router will NOT paper-duplicate.

### 2. Force-exit in LIVE (per-rule timed exit) — VERIFIED-READY

- late_entry_v3.evaluate_exit consumes `force_exit_at_rem_sec` from the payload; exit_watcher builds that payload.
- exit_watcher reads stored per-rule threshold from the position's strategy_metadata: `domain/execution/exit_watcher.py:202-211` (candle_auto preset has no entry in the static map, so it falls back to `position.strategy_metadata.get("force_exit_at_rem_sec")`).
- The position row carries strategy_metadata because the open-for-exit loader selects `p.strategy_metadata`: `domain/positions/registry.py:164`, decoded into `OpenPositionForExit.strategy_metadata` at `registry.py:235`.
- Loader is MODE-AGNOSTIC — selects `p.mode` (registry.py:161) with no `WHERE mode='paper'` filter (`_OPEN_FOR_EXIT_COLS`, registry.py:159-175). Live positions are loaded the same as paper.
- Net: because item 1 now persists strategy_metadata in LIVE, the candle_auto per-rule timed force-exit fires in LIVE, not just paper. VERIFIED.

### 3. Reconcile (broker-truth orphan/drift) — VERIFIED-READY

- `domain/execution/reconcile.py:85` `class LiveOrderReconciler`; `reconcile_once()` at `reconcile.py:110`.
- Pulls broker open orders `client.get_open_orders()` (`reconcile.py:139`), diffs vs DB, ORPHAN + DB_ONLY classes (`reconcile.py:160-167`); throttled operator page; detection/telemetry only, no mutate; paper/non-live no-op (`reconcile.py:124`); fail-soft.
- Scheduler job wired: `scheduler.py:1187` gated `RECONCILE_LIVE_ORDERS_ENABLED` (default True, `config.py:897`), registered id `live_order_reconcile` (`scheduler.py:1190`).
- Matches WARP-74 Chunk A (SENTINEL 95/100, MERGED #1612). Present on main.

### 4. Kill-switch broker cancel-all — VERIFIED-READY

- `domain/risk/kill_switch_exec.py:73` `_broker_cancel_all_orders()` calls `client.cancel_all_orders()` (`kill_switch_exec.py:100`).
- Gated on USE_REAL_CLOB (`kill_switch_exec.py:92`); paper = no-op (`kill_switch_exec.py:93`); fail-soft (`kill_switch_exec.py:103-105`); audited (`kill_switch_exec.py:156-163`); operator paged on FAILED broker-cancel (`kill_switch_exec.py:170-181`).
- Runs BEFORE the DB-cancel in execute_kill_switch (`kill_switch_exec.py:128-145`). Matches WARP-74 Chunk B (SENTINEL 97/100, MERGED #1613).

### 5. Live guard chain composes as a hard AND -> paper on any failure — VERIFIED-READY

- Router entry `domain/execution/router.py:53` `execute()`. Order of gates for chosen_mode=='live':
  1. WARP-92 GLOBAL toggle FIRST: `router.py:68` `if not await is_global_live_enabled():` -> audit + `_paper()`. Fail-safe to paper on missing key / any DB error (`domain/ops/global_live_gate.py:110-144`, returns False on error).
  2. `live_engine.assert_live_guards(role, trading_mode)` `router.py:82`; any failure -> CRITICAL log + audit `live_blocked_fallback_paper` + `_paper()` (`router.py:83-100`).
- assert_live_guards (`live.py:52-83`) requires ALL of: ENABLE_LIVE_TRADING, EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, RISK_CONTROLS_VALIDATED, SECURITY_HARDENING_VALIDATED, USE_REAL_CLOB, role=='admin', trading_mode=='live'. Any one false -> raise -> paper.
- gate.py `_passes_live_guards` (`domain/risk/gate.py:310-322`) mirrors the same 5 flags + USE_REAL_CLOB + role + trading_mode; `chosen_mode = "live" if _passes_live_guards(...)` at `gate.py:665`.
- Defense-in-depth: live.execute re-asserts guards (`live.py:151`) + GUARD_BYPASS_ATTEMPT CRITICAL log if reached with incomplete guards (`live.py:123-137`).
- Executor hard-gate also exposed as `domain/execution/live_activation.py:46` `is_live_execution_allowed` = env AND global toggle AND per-user opt-in (`live_activation.py:55-80`).
- Composition is a strict AND across all layers; any failure resolves to paper. VERIFIED.

### 6. Per-user opt-in (/live/enable + gates) — VERIFIED-READY

- `/live/enable` endpoint: `webtrader/backend/router.py:2572` (schema `webtrader/backend/schemas.py:460`). Requires typed phrase + cap bounds check `0 < cap <= LIVE_CAP_MAX_USDC` (`router.py:2611-2614`).
- Opt-in state shape: paper_mode_override=false, trading_mode='live', live_capital_cap_usdc>0 enforced in `domain/execution/live_activation.py:69-80`.
- Shared source of truth + cap validation: `domain/activation/live_opt_in_gate.py` (`LIVE_ENABLE_CONFIRM_PHRASE` :56, `validate_live_capital_cap` :70, bounds :61-62). Mode-change events audited (`live_opt_in_gate.py:129-158`).
- 8-gate pre-activation checklist: `domain/activation/live_checklist.py` GATE_ORDER (`live_checklist.py:39-48`) — EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, ENABLE_LIVE_TRADING, active_subaccount_with_deposit, strategy_configured, risk_profile_configured, two_factor_setup_complete, operator_allowlist_approved. Read-only; never sets a guard. VERIFIED.

### 7. Slippage gate (WARP-87) — TIER WIRING VERIFIED-READY / PER-CELL CAPS OPEN (parallel lane)

- Tier classifier + table present & pure: `domain/risk/slippage_gate.py` — GREEN<=0.15 / WATCH<=0.30 / HALT>0.30 (`slippage_gate.py:48-49,114-136`); `LIVE_SIZE_CAPS_USDC = {"btc/5m":500.0, "eth/5m":100.0}` (`slippage_gate.py:56-59`). NOTE: sol/5m NOT present in the cap table.
- Wired at gate.evaluate step 14b, LIVE-ONLY: `domain/risk/gate.py:706` `if chosen_mode == "live":` -> estimate + `SG.evaluate_slippage_gate(...)` (`gate.py:723-728`); HALT / size-cap breach -> `GateResult(False, ...)` (`gate.py:729-735`); WATCH -> warn + Sentry breadcrumb pass (`gate.py:736+`). Pure, no DB read (honours #1694 pool-wedge RCA).
- BINDING GAP (OPEN — in progress, parallel lane WARP/smart-strike-cell-cap-binding): the per-cell cap depends on `ctx.cell`, `ctx.orderbook_depth_usdc`, `ctx.spread`, which default to None on `GateContext` (`gate.py:88-90`) and are NOT populated at the candidate construction site `services/trade_engine/engine.py:303-334` (no `cell=` / `orderbook_depth_usdc=` / `spread=` kwargs). Consequence today: `live_size_cap_for_cell(None)` returns None (`slippage_gate.py:108-111`) so the per-cell size cap does NOT bind; `_depth` falls back to `market_liquidity` and `_spread` to 1.0 (`gate.py:711-716`). The tier gate still runs on edge/size; only the per-cell $ caps are dormant until the cell is threaded.
- Status: tier-gate wiring + btc/eth/5m cap table = VERIFIED-READY; per-cell cap binding = OPEN -> in-progress (parallel lane). sol/5m cap not yet in the table.

### 8. Redeem / CTF settlement (binary up/down resolution) — VERIFIED-READY

- LIVE on-chain redeem: `services/redeem/redeem_router.py:429` `ensure_live_redemption()` -> `polymarket.submit_live_redemption(cond)` (`redeem_router.py:464`) = real `CTF.redeemPositions()` tx.
- Called for winning LIVE positions: `redeem_router.py:321-324` (`if p["mode"] == "live": await ensure_live_redemption(...)`), inside `settle_winning_position` (`redeem_router.py:281`).
- Idempotent on-chain: deduped by `live_redemptions.condition_id` unique constraint (`redeem_router.py:451-456, 466-471`); gated on EXECUTION_PATH_VALIDATED (`redeem_router.py:458`, deferred when off).
- Resolution detection + winner-enqueue / loser-settle: `detect_resolutions` (`redeem_router.py:48`), instant vs hourly worker (`services/redeem/instant_worker.py`, gas-guard for live `instant_worker.py:79-92`).
- WATCH (non-blocking): on-chain redeem failure is caught and the INTERNAL ledger credit still posts (`redeem_router.py:322-326`). The user is made whole internally against the master pool; the on-chain tx can lag/retry. Acceptable for v1 but operator must monitor `live_redemptions` vs settled wins for chain-side drift.

### 9. Auto-fallback / no silent downgrade — VERIFIED-READY

- LivePostSubmitError -> re-raise, NO paper-duplicate; flips user to paper for next signal: `router.py:112-124` + `fallback.trigger_for_clob_error`.
- LivePreSubmitError -> distinguishes INFRA-DEGRADED vs DELIBERATE: `router.py:125-174`; infra-degraded path = CRITICAL log + audit `live_infra_degraded_paper_fallback` + operator page (`router.py:130-151`); fragments matched defensively (`router.py:38-50`).
- Fallback module: `domain/execution/fallback.py:74` `trigger()` flips user_settings.trading_mode -> paper, idempotent, audited/notified.
- No silent live->paper downgrade: every fallback emits an audit row and infra-degraded pages the operator. VERIFIED.

### 10. Capital / wallet prerequisites — OWNER-GATED

- On-chain capital paths are CODE-COMPLETE and SENTINEL-approved (withdrawals PR #1402 94/100, sweep PR #1403, redemption #1408), all triple-gated behind EXECUTION_PATH_VALIDATED (OFF).
- Operational prerequisites are NOT code and remain owner actions: fund master EOA with USDC.e (trading + withdrawals) + MATIC (gas + sweep top-ups); set POLYMARKET secrets; master-EOA nonce lock + gas ceiling configured live. (WARP-74 Lane 5 live-path-hardening; LIVE_READINESS.md "Final go-live sequence".)
- Status: OWNER-GATED. No code gap.

---

## CRITICAL / OPEN ITEMS

- CRITICAL: NONE found in the candle_auto LIVE code path. GAP A (strategy_metadata persist) is CLOSED.
- OPEN (engineering, in-progress parallel lane): per-cell LIVE size caps do not bind — `cell` / `orderbook_depth_usdc` / `spread` not threaded from the candidate site into GateContext (`gate.py:88-90` defaults None; `engine.py:303-334` omits them). Fixed in `WARP/smart-strike-cell-cap-binding`. Until merged, btc/eth $ caps are dormant (tier gate still active).
- OPEN (engineering, minor): sol/5m has no entry in `LIVE_SIZE_CAPS_USDC` (`slippage_gate.py:56-59`) — if SOL is in LIVE v1 scope, add the cap (pending owner confirm of sol cap value).
- WATCH (operational, not a blocker): on-chain redeem failure soft-falls to internal credit (`redeem_router.py:322-326`); monitor `live_redemptions` for chain-side drift.

---

## GO-LIVE CHECKLIST

### ENGINEERING (code)

- [ ] Merge `WARP/smart-strike-cell-cap-binding` — thread `cell` + `orderbook_depth_usdc` + `spread` into GateContext at the candle_auto candidate site so per-cell LIVE size caps actually bind (currently dormant).
- [ ] Add sol/5m to `LIVE_SIZE_CAPS_USDC` IF SOL is in LIVE v1 scope (owner to confirm cap value).
- [x] live.py persists strategy_metadata (GAP A closed) — verified live.py:338/346.
- [x] LIVE force-exit fires via mode-agnostic loader — verified registry.py:164/235 + exit_watcher.py:202-211.
- [x] Reconcile + kill-switch broker cancel-all on main — verified reconcile.py / kill_switch_exec.py.
- [x] Guard chain (env 5 + USE_REAL_CLOB + role + mode + WARP-92 global) composes as hard AND -> paper — verified router.py / gate.py / live_activation.py.
- [x] Slippage TIER gate wired LIVE-only (step 14b) — verified gate.py:706-735.
- [x] On-chain CTF redeem path — verified redeem_router.py:429/464.
- [x] No-silent-downgrade fallback + infra-degraded paging — verified router.py:112-174 / fallback.py.

### OWNER-GATED (operational)

- [ ] Fund master wallet: USDC.e (trading + withdrawals) + MATIC (gas + sweep top-ups).
- [ ] Set POLYMARKET secrets (API creds / signing key) in Fly secrets.
- [ ] Configure master-EOA nonce lock + gas ceiling for live.
- [ ] Push the HELD `go-live-guards` change (fly.toml): flip the 5 validation guards (ENABLE_LIVE_TRADING, EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, RISK_CONTROLS_VALIDATED, SECURITY_HARDENING_VALIDATED) + USE_REAL_CLOB. (WORKTODO: committed local, NOT pushed.)
- [ ] Flip the WARP-92 `global_live_trading_enabled` admin toggle (PATCH /admin/settings/live-trading) — defaults false; fail-safe to paper.
- [ ] First user `/live/enable` with an explicit capital cap (typed confirm; 0 < cap <= 10000 USDC); 8-gate live_checklist must pass.

### DECISIONS (WARP🔹CMD)

- [ ] LIVE v1 scope = BTC + ETH + SOL 5m. Confirm SOL inclusion; if yes, set its per-cell cap.
- [ ] Per-cell caps: btc/5m $500, eth/5m $100 (locked WARP-87); sol/5m PENDING owner confirm.
- [ ] First-user capital cap size.
- [ ] Go-live trigger criteria.
- [ ] Whether a realized-EV confidence read is required first. NOTE: paper read on user qwneer8 shows flip_hunter net +EV, asymmetric ~3:1 — but it is 1 user / 1 day; NOT a statistically sufficient cutover signal. WARP-72 Phase 4 scorer cutover is PARKED (scorer net-negative EV on holdout); the router selection logic is what ships, not the scorer.

---

## RECOMMENDED SEQUENCE

1. Merge `WARP/smart-strike-cell-cap-binding` (per-cell cap binding) — engineering close.
2. CMD decide SOL v1 scope; if in, add sol/5m cap; confirm first-user cap + go-live trigger.
3. Owner: fund master wallet (USDC.e + MATIC), set POLYMARKET secrets, configure nonce lock + gas ceiling.
4. Owner: push the HELD go-live-guards (5 flags + USE_REAL_CLOB).
5. Owner: flip WARP-92 `global_live_trading_enabled` admin toggle.
6. First user `/live/enable` with a small cap; pass 8-gate checklist + typed confirm.
7. Monitor: reconcile sweep (orphan/drift pages), live_redemptions drift, infra-degraded pages, slippage WATCH breadcrumbs. Kill-switch tested reachable.

---

## GO-LIVE STATUS / VERDICT

VERDICT: READY-PENDING-OWNER.

The candle_auto -> late_entry_v3 LIVE code path is engineering-ready with ONE open item: per-cell LIVE size caps are wired but DORMANT until the cell/depth/spread fields are threaded into GateContext (in-progress parallel lane `WARP/smart-strike-cell-cap-binding`). The tier slippage gate, real CLOB entry/exit, strategy_metadata persistence (GAP A closed), LIVE force-exit, broker-truth reconcile, kill-switch broker cancel-all, the hard-AND guard chain + WARP-92 global toggle, per-user opt-in + 8-gate checklist, on-chain CTF redeem, and no-silent-downgrade fallback are all VERIFIED-READY against code. No CRITICAL issues in scope. Remaining blockers are OWNER-GATED operational (fund wallet, secrets, flip held guards + global toggle, first /live/enable) and the cap-binding merge. Do NOT flip live until the cap-binding lane lands AND the owner sequence completes.
