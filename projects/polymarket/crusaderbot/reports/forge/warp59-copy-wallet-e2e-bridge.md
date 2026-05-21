# WARP-59 — Copy Wallet end-to-end bridge: copy_targets → copy_trade_tasks

**Branch:** `WARP/warp59-copy-wallet-e2e-bridge`
**Issue:** #1265
**Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Generated:** 2026-05-21 18:25 Asia/Jakarta

---

## 1. What was built

Realigned the MVP Telegram copy-wallet handler so its writes land in the same table the production execution scanner reads. Wallets added via the MVP UX now flow end-to-end through the existing scanner without any view, trigger, or domain change.

Concretely, in `projects/polymarket/crusaderbot/bot/handlers/mvp/copy_wallet.py`:

- `_read_wallets` SELECT swapped from `copy_targets` to `copy_trade_tasks`. Display aliases preserved (`address`, `enabled`, `allocation`) so the keyboard / message renderers stay untouched.
- `do_start_copying` INSERT swapped from `copy_targets` to `copy_trade_tasks`. The MVP `allocation_usdc` value (default 100.0, drives the $25/$50/$100/$250/Custom buckets) maps to `copy_mode='fixed'` + `copy_amount=allocation_usdc`, which the execution scaler consumes directly at `services/copy_trade/scaler.py:mirror_size_direct`. `task_name` and `nickname` derive from the wallet short form (`MVP 0xab12...cdef`) so the row is visually identifiable in `/copytrade` lists.
- Manual upsert (SELECT → UPDATE / INSERT) replaces the previous PostgreSQL ON CONFLICT clause: `copy_trade_tasks` does not declare `UNIQUE (user_id, wallet_address)` (mig 018 only creates `idx_ctt_user (user_id)`), and adding that constraint would change semantics for the legacy `/copytrade` wizard which permits multiple tasks per leader wallet with different settings. The handler-level upsert preserves single-row-per-(user, wallet) for MVP without touching legacy behaviour.
- `do_pause` UPDATE swapped to `copy_trade_tasks` with the canonical `status='paused'` (was MVP-only `'inactive'`); scoped to `status='active'` so the no-op pause is cheap.

Chosen path: **Option B** from #1265 (align MVP write path to `copy_trade_tasks`).

Why not Option A (DB view / trigger): `copy_trade_tasks` carries fourteen execution-relevant columns (`tp_pct`, `sl_pct`, `max_daily_spend`, `slippage_pct`, `min_trade_size`, `reverse_copy`, `copy_direction`, `execution_mode`, `allow_topups`, `nickname`, …) that have no source in `copy_targets`. A bridging view would have to synthesise defaults at the DB layer, and a writable view would need an INSTEAD OF trigger that re-implements upsert semantics — opaque, doubly-booked truth.

Why not Option C (scanner reads `copy_targets`): would require a destructive refactor of `CopyTradeTask` + `services/copy_trade/monitor.py` + the entire execution scaler chain to operate on the sparse `copy_targets` schema. Out of scope for a STANDARD lane and bisects the legacy `/copytrade` wizard which already writes the rich schema.

Result: MVP UX wallet add → `copy_trade_tasks` INSERT → next scheduler tick of `copy_trade_monitor.run_once` (`scheduler.py:603-605`) picks the row up via `list_active_tasks()` → executes through the canonical TradeEngine path in paper mode. No activation guard, no execution engine, no scheduler change.

## 2. Current system architecture (relevant slice)

```
USER  (Telegram /start MVP)
  │
  ▼  bot/handlers/mvp/copy_wallet.py
       _read_wallets         (SELECT  copy_trade_tasks)   ← FIXED
       do_start_copying      (UPSERT copy_trade_tasks)    ← FIXED
       do_pause              (UPDATE copy_trade_tasks)    ← FIXED
  │
  ▼  PostgreSQL
       copy_trade_tasks (mig 018 + 035) — canonical execution schema
  │
  ▼  scheduler.py:603 — COPY_TRADE_MONITOR_INTERVAL tick
       services/copy_trade/monitor.py:80
         └─ domain/copy_trade/repository.list_active_tasks()
              SELECT * FROM copy_trade_tasks WHERE status='active'
  │
  ▼  per-task processing (services/copy_trade/monitor.py)
       fetch_recent_wallet_trades → idempotency check
         → scaler.mirror_size_direct (copy_mode='fixed') / scale_size
         → TradeEngine.execute(signal)   [PAPER ONLY — guard untouched]
         → copy_trade_idempotency persisted
```

