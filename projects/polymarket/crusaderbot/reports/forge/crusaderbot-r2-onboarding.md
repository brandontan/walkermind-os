# WARP•FORGE Report — crusaderbot-r2-onboarding

**Branch:** WARP/crusaderbot-r2-onboarding
**Last Updated:** 2026-05-04 08:36 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** FOUNDATION

---

## 1. What was built

R2 onboarding lane: first user-facing surface that establishes a user record + per-user HD wallet on `/start`.

- HD address derivation via `eth_account` BIP44 path `m/44'/60'/0'/0/{hd_index}`
- Fernet at-rest encryption for derived private keys (key never logged, never returned)
- Monotonic `hd_index` allocation backed by `COALESCE(MAX(hd_index), -1) + 1`; DB `UNIQUE(hd_index)` enforces race-safety
- User upsert keyed on `telegram_user_id` (idempotent — second `/start` returns existing wallet, no re-provisioning)
- Audit-logged `bump_tier` primitive for future allowlist/admin transitions (R3+ consumer)

`/start` flow now wired via `partial(handle_start, pool=db.pool, config=settings)`:
1. `get_or_create_user(telegram_user_id, username)` — UPSERT with COALESCE username refresh
2. If user has no wallet: derive → encrypt → drop cleartext → store
3. If user has wallet: fetch existing address from `wallets` table
4. Reply with welcome + deposit address (markdown code block) + min deposit + `/menu` hint

Lane also performs post-merge sync from PR #847: `ROADMAP.md` R1 row → ✅ Done; `PROJECT_STATE.md` COMPLETED includes R1 skeleton merge.

## 2. Current system architecture (slice for R2)

```
Telegram /start
  ↓
bot/dispatcher.py  (CommandHandler("start", partial(handle_start, pool=, config=)))
  ↓
bot/handlers/onboarding.handle_start(update, context, *, pool, config)
  ├── services/user_service.get_or_create_user(pool, telegram_user_id, username)
  │     → users (INSERT ... ON CONFLICT DO UPDATE)
  ├── wallet/vault.get_wallet(pool, user_id)
  │     → SELECT ... FROM wallets WHERE user_id=$1
  └── if no wallet:
      ├── wallet/vault.get_next_hd_index(pool)
      │     → SELECT COALESCE(MAX(hd_index), -1) + 1 FROM wallets
      ├── wallet/generator.derive_address(WALLET_HD_SEED, hd_index)
      │     → BIP44 m/44'/60'/0'/0/{hd_index}  → (address, private_key_hex)
      ├── wallet/generator.encrypt_pk(private_key, WALLET_ENCRYPTION_KEY)
      │     → Fernet ciphertext (urlsafe base64)
      ├── [private_key reference dropped here — never logged, never returned]
      └── wallet/vault.store_wallet(pool, user_id, address, hd_index, encrypted)
            → INSERT INTO wallets (user_id, deposit_address, hd_index, encrypted_key)
  ↓
Telegram reply (Markdown):
  - 👋 Welcome + paper-mode disclaimer
  - 💳 deposit address in code-span (tap to copy)
  - min deposit USDC
  - /menu hint
```

`main.py` lifespan now passes `db.pool` and `settings` into `setup_handlers()`. `bump_tier` (consumed by R3) writes to the `audit.log` schema established in R1 migrations inside the same transaction as the `users` UPDATE, with a `SELECT ... FOR UPDATE` row lock.

## 3. Files created / modified (full repo-root paths)

