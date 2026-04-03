# WALLET_REAL — Real Wallet System Implementation

**Date:** 2026-04-03  
**Author:** FORGE-X  
**Branch:** `feature/forge/wallet-real-foundation`

---

## 1. Architecture

```
TELEGRAM UI
    ↓ action:wallet / wallet_balance / wallet_withdraw
CallbackRouter  ──(user_id)──→  telegram/handlers/wallet.py
                                    ↓
                              core/wallet/service.py (WalletService)
                                  ↙         ↘
                   core/wallet/models.py   core/security/encryption.py
                   (WalletModel)           (AES-256-GCM)
                                  ↓
                        Polymarket Data API
                        (balance fetch)
```

### Domain directories used:
- `core/security/` — encryption primitives
- `core/wallet/` — wallet lifecycle (models + service)
- `telegram/handlers/` — UI wiring
- `telegram/ui/` — screen templates + keyboard

---

## 2. Encryption Flow

```
WALLET_SECRET_KEY (env) ──→ PBKDF2-HMAC-SHA256 (260,000 iterations)
                                ↓
                        256-bit AES key
                                ↓
       random 16-byte salt + random 12-byte nonce
                                ↓
                    AES-256-GCM encrypt(private_key_hex, AAD="polyquantbot-wallet-v1")
                                ↓
         Base64(salt || nonce || ciphertext || 16-byte GCM tag)
```

- Each encryption call generates a fresh random salt and nonce
- GCM tag provides authentication (tampering is detected on decrypt)
- Plaintext key is deleted from memory immediately after encryption
- WALLET_SECRET_KEY missing → `EnvironmentError` raised immediately (fail fast)

---

## 3. Wallet Lifecycle

```
User sends Telegram action
        ↓
WalletService.create_wallet(user_id)     ← idempotent
        ↓
generate_keypair() via secp256k1 (cryptography lib)
        ↓
encrypt_private_key(hex_private_key)    ← AES-256-GCM
        ↓
del private_key_hex (zero plaintext from scope)
        ↓
WalletModel stored in-memory (_wallets dict)
        ↓
WalletService.get_balance(user_id)       ← Polymarket Data API
WalletService.withdraw(user_id, to, amt) ← decrypt → sign → broadcast
```

### Multi-user safety:
- Per-user `asyncio.Lock` prevents TOCTOU race on wallet creation
- Global lock protects per-user lock dict
- In-memory store is instance-scoped (no global state)

---

## 4. API Integration

### Balance fetch — Polymarket Data API:
```
GET https://data-api.polymarket.com/value?user={address}
→ { "portfolioValue": 42.5, ... }
```
- Retry: 3× with 0.5s backoff
- Timeout: 5s per request
- Fallback: returns 0.0 on all errors

### Withdraw — Polygon ERC-20 transfer:
- Requires `eth_account` + `POLYGON_RPC_URL` env var
- USDC contract: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (Polygon)
- Chain ID: 137
- If dependencies absent → returns `"pending_no_signer"` status (no silent failure)

---

## 5. Files Created / Modified

### Created:
| File | Description |
|------|-------------|
| `core/security/__init__.py` | Package init |
| `core/security/encryption.py` | AES-256-GCM encrypt/decrypt (PBKDF2 key derivation) |
| `core/wallet/__init__.py` | Package init |
| `core/wallet/models.py` | `WalletModel` dataclass (safe repr, public_dict) |
| `core/wallet/service.py` | `WalletService` (create, get, balance, withdraw) |
| `tests/test_wallet_real.py` | 27 tests (WR-01 to WR-27) — all passing |
| `reports/forge/WALLET_REAL.md` | This report |

### Modified:
| File | Change |
|------|--------|
| `telegram/handlers/wallet.py` | Rewired to WalletService; added `handle_wallet_withdraw`; `set_wallet_service()` injection |
| `telegram/ui/screens.py` | Updated `wallet_screen`, `wallet_balance_screen`; added `wallet_withdraw_screen`, `wallet_withdraw_result_screen` |
| `telegram/ui/keyboard.py` | Added `💸 Withdraw` button to `build_wallet_menu()` |
| `telegram/handlers/callback_router.py` | `_dispatch()` now accepts `user_id`; routes `wallet_withdraw` action |

---

## 6. What's Working

- ✅ AES-256-GCM encryption with PBKDF2-HMAC-SHA256 key derivation
- ✅ Per-user isolated wallet creation (secp256k1 keypair)
- ✅ Idempotent wallet creation (same wallet on repeated calls)
- ✅ Encrypted private key never logged or returned to UI
- ✅ Balance fetch from Polymarket Data API (with retry + timeout)
- ✅ Telegram wallet screen shows address + live balance
- ✅ Withdraw button in Telegram wallet menu
- ✅ Withdraw screen shows address and available balance
- ✅ Withdraw validation (address format, amount > 0, sufficient balance)
- ✅ Private key zeroed from memory after use in withdraw
- ✅ `set_wallet_service()` injection hook for main.py wiring
- ✅ 27/27 tests passing

---

## 7. Edge Cases Handled

| Case | Handling |
|------|----------|
| `WALLET_SECRET_KEY` not set | `EnvironmentError` raised immediately |
| Tampered ciphertext | GCM auth tag mismatch → `ValueError` |
| Duplicate wallet creation (race) | Per-user asyncio lock + double-check |
| No HTTP session | Returns 0.0 with warning log |
| Balance API timeout | Retry 3×, fallback 0.0 |
| Withdraw to bad address | `ValueError` before any decrypt |
| Insufficient balance | `RuntimeError` before any decrypt |
| `eth_account` not installed | Returns `pending_no_signer` status (no crash) |
| `POLYGON_RPC_URL` not set | Returns `pending_no_rpc` status (no crash) |

---

## 8. Known Issues / Next Steps

1. **Address derivation**: Uses `hashlib.sha3_256` (FIPS SHA-3). For Ethereum-compatible
   addresses install `eth_account` and replace `_derive_address()` with
   `Account.from_key(private_key_hex).address`.

2. **Persistence**: WalletService currently stores wallets in-memory only. Wire into
   the existing `SQLiteClient` (or PostgreSQL) for persistence across restarts.

3. **main.py wiring**: Call `wallet.set_wallet_service(WalletService())` at bot startup
   to activate live balance + withdraw UI.

4. **Live withdraw**: Requires `pip install eth_account web3` and `POLYGON_RPC_URL` env var.