Legacy `/copytrade` 8-step wizard (`bot/handlers/setup.py` + `bot/handlers/copy_trade.py`) continues to write `copy_trade_tasks` with full per-task settings — unchanged. The MVP handler is now a second, narrower writer onto the same table.

`copy_targets` (mig 009) is unchanged; nothing in the MVP handler reads or writes it anymore. The WARP-58 fix on `domain/signal/copy_trade.py` (legacy SignalCandidate scanner that reads `copy_targets`) remains valid and still services any user with `auto_trade_on=TRUE` + `'copy_trade' in strategy_types` — it just no longer receives rows from the MVP path. This is the explicit MEDIUM-4 outcome flagged by WARP-57 SENTINEL: MVP joins the production execution path; `copy_targets` returns to being the legacy compatibility table.

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/bot/handlers/mvp/copy_wallet.py` — SELECT/INSERT/UPDATE swap, manual upsert, mapping `allocation_usdc → copy_amount` under `copy_mode='fixed'`, `do_pause` uses canonical `status='paused'`.

Created:
- `projects/polymarket/crusaderbot/tests/test_warp59_copy_wallet_bridge.py` — 6 hermetic tests covering INSERT path, UPDATE-on-duplicate path, pause path, _read_wallets path, end-to-end visibility to `list_active_tasks` via a shared fake pool, and a module-source guard that fails if any `copy_targets` reference reappears in the MVP handler.
- `projects/polymarket/crusaderbot/reports/forge/warp59-copy-wallet-e2e-bridge.md` (this file).

State updates:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — surgical: `Last Updated`, `Status`, `[IN PROGRESS]` (new WARP-59 entry), `[NEXT PRIORITY]` (WARP-59 review entry prepended).
- `projects/polymarket/crusaderbot/state/WORKTODO.md` — Active section: WARP-59 entry added above WARP-58.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — append-only: WARP-59 lane entry at top.

Not modified (explicitly out of scope per issue #1265 and per CLAUDE.md HARD RULES):
- `services/copy_trade/monitor.py` — production scanner already reads `copy_trade_tasks`; verified, no change needed.
- `domain/copy_trade/repository.py` — `list_active_tasks` already canonical; verified, no change needed.
- `scheduler.py` — strategy registry / `copy_trade_monitor` job wiring untouched.
- Activation guards, kill switch, execution engine, RISK layer.
- `migrations/` — no migration required; both tables already exist and the MVP rewrite uses only columns present in mig 018 + 035.
- `bot/handlers/setup.py`, `bot/handlers/copy_trade.py` — legacy `/copytrade` wizard untouched.
- `domain/signal/copy_trade.py` — WARP-58 fix preserved verbatim.

## 4. What is working

- `python -m py_compile projects/polymarket/crusaderbot/bot/handlers/mvp/copy_wallet.py` clean.
- `python -m py_compile projects/polymarket/crusaderbot/tests/test_warp59_copy_wallet_bridge.py` clean.
- `grep -n "copy_targets" projects/polymarket/crusaderbot/bot/handlers/mvp/copy_wallet.py` returns zero matches — every legacy table reference is gone from the MVP handler (the module-source test (`test_no_legacy_copy_targets_writes_remain`) pins this as a contract).
- `grep -n "copy_trade_tasks" projects/polymarket/crusaderbot/bot/handlers/mvp/copy_wallet.py` returns six SQL references (one SELECT in `_read_wallets`, one SELECT + one UPDATE + one INSERT in `do_start_copying`, one UPDATE in `do_pause`, and four log/comment lines) — every code path now agrees on the canonical table.
- Column mapping audited against `migrations/018_copy_trade_tasks.sql` + `035_copy_trade_extend.sql`: `wallet_address`, `task_name`, `status`, `copy_mode`, `copy_amount`, `nickname`, `copy_direction`, `execution_mode`, `allow_topups`, `updated_at` — all present, all NOT NULL defaults satisfied by the INSERT shape, all CHECK-equivalent enums respected (`status='active'/'paused'`, `copy_mode='fixed'`, `copy_direction='buys_only'`, `execution_mode='auto'`).
- End-to-end bridge proof: `test_bridge_end_to_end_visibility_to_list_active_tasks` runs the MVP `do_start_copying` against a recording fake pool, then runs `domain/copy_trade/repository.list_active_tasks` against the **same** pool and asserts the inserted row is materialised back as a `CopyTradeTask` with the expected wallet_address, status, copy_mode, and copy_amount.

## 5. Known issues

- pytest is not installed in this remote execution container (and neither are the runtime deps `telegram` / `asyncpg`), so the test arm of the STANDARD checklist could not be exercised here — same posture as WARP-58. The fix is a contained SQL-string + column-set change; py_compile + module-source contract + assertion design are the verification available in this environment. WARP🔹CMD should run `pytest projects/polymarket/crusaderbot/tests/test_warp59_copy_wallet_bridge.py projects/polymarket/crusaderbot/tests/test_copy_trade.py projects/polymarket/crusaderbot/tests/test_phase5e_copy_trade.py projects/polymarket/crusaderbot/tests/test_phase5f_copy_wizard.py` locally / in CI before merge.
- WARP-58 closure assumption (legacy SignalCandidate scanner against `copy_targets`) still holds, but is no longer fed by the MVP path. Any user who used the MVP UX before this lane shipped has a row sitting in `copy_targets` that the scheduler never picks up unless they also have `auto_trade_on=TRUE` and `'copy_trade'` in `strategy_types`. A one-shot data backfill (copy rows from `copy_targets` to `copy_trade_tasks` for affected users) is out of scope and should be sequenced by WARP🔹CMD if pre-MERGE MVP installs exist in production. Closed-beta state means this is likely zero rows in practice; verify against Supabase before redeploy.
- The MVP UI displays a single allocation value (`copy_amount` under `copy_mode='fixed'`); the rest of `copy_trade_tasks`' execution knobs (`tp_pct`, `sl_pct`, `max_daily_spend`, `slippage_pct`, `min_trade_size`, `reverse_copy`, `copy_direction`, `execution_mode`, `allow_topups`) default to the values defined in mig 018 + 035. If WARP🔹CMD wants the MVP UX to expose these later, the corresponding INSERT shape is the natural extension point — no schema change needed.

## 6. What is next

- WARP🔹CMD review of PR for `WARP/warp59-copy-wallet-e2e-bridge`.
- Run the hermetic test bundle locally / in CI to confirm green: the six new tests plus the existing copy-trade tests must all pass.
- Optional pre-deploy backfill in Supabase if pre-existing `copy_targets` rows from the MVP UX exist (closed-beta — likely empty).
- After merge: Fly.io redeploy so the running bot pod imports the realigned handler. `copy_trade_monitor.run_once` requires no restart for the scanner read path (it already reads `copy_trade_tasks`); only the handler write path needs the pod to refresh.
- Optional follow-up lane (NOT in this PR): retire `domain/signal/copy_trade.py` once WARP🔹CMD confirms no live user relies on the SignalCandidate-style legacy scanner. Until then both scanners coexist (per the WARP-26 advisory).

---

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : MVP copy-wallet add via Telegram writes to `copy_trade_tasks`; `list_active_tasks` returns the inserted row; pause writes `status='paused'`; zero `copy_targets` references remain in `bot/handlers/mvp/copy_wallet.py`.
Not in Scope      : live execution, strategy engine, RISK gate, activation guards, scheduler wiring, `domain/`/`services/` for copy-trade, `migrations/`, legacy `/copytrade` wizard, data backfill of pre-existing `copy_targets` rows.
Suggested Next    : WARP🔹CMD review + hermetic test run + Fly.io redeploy.
