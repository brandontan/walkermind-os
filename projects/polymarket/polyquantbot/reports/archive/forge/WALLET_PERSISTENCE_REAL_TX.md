# WALLET_PERSISTENCE_REAL_TX — Wallet Persistence & Real Polygon Transactions

**Date:** 2026-04-03  
**Author:** FORGE-X  
**Branch:** feature/forge/wallet-persistence-real-tx

---

## 1. What Was Built

Upgraded the PolyQuantBot wallet system with:

- **PostgreSQL persistence** — wallets now survive process restarts via the `wallets` table
- **Correct Ethereum address derivation** — replaced SHA-3 fallback with `eth_account.Account.create()` (EIP-55 checksummed addresses)
- **Real Polygon ERC-20 transactions** — `web3` + `eth_account` sign + broadcast USDC transfers with 2× RPC retry
- **Telegram `/withdraw` command handler** — new `handle_withdraw_command()` returns result screen with tx hash
- **10 new tests** (WR-28 – WR-37) covering repository layer, eth_account derivation, and withdraw command UI

---

## 2. DB Schema

```sql
CREATE TABLE IF NOT EXISTS wallets (
    user_id                 BIGINT           PRIMARY KEY,
    address                 TEXT             NOT NULL,
    encrypted_private_key   TEXT             NOT NULL,   -- AES-256-GCM Base64 ciphertext
    created_at              DOUBLE PRECISION NOT NULL,
    updated_at              DOUBLE PRECISION NOT NULL
);
```

**Key design decisions:**
- `user_id` is the natural primary key (Telegram user ID)
- `encrypted_private_key` stores the AES-256-GCM ciphertext only — plaintext is **never** stored
- `ON CONFLICT (user_id) DO NOTHING` ensures idempotent inserts
- `updated_at` tracks last modification time for auditing

---

## 3. Address Derivation Fix

**Before:** Custom `_derive_address()` using `hashlib.sha3_256` (FIPS 202 SHA-3 ≠ Ethereum Keccak-256) — produced addresses that did NOT match on-chain.

**After:** `eth_account.Account.create()` — uses the correct secp256k1 key generation + Keccak-256 hashing, producing EIP-55 checksummed addresses compatible with the Polygon mainnet.

```python
# New _generate_keypair() implementation
from eth_account import Account

acct = Account.create()
private_key_hex = bytes(acct.key).hex()  # 64-char hex, no 0x prefix
address = acct.address                   # EIP-55 checksummed 0x... address
```

---

## 4. Transaction Flow

```
User → /withdraw <to_address> <amount>
          │
          ▼
handle_withdraw_command(user_id, to_address, amount_usdc)
          │
          ▼
WalletService.withdraw(user_id, to_address, amount_usdc)
    │
    ├── validate to_address (len=42, 0x prefix)
    ├── validate amount > 0
    ├── get_wallet(user_id)  → WalletRepository → PostgreSQL
    ├── get_balance(user_id) → Polymarket Data API
    ├── check balance >= amount
    └── decrypt private key → _sign_and_broadcast()
              │
              ├── Account.from_key(0x{private_key_hex})
              ├── web3.Web3(HTTPProvider(POLYGON_RPC_URL, timeout=5s))
              ├── Build ERC-20 transfer tx (USDC, chainId=137)
              ├── account.sign_transaction(tx)
              └── w3.eth.send_raw_transaction()  [2× retry on RPC error]
                        │
                        ▼
              { "status": "broadcast", "tx_hash": "0x...", ... }
          │
          ▼
wallet_withdraw_result_screen(result)
→ "✅ Withdraw sent\nTx: 0x..."
```

---

## 5. Security Measures

