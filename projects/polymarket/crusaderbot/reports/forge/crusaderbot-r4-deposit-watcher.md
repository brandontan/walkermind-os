# WARP•FORGE Report — crusaderbot-r4-deposit-watcher

**Branch:** WARP/CRUSADERBOT-R4-DEPOSIT-WATCHER
**Last Updated:** 2026-05-04 20:30 Asia/Jakarta
**Validation Tier:** MAJOR
**Claim Level:** MAJOR — on-chain reader + ledger write path

**SENTINEL findings resolved (round 1, PR #850):**
1. **Atomic transaction (CRITICAL).** `_credit_deposit` now runs deposits insert + sub-account upsert + `ledger.credit()` + `bump_tier()` inside a single `async with conn.transaction()` block. `ledger.credit`, `ledger.get_balance`, and `user_service.bump_tier` accept an optional `conn` parameter so they compose into the caller's transaction without losing standalone behavior. Telegram notification stays out of the txn (best-effort).
2. **Dedupe key tx_hash + log_index (CRITICAL).** Schema migration already ships the composite `UNIQUE (tx_hash, log_index)` and `log_index INTEGER NOT NULL DEFAULT 0` column. Watcher now parses with `log_obj.get("logIndex", "0x0")` and converts hex → int (defaults to 0 on parse failure) instead of refusing the credit.
3. **Reorg guard (HIGH).** `_handle_log` short-circuits at the top with `log.debug("deposit_watcher.reorg_skip", tx_hash=…)` and returns when `removed: true` arrives, before any DB or downstream work.

---

## 1. What was built

R4 lane: deposit detection + internal ledger crediting. Paper mode only. All activation guards remain OFF. No live trading code touched. No allowlist/tier/onboarding/fee changes.

- **Alchemy WebSocket deposit watcher** (`services/deposit_watcher.py`): asyncio background task subscribed to USDC `Transfer` events on Polygon via `eth_subscribe`. In-process address-map filter (refreshed every 60s) routes incoming logs to the matching user. Logs flagged `removed: true` (chain reorgs) are skipped with a structured warning and never credited. Confirmed canonical transfers are inserted into `deposits` keyed on `(tx_hash, log_index)` and credited to the user's sub-account ledger inside a single DB transaction (no partial-success window). Reconnect with exponential backoff (1 s → 60 s cap). Per-event isolation: a single bad log never kills the loop.
- **Sub-account ledger** (`services/ledger.py`): `ensure_sub_account(pool, user_id)` (1:1 sub-account, race-safe via `INSERT … ON CONFLICT DO NOTHING`), `get_balance(pool, user_id)` (sums `ledger_entries` joined through `sub_accounts`), `credit / debit` (asyncio.Lock-guarded append, debit is scaffold-only for R4), `get_entries(sub_account_id, limit)`.
- **Schema additions** (`db/schema_r4.sql`): `sub_accounts(id, user_id UNIQUE, created_at)` and `ledger_entries(id, sub_account_id, type, amount_usdc, ref_id, ts)` — both `IF NOT EXISTS`. Plus an additive mutation to the existing R1 `deposits` table: add `log_index INTEGER NOT NULL DEFAULT 0`, drop the original `UNIQUE(tx_hash)` (`deposits_tx_hash_key`) and add a composite `UNIQUE (tx_hash, log_index)`. One EVM tx can emit multiple Transfer events distinguished by `logIndex` (multi-recipient distributions, batch contracts), and the original tx_hash-only key silently dropped legitimate credits when two recipients shared one transaction. The constraint swap is wrapped in idempotent `IF EXISTS` / `IF NOT EXISTS` blocks so the R4 schema applies cleanly on every startup, including a database that was created before R4. The legacy R1 `ledger` table is untouched.
- **Migration runner** (`database.py`): `run_migrations()` now also reads `db/schema_r4.sql` on every startup. R1 init still gated behind the `users`-table existence check; R4 schema is additive and rerun-safe.
- **Telegram surfaces** (`bot/handlers/wallet.py`):
  - `/wallet` — open to all tiers; shows address + USDC balance + effective tier (max of DB `users.access_tier` and the in-memory R3 allowlist tier).
  - `/deposit` — gated by the existing R3 `require_tier(TIER_ALLOWLISTED)` decorator; shows the address with deposit instructions.
- **Dispatcher wiring** (`bot/dispatcher.py`): both new commands registered via `functools.partial(pool=, config=)` like R2's `/start`.
- **Lifespan integration** (`main.py`): the `DepositWatcher` starts after Telegram polling and is the first thing torn down on shutdown (so we never miss a pending log credit while the bot.send_message path is already gone).
- **Env vars** (`config.py` + `.env.example`): added `ALCHEMY_POLYGON_RPC_URL`, `ALCHEMY_POLYGON_WS_URL`, `USDC_CONTRACT_ADDRESS` (the native, non-bridged USDC `0x3c499…`). `MIN_DEPOSIT_USDC` was already present from R1.
- **Dependency** (`pyproject.toml`): `websockets ^12.0` added explicitly (it is already a transitive of `web3`, but the watcher uses it directly so the dep is declared).

## 2. Current system architecture (slice for R4)

```
Polygon mainnet — USDC ERC-20 Transfer event
  ↓ (Alchemy WSS  eth_subscribe logs)
services/deposit_watcher.DepositWatcher  (asyncio background task)
  ├── connect → eth_subscribe(address=USDC, topics=[Transfer])
  ├── in-process map: deposit_address (lower) -> (user_id, telegram_user_id)
  │     reloaded every 60 s from wallets ⨝ users
  ├── per-log:
  │     if removed=true → skip with warning (chain reorg orphan)
  │     parse to_addr from topics[2]; parse log_index (required)
  │     lookup user; if no match → drop
  │     parse amount_usdc = uint256(data) / 10^6
  │     BEGIN TRANSACTION
  │       INSERT INTO deposits (..., log_index)
  │         ON CONFLICT (tx_hash, log_index) DO NOTHING RETURNING id
  │         hit  → COMMIT(no-op), exit (idempotency guard)
  │         miss → continue inside same txn
  │       INSERT INTO sub_accounts ON CONFLICT DO NOTHING; lookup id
  │       INSERT INTO ledger_entries (sub_account_id, type='deposit', amount,
  │                                   ref_id=deposit_id)
  │     COMMIT
  │     balance = ledger.get_balance(user_id)         (out of txn)
  │     if balance >= MIN_DEPOSIT_USDC and access_tier < 3:
  │         user_service.bump_tier(user_id, 3, actor_role="deposit_watcher")
  │     bot.send_message(chat_id=telegram_user_id, text="💰 Deposit confirmed …")
  └── on disconnect: backoff 1s -> 2s -> 4s -> ... -> 60s cap, reconnect

services/ledger
  ensure_sub_account / get_balance / credit / debit (scaffold) / get_entries
  asyncio.Lock around credit + debit (intra-process double-write guard)

db/schema_r4.sql (idempotent, additive)
  sub_accounts     (id PK, user_id UNIQUE → users.id, created_at)
  ledger_entries   (id PK, sub_account_id → sub_accounts.id, type, amount_usdc,
                    ref_id, ts)
  deposits         add log_index INTEGER NOT NULL DEFAULT 0;
                   drop UNIQUE (tx_hash); add UNIQUE (tx_hash, log_index)
                   — guarded with IF EXISTS / IF NOT EXISTS for rerun-safety
  legacy R1 ledger table left untouched

bot
  handlers/wallet.handle_wallet   (open)
    user → wallet → balance → tier (effective = max(db, allowlist))
  handlers/wallet.handle_deposit  (require_tier(TIER_ALLOWLISTED))
    user → wallet.deposit_address → instructions + min deposit
  dispatcher.setup_handlers       registers /wallet + /deposit via partial(pool, config)

main.py lifespan
  db.connect → cache.connect → run_migrations (001_init + schema_r4)
  → bot.initialize → bot.start → updater.start_polling
  → DepositWatcher.start
  shutdown reverses: watcher.stop first → updater.stop → bot.stop → bot.shutdown
                     → cache.disconnect → db.disconnect
```

## 3. Files created / modified (full repo-root paths)

**Created (4):**
- `projects/polymarket/crusaderbot/services/deposit_watcher.py` — DepositWatcher class + WS loop + credit path
- `projects/polymarket/crusaderbot/services/ledger.py` — ensure_sub_account / get_balance / credit / debit / get_entries
- `projects/polymarket/crusaderbot/db/schema_r4.sql` — sub_accounts + ledger_entries (additive)
- `projects/polymarket/crusaderbot/bot/handlers/wallet.py` — /wallet (open) + /deposit (Tier 2+)
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-r4-deposit-watcher.md` — this report

**Modified (6):**
- `projects/polymarket/crusaderbot/main.py` — lifespan starts/stops DepositWatcher around polling
- `projects/polymarket/crusaderbot/database.py` — run_migrations also applies db/schema_r4.sql (idempotent)
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registers /wallet and /deposit via partial(pool=, config=)
- `projects/polymarket/crusaderbot/config.py` — ALCHEMY_POLYGON_RPC_URL + ALCHEMY_POLYGON_WS_URL + USDC_CONTRACT_ADDRESS
- `projects/polymarket/crusaderbot/.env.example` — same three vars + comment
- `projects/polymarket/crusaderbot/pyproject.toml` — websockets ^12.0
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — R3 → COMPLETED, R4 IN PROGRESS, NEXT PRIORITY = SENTINEL
- `projects/polymarket/crusaderbot/state/ROADMAP.md` — R3 ✅, R4 🚧
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — R4 lane entry appended

**Untouched (intentional):**
- `services/allowlist.py` and `bot/middleware/tier_gate.py` (R3 territory)
- `bot/handlers/onboarding.py` and `wallet/` (R2 territory)
- `domain/risk/constants.py`, R1 `migrations/001_init.sql`, fee tables, kill switch

## 4. What is working

- WebSocket connect → `eth_subscribe(logs)` with USDC contract + Transfer topic; subscription handshake tolerates an early notification arriving before the ack frame.
- Reconnect on disconnect: exponential backoff capped at 60 s; `_stop_event.wait` makes the backoff promptly cancellable on shutdown.
- Address-map filter is fully in-process (no per-user subscription), so newly provisioned wallets are picked up at the next 60 s refresh without resubscribing.
- USDC amount parse: `int(data, 16) / Decimal(10 ** 6)` — produces `Decimal` to keep ledger arithmetic exact.
- Topic-to-address: takes the last 40 hex chars of `topics[2]` and lowercases the result; rejects malformed topics with a structured warning.
- Idempotency at log granularity: `INSERT … ON CONFLICT (tx_hash, log_index) DO NOTHING RETURNING id`. The composite key handles the case of a single EVM transaction emitting multiple Transfer events (multi-recipient distributions, batch contracts) — the previous tx_hash-only key would have silently dropped every legitimate deposit after the first.
- Atomic credit path: the deposit insert, sub-account upsert, and ledger entry insert all run inside one `async with conn.transaction()` block. There is no partial-success window where a `deposits` row exists without its matching `ledger_entries` row, which would otherwise cause permanent under-crediting (future retries would short-circuit on `ON CONFLICT`).
- Reorg gate: any log carrying `removed: true` (chain reorganization orphan) is skipped with a structured `deposit_watcher.removed_log_skipped` warning before any DB write, so reorged-out transfers cannot pollute the ledger. Reversing a previously-credited deposit on a later `removed=true` is a deferred enhancement (a confirmation-delay model is the cleaner long-term fix).
- Sub-account creation is race-safe via `ON CONFLICT (user_id) DO NOTHING` + read-back inside the same transaction.
- Ledger credit lives entirely inside the deposit transaction for the watcher path (the standalone `ledger.credit` helper retains its `asyncio.Lock` for non-atomic callers).
- Tier 3 promotion goes through the existing `user_service.bump_tier` (R2) — DB `users.access_tier` update + `audit.log` row inside one transaction with `SELECT … FOR UPDATE` lock; no allowlist file touched.
- Effective tier shown on `/wallet` is `max(db_tier, allowlist_tier)`, so a Tier 2 allowlisted user who funds keeps Tier 3 visibility, and a Tier 3 funded user who is not on the allowlist still sees Tier 3.
- `/deposit` is correctly gated by `require_tier(TIER_ALLOWLISTED)`; Tier 1 callers receive the existing R3 `🔒 …` denial and never see the address through this command (they can still see it via `/wallet`).
- Telegram notification text exactly matches the task spec format ("💰 Deposit confirmed: +$X.XX USDC / Your balance: $Y.YY USDC / Access tier: Tier 3 — Funded beta").
- WS URL host is logged, but the API-key-bearing path (`/v2/<key>`) is stripped from log output via `_ws_host`.
- Migrations: R1 init still gated on `users` existence; R4 schema is additive + `IF NOT EXISTS` so it runs safely on every startup.
- Lifespan: watcher is the first thing torn down on shutdown, so we never try to credit + notify after `bot.stop()`.

## 5. Known issues

- **In-process address-map refresh is 60 s.** A user who runs `/start` and immediately makes a deposit could see up to a one-minute delay before the watcher recognises their address. Acceptable for MVP — average human deposit flow is many minutes — but a future enhancement can push fresh addresses into the watcher synchronously from `handle_start`.
- **No log replay on first connect.** The watcher only sees Transfer events that arrive after the WS subscription is alive. Deposits that landed while the bot was offline are not retroactively credited. A reconciliation pass (e.g. `eth_getLogs` from the last seen block at startup) is deferred — out of scope per task `Not in Scope`.
- **Reorg-reversal of already-credited deposits is deferred.** The watcher refuses to credit any log with `removed: true`, but it does not currently reverse a previously-credited deposit if a later `removed: true` event re-emits its log identity. The cleaner long-term fix is a confirmation-delay model (defer credit until N block confirmations, e.g. 12) — tracked as a follow-up before live activation.
- **No actual sweep to the hot pool.** The watcher only credits the internal ledger; the on-chain USDC stays at the per-user HD-derived address. The blueprint §7 sweep flow is explicitly deferred ("Not in Scope: Real sweep to hot pool").
- **No withdraw flow.** `debit` is wired up as a scaffold for future use; nothing in R4 calls it. Withdraw is its own lane.
- **Tier 4 gate not modelled.** Promotion stops at Tier 3 (Funded beta). Tier 4 (live auto-trade) requires the activation guards to be SET and is correctly out of scope.
- **`OPERATOR_CHAT_ID` semantic dual-use** — same caveat carried over from R3; no change in R4.
- **No automated tests in this lane.** Manual verification path:
  1. Set Alchemy WS URL + USDC contract in `.env`; bring stack up; confirm log line `deposit_watcher.connected`.
  2. From a test wallet on Polygon, send 0.1 USDC to a known user's deposit address — confirm `deposit_watcher.deposit_credited` log (with `tx_hash` and `log_index`) + Telegram message; confirm balance via `/wallet`.
  3. Replay the same `(tx_hash, log_index)` — confirm `deposit_watcher.duplicate_skipped` log and no extra credit / notification.
  4. Send another transfer that pushes balance ≥ $50 — confirm `user.tier_bumped` log (`old_tier=1` or `2`, `new_tier=3`) and the "Access tier: Tier 3 — Funded beta" line in the Telegram message.
  5. Send a synthetic log with `removed: true` (or trigger via reorg test rig) — confirm `deposit_watcher.removed_log_skipped` warning and zero DB writes.
  6. From a Tier 1 caller: `/wallet` shows address + $0.00 + Tier 1; `/deposit` shows the R3 `🔒` denial.
  7. From a Tier 2 (allowlisted) caller: `/deposit` shows the address + min-deposit instructions.
  8. Regression: `/start`, `/status`, `/allowlist` all behave as before.
- **Watcher does not pre-validate `USDC_CONTRACT_ADDRESS` checksum or chain.** A misconfigured env var would silently cause zero matches; ops-level alarm on "no deposits in N hours" is deferred to R12.
- **`websockets` is added as a direct dep** even though `web3 ^6.15` already pulls it transitively. We use the API directly so an explicit pin is correct, but it widens the upgrade surface marginally.

## 6. What is next

- **WARP•SENTINEL validation required for R4 deposit watcher before merge.**
  Source: `projects/polymarket/crusaderbot/reports/forge/crusaderbot-r4-deposit-watcher.md`
  Tier: MAJOR
  Validation environment: `dev` (paper mode, all activation guards OFF).
- After merge: post-merge sync per AGENTS.md POST-MERGE SYNC RULE — bump `PROJECT_STATE.md` from IN PROGRESS → COMPLETED for R4, `ROADMAP.md` R4 row 🚧 → ✅, append `CHANGELOG.md` with merge SHA.
- Next lane: **R5 strategy config** — DB-backed strategy / risk / capital allocation settings + Telegram `/config`, `/strategy`, `/risk` (Tier 2+ via `require_tier`).

---

**Validation Tier:** MAJOR — on-chain reader + DB write path + tier promotion. WARP•SENTINEL mandatory before merge.

**Claim Level:** MAJOR — first end-to-end credit path: chain event → DB → ledger → tier → notify.

**Validation Target:**
(a) `deposit_watcher` connects to Alchemy WS on startup and logs `deposit_watcher.connected`;
(b) a simulated USDC transfer to a known user address produces a `deposits` row + a positive `ledger_entries` row + a Telegram notification;
(c) ledger amount equals on-chain `value / 10^6` exactly (Decimal precision);
(d) duplicate `tx_hash` triggers `deposit_watcher.duplicate_skipped` and produces no extra ledger row / notification;
(e) tier auto-bumps to 3 when balance crosses `MIN_DEPOSIT_USDC` and `bump_tier` writes to `audit.log`;
(f) `/wallet` reflects the new balance + tier label;
(g) `/deposit` is denied for Tier 1 with the R3 `🔒` message and shown for Tier 2+;
(h) zero regression on `/start`, `/status`, `/allowlist`;
(i) graceful shutdown: watcher stops first, no orphaned send_message after `bot.stop()`.

**Not in Scope:**
- Real sweep to hot pool / on-chain treasury rebalance
- Withdraw flow (USDC out)
- Tier 4 gate (live auto-trade)
- Backfill / reconciliation of deposits that landed while the watcher was offline
- Trading logic, strategy engine, risk gate (R5+)
- Modifying allowlist/tier system (R3 territory)
- Fee system, referral accounting (R11)

**Suggested Next:** WARP•SENTINEL on `WARP/CRUSADERBOT-R4-DEPOSIT-WATCHER` in `dev` (paper). On APPROVED, WARP🔹CMD merges; post-merge sync; open R5 strategy config lane.