**Created (8):**
- `projects/polymarket/crusaderbot/wallet/__init__.py` — package marker
- `projects/polymarket/crusaderbot/wallet/generator.py` — `derive_address` + `encrypt_pk` + `decrypt_pk`
- `projects/polymarket/crusaderbot/wallet/vault.py` — `get_next_hd_index` + `store_wallet` + `get_wallet`
- `projects/polymarket/crusaderbot/services/__init__.py` — package marker
- `projects/polymarket/crusaderbot/services/user_service.py` — `get_or_create_user` + `get_user_by_telegram_id` + `bump_tier`
- `projects/polymarket/crusaderbot/bot/handlers/__init__.py` — package marker
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — `handle_start` flow
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-r2-onboarding.md` — this report

**Modified (4):**
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — replaced inline `start_handler` with `partial(handle_start, pool=, config=)` from new onboarding module; `setup_handlers(app, *, db_pool, config)` signature now requires both keyword-only args; `/status` handler unchanged
- `projects/polymarket/crusaderbot/main.py` — single-line change in lifespan: `setup_handlers(bot_app, db_pool=db.pool, config=settings)` (not in original task spec — see Known Issues #1)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Last Updated bumped, COMPLETED includes R1 skeleton merge, IN PROGRESS = crusaderbot-r2-onboarding, NEXT PRIORITY = R3
- `projects/polymarket/crusaderbot/state/ROADMAP.md` — R1 row → ✅ Done (PR #847); R2 row → 🚧 In Progress; Last Updated bumped
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — appended R2 lane entry

## 4. What is working

- `derive_address` returns deterministic `(address, hex_key)` for a given seed + index per BIP44 path
- `encrypt_pk` / `decrypt_pk` round-trip cleanly via Fernet
- `get_next_hd_index` returns 0 on empty `wallets` table, monotonically increments thereafter
- `get_or_create_user` uses `INSERT ... ON CONFLICT (telegram_user_id) DO UPDATE` — idempotent on telegram_user_id, refreshes non-NULL username
- `bump_tier` writes both `UPDATE users` and `INSERT INTO audit.log` inside a single transaction with row-level lock — safe under concurrent admin requests
- `handle_start` is fully idempotent: second `/start` for the same Telegram user returns the same deposit address without provisioning a new wallet
- Private key never logged: `derive_address` returns it, `handle_start` encrypts immediately, drops the variable before any await
- `setup_handlers` requires both `db_pool` and `config` kwargs — wiring fails fast at startup if `main.py` forgets to pass them (TypeError)
- All exception paths surface a user-safe message AND log structured error with no PII beyond `telegram_user_id`

## 5. Known issues

- **`main.py` modified beyond original task DELIVERABLES.** Task listed only `bot/dispatcher.py` as modified. The dispatcher's new `setup_handlers(*, db_pool, config)` signature is the natural way to bind pool+config into the partial — but it requires the caller (`main.py` lifespan) to supply both. Without the 1-line change, startup would raise `TypeError: setup_handlers() missing 2 required keyword-only arguments`. Flagged for transparency.
- **No test coverage in this lane** (per task `Not in Scope: tests`). Manual verification path: deploy + send `/start` from two different Telegram accounts → verify two distinct addresses emitted; second `/start` from same account → verify same address.
- **Username refresh on UPSERT conflict ignores NULL.** `COALESCE(EXCLUDED.username, users.username)` — if a user later removes their Telegram @handle, the old one is preserved. Acceptable for R2 (tier-aware username display lands in R3).
- **No allowlist gate yet.** Any Telegram user who messages the bot gets a wallet provisioned at Tier 1. Tier 2 gating is R3 scope — no real money at risk in R2 since paper mode is enforced.
- **`Account.enable_unaudited_hdwallet_features()` required for mnemonic derivation.** This API is marked unaudited by `eth_account` upstream; blueprint v3.1 §7 explicitly accepts the trade-off for MVP. Production hardening (KMS-backed key vault, custom HD wallet) deferred to a later phase.
- **`hd_index` allocation has a TOCTOU window.** `MAX+1` and `INSERT` are not atomic. The DB `UNIQUE(hd_index)` constraint catches racing inserters (one INSERT will fail with `IntegrityError`); the current handler does not retry. Safe under low concurrency typical for R2; revisit on R3+ when registration QPS climbs.
- **`MIN_DEPOSIT_USDC` is shown to user but not enforced.** Detection + enforcement land in R4 deposit watcher.
- **`Telegram MarkdownV1` is used (not MarkdownV2).** Address renders in a backtick code-span. Ethereum addresses are `0x` + hex — no Markdown-special chars to escape. Safe for the R2 content set.
- **`user_id` column type.** `wallets.user_id` and `users.id` are `UUID`; passing Python `UUID` objects (returned by asyncpg) works in queries. Using `str` works too via implicit cast.

## 6. What is next

- **R3 — Operator allowlist (Tier 2 access gate):** admin-only commands to add/remove users from the Tier 2 allowlist; first consumer of `bump_tier`; user-facing message changes when transitioning tiers; gating on `/start` for users not yet allowlisted. STANDARD tier.
- Post-merge sync per AGENTS.md POST-MERGE SYNC RULE: bump PROJECT_STATE.md from IN PROGRESS → COMPLETED for R2; ROADMAP R2 row 🚧 → ✅; append CHANGELOG entry with merge SHA.

---

**Validation Tier:** STANDARD — onboarding flow + DB writes + first secret-handling surface. No risk/capital/execution paths touched. WARP•SENTINEL NOT ALLOWED on STANDARD per AGENTS.md.

**Claim Level:** FOUNDATION — wallet provisioning is functional but no signing path consumes the keys yet (R7+ scope). Risk constants imported in R1 but not enforced anywhere yet. Paper mode preserved.

**Validation Target:** (a) `derive_address` returns deterministic `(addr, key)` per BIP44 path; (b) `encrypt_pk` / `decrypt_pk` round-trip; (c) `get_or_create_user` upsert is idempotent on telegram_user_id; (d) `get_next_hd_index` returns 0 on empty table, increments thereafter; (e) `handle_start` provisions wallet on first contact, returns existing wallet on subsequent calls; (f) private key never appears in any log line or Telegram reply; (g) `bump_tier` writes audit.log entry inside same transaction as users UPDATE; (h) `setup_handlers` raises `TypeError` if `db_pool` or `config` missing.

**Not in Scope:** Deposit detection (R4), wallet import / WalletConnect, Tier 2 allowlist (R3), strategy config (R5), signing operations, live trading, tests.

**Suggested Next:** WARP🔹CMD review on PR (STANDARD; SENTINEL not allowed). On merge → R3 allowlist lane.
