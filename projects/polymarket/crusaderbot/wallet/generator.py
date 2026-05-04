"""HD wallet derivation + Fernet at-rest encryption for private keys."""
from __future__ import annotations

from typing import Tuple

from cryptography.fernet import Fernet
from eth_account import Account


def derive_address(seed_phrase: str, hd_index: int) -> Tuple[str, str]:
    """Derive Ethereum address + private key from BIP44 path m/44'/60'/0'/0/{hd_index}.

    Returns (address, private_key_hex). The caller MUST encrypt the private key
    before persistence; never log, transmit, or surface it in any user-facing reply.
    """
    Account.enable_unaudited_hdwallet_features()
    acct = Account.from_mnemonic(
        seed_phrase,
        account_path=f"m/44'/60'/0'/0/{hd_index}",
    )
    return acct.address, acct.key.hex()


def encrypt_pk(private_key: str, fernet_key: str) -> str:
    """Encrypt a private key with Fernet. Returns urlsafe base64 token string."""
    f = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return f.encrypt(private_key.encode()).decode()


def decrypt_pk(encrypted: str, fernet_key: str) -> str:
    """Decrypt a previously-encrypted private key. Returns the original hex string."""
    f = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return f.decrypt(encrypted.encode()).decode()