| Measure | Implementation |
|---------|---------------|
| Key encryption | AES-256-GCM with PBKDF2-HMAC-SHA256 key derivation (WALLET_SECRET_KEY env var) |
| No plaintext key storage | Plaintext key deleted immediately after `encrypt_private_key()` |
| No key logging | `encrypted_private_key` explicitly excluded from all log events |
| Signing boundary | Key decrypted only inside `_sign_and_broadcast()`, deleted in `finally` block |
| Address validation | 42-char, `0x` prefix check before any DB/RPC call |
| Amount validation | Positive float check; integer wei conversion via `Decimal` to avoid rounding |
| Balance check | On-chain balance verified before signing transaction |
| Idempotent creation | `ON CONFLICT DO NOTHING` + double-checked locking per user |
| Multi-user safe | Per-user `asyncio.Lock` prevents TOCTOU concurrent wallet creation |

---

## 6. Files Created / Modified

### Created
- `core/wallet/repository.py` — `WalletRepository` class with `ensure_schema()`, `get_wallet()`, `create_wallet()`, `update_wallet()`

### Modified
- `core/wallet/service.py`
  - Replaced `_derive_address()` + old `_generate_keypair()` with `eth_account.Account.create()` approach
  - Added `repository: Optional[WalletRepository] = None` constructor parameter
  - `get_wallet()`: delegates to repository when set; falls back to in-memory dict
  - `create_wallet()`: persists via repository when set; async double-checked locking preserved
  - `get_balance()` / `withdraw()`: use `await self.get_wallet()` (was `self._wallets.get()`)
  - `_sign_and_broadcast()`: added 2× RPC retry with `_MAX_RPC_RETRIES=2` and `_RPC_RETRY_DELAY_S=1.0`; added `timeout=5s` to HTTPProvider
  - Added `_MAX_RPC_RETRIES`, `_RPC_RETRY_DELAY_S` module constants
- `core/wallet/__init__.py` — exports `WalletRepository`
- `telegram/handlers/wallet.py` — added `handle_withdraw_command()` + imports `wallet_withdraw_result_screen`
- `tests/test_wallet_real.py` — added WR-28 through WR-37 (10 new tests)

---

## 7. Test Cases

| ID | Scenario |
|----|----------|
| WR-28 | `WalletRepository.get_wallet` returns `None` when no DB row |
| WR-29 | `WalletRepository.get_wallet` deserializes row to `WalletModel` |
| WR-30 | `WalletRepository.create_wallet` returns existing row on conflict (idempotent) |
| WR-31 | `WalletRepository.ensure_schema` calls `_execute` with `CREATE TABLE IF NOT EXISTS wallets` DDL |
| WR-32 | `WalletRepository.update_wallet` calls `_execute` with `UPDATE wallets` SQL |
| WR-33 | `WalletService` with repository delegates `get_wallet` to DB layer |
| WR-34 | `WalletService` with repository persists wallet via `create_wallet` |
| WR-35 | `_generate_keypair()` produces valid 64-char private key + 42-char `0x` address |
| WR-36 | `handle_withdraw_command` returns result screen with tx hash on success |
| WR-37 | `handle_withdraw_command` returns error screen on `ValueError` |

**Total: 37 tests pass (WR-01–WR-37). All 27 original tests preserved.**

---

## 8. Known Limitations

1. **`WalletRepository.ensure_schema()` must be called at startup** — `WalletService` does not auto-call it. Wire `await repo.ensure_schema()` in `main.py` after `DatabaseClient.connect()`.

2. **`POLYGON_RPC_URL` env var required** — Without it, `withdraw()` returns `"pending_no_rpc"` status (no real transaction).

3. **Balance from Polymarket Data API only** — Live on-chain balance from Polygon RPC is not yet fetched directly; uses Polymarket's portfolio value endpoint.

4. **`/withdraw` command routing** — `handle_withdraw_command()` is implemented but needs wiring into `main.py` text command router to parse `/withdraw <address> <amount>`.

5. **No key rotation** — Existing wallets retain their original encrypted key; there is no key rotation flow.

---

## 9. What's Next

- Wire `WalletRepository` + `WalletService(repository=repo)` into `main.py` startup
- Wire `/withdraw` text command into `CommandRouter` / `CommandHandler`
- Wire `WalletManager` live balance into `run_trading_loop()` bankroll
- Add direct RPC balance fetch (USDC ERC-20 `balanceOf`) as alternative to Polymarket API
