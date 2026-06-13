# WARP•R00T — polymarket-bridge-native-enablement-blocker (#1805)

Branch: `WARP/root-bridge-native-deposit-safe-groundwork`
Issue: #1805
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Role: WARP•R00T (root-cause + safe groundwork; owner-directed outcome)
Date: 2026-06-13 08:32 Asia/Jakarta

Owner decision (2026-06-13): **"Document precise blocker + safe groundwork."** Keep native Polygon USDC + USDT DISABLED for crediting (no fake-enablement); land a safe, non-crediting Bridge status poller + an honest user notification; write this precise blocker.

Validation Target: Bridge/pUSD deposit detection + operator visibility + web notification groundwork, with native USDC/USDT crediting kept DISABLED behind a documented precondition chain.

Not in Scope: crediting native USDC/USDT as tradeable balance, sweep/custody changes, strategy/risk/order changes, live-guard flips, real fund movement, live external Bridge calls (poller is OFF by default).

---

## 1. The precise blocker (why native USDC/USDT cannot be safely credited today)

Polymarket Bridge settles native USDC / USDT into **pUSD** credited to a Polymarket wallet (`/deposit` → `/status` `COMPLETED`, `toToken = pUSD` on Polygon 137). The bot's capital accounting and live execution are **USDC.e-bound**, with no pUSD path. Crediting a pUSD settlement as spendable balance would credit money the live path cannot reliably spend — unsafe fake-enablement, which #1805 explicitly forbids. Evidence (code-truth):

1. **Live order funding debits the DB ledger, not on-chain pUSD.** `domain/execution/live.py` opens a position by `ledger.debit_in_conn(..., T_TRADE_OPEN)` against the per-user DB ledger — it never reads on-chain pUSD/USDC balance.
2. **`get_live_balance` counts only USDC.e `deposits`-table rows.** `wallet/ledger.py` `_LIVE_LEDGER_FILTER_SQL` sums `type='deposit'` rows that have a matching `deposits` row (on-chain USDC.e transfers), withdrawals, refunds, and live-position rows. A Bridge pUSD settlement has no `deposits` row, so it is invisible to the $5 live Auto-Trade gate and to order sizing.
3. **Custody sweep is USDC.e-contract-bound.** `integrations/polygon_usdc.py` `sweep_usdc_to_master` transfers the USDC.e ERC-20 from the user deposit address to the master wallet. It cannot move pUSD, and there is no pUSD→USDC.e onramp/offramp wired into custody.
4. **pUSD is documentation-only in runtime.** Grep of the project: `pUSD` appears only in the Bridge adapter, config constant (`PUSD_POLYGON`), the disabled deposit-asset definition, `.env.example`, tests, and docs/reports. **No runtime code holds, wraps, unwraps, sweeps, or spends pUSD.**
5. **Default execution is master/USDC.e, not per-user deposit-wallet.** `USE_PER_USER_EXECUTION` is off by default; the live path funds from the master wallet's swept USDC.e. The per-user deposit-wallet model (signatureType=3 / POLY_1271) *could* in principle hold spendable pUSD, but that mode is not the active live path, and the DB accounting above still would not credit it.

**Conclusion:** the blocker is not a single line — it is an architecture chain. For native USDC/USDT to be safely creditable, ALL of the following must first be true (none are today):

- (a) the live order path funds from the same wallet/collateral the Bridge pUSD settlement lands in (commit to per-user deposit-wallet execution as the live path, OR add a proven pUSD→USDC.e onramp into custody);
- (b) accounting credits ONLY terminal `COMPLETED` pUSD settlements, exactly once, with reorg/failure/manual-review handling, into a balance the live path actually spends;
- (c) the $5 live Auto-Trade gate + order sizing read that same settled, spendable balance;
- (d) the go-live sequence (per-user execution flip, `USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED`) is owner-decided.

These are owner go-live decisions, so native enablement stays a documented blocker until they are made.

## 2. Safe groundwork built (no crediting, OFF by default)

A Bridge deposit STATUS poller that observes terminal settlements and gives operators an auditable queue + the user an honest notification, while NEVER crediting balance:

- `services/bridge/status_poller.py` — `run_once()`:
  - dormant unless `BRIDGE_DEPOSIT_POLLER_ENABLED` (default **False**) — makes **no** live Bridge call while OFF;
  - loads each user's persisted `bridge_deposit_addresses.evm_address`;
  - reads terminal `COMPLETED` pUSD settlements via the existing adapter (`polymarket_bridge.get_status` + `completed_pusd_settlements`), fail-closed per user on Bridge outage;
  - persists each (idempotently, via the `uq_bridge_deposit_events_tx_hash` unique index) to `bridge_deposit_events` with status `MANUAL_REVIEW`, `credited_deposit_id = NULL`, `manual_review_reason` set, raw Bridge `COMPLETED` payload preserved;
  - emits exactly one **honest, deduped** web notification (`alert_kind="bridge_deposit_received"`, `dedup_key="bridge:<tx>:received"`) telling the user the deposit was received but is **"pending review and NOT yet available for trading."**
- `config.py` + `.env.example` — `BRIDGE_DEPOSIT_POLLER_ENABLED=false`, `BRIDGE_DEPOSIT_POLL_INTERVAL_SECONDS=180`.
- `scheduler.py` — registers `bridge_deposit_status_poll` ONLY under the flag (idiomatic, mirrors `COMPLETE_SET_ARB_ENABLED` / `LIVE_RECONCILE_ENABLED`).

Hard invariants (pinned by tests): no write to `deposits`/`ledger`/`wallets`; `get_live_balance` untouched; no sweep/order/guard read or flip; `credited_deposit_id` always NULL; idempotent replays.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/services/bridge/__init__.py` (new)
- `projects/polymarket/crusaderbot/services/bridge/status_poller.py` (new)
- `projects/polymarket/crusaderbot/tests/test_bridge_status_poller.py` (new — 9 behaviour/safety tests)
- `projects/polymarket/crusaderbot/config.py` (poller flag + interval)
- `projects/polymarket/crusaderbot/.env.example` (flag, OFF, documented)
- `projects/polymarket/crusaderbot/scheduler.py` (flag-gated job registration)
- `projects/polymarket/crusaderbot/reports/forge/polymarket-bridge-native-enablement-blocker.md` (this report)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md`

Deposit-asset matrix (`wallet/deposit_assets.py`) is **unchanged** — native USDC/USDT stay `enabled=False` / `creditable=False`; USDC.e remains the only enabled deposit asset. Frontend deposit selector keeps the honest "unavailable" state (no change).

## 4. Validation

- New `test_bridge_status_poller.py` — 9 passed: dormant-when-off (no Bridge call), COMPLETED pUSD → manual review + honest non-crediting notification, idempotent replay (no double-notify), non-COMPLETED/non-pUSD ignored, no-tx_hash skipped, per-user fail-closed on Bridge outage, source-pin that the poller never credits/sweeps/imports ledger, scheduler flag-gated registration, native USDC/USDT remain disabled.
- Full suite: `pytest projects/polymarket/crusaderbot/tests/` → 3646 passed, 15 skipped.
- `ruff` + `py_compile` clean; secret / mojibake / BOM scans clean.

## 5. Safety invariant statement

No native USDC/USDT crediting; no `deposits`/`ledger`/`wallets` write; `get_live_balance`, the $5 live Auto-Trade gate, and order sizing untouched. No sweep, no order, no real fund movement. No live external Bridge call (poller OFF by default). No live-guard flip (`USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` untouched). Kelly 0.25, asyncio only, no hardcoded secrets, no `phase*/` folders.

## 6. What is next

WARP🔹CMD first-pass; merge under WARP•R00T final gate on CI green (safe groundwork + documented blocker; no capital path enabled). #1805 stays OPEN as the enablement lane — native USDC/USDT remain disabled until the owner decides the go-live precondition chain in §1 (per-user deposit-wallet execution OR pUSD↔USDC.e onramp + settled-balance accounting + go-live guard sequence). To activate the (still non-crediting) poller in production, flip `BRIDGE_DEPOSIT_POLLER_ENABLED=true`.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: Bridge status detection/visibility/notification groundwork; native crediting kept DISABLED behind a documented precondition chain.
Not in Scope: native USDC/USDT crediting, sweep/custody, live-guard flips, real fund movement.
Suggested Next Step: WARP🔹CMD first-pass → R00T final-gate merge on CI green; native enablement deferred to the owner go-live decision.
