"""HD wallet derivation using BIP44 path m/44'/60'/0'/0/{index}."""
from __future__ import annotations

from cryptography.fernet import Fernet
from eth_account import Account

Account.enable_unaudited_hdwallet_features()


def derive_address(seed_phrase: str, hd_index: int) -> tuple[str, str]:
    """Returns (checksum address, hex private key) for the given HD index."""
    acct = Account.from_mnemonic(
        seed_phrase,
        account_path=f"m/44'/60'/0'/0/{hd_index}",
    )
    pk = acct.key.hex()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    return acct.address, pk


def encrypt_pk(private_key: str, fernet_key: str) -> str:
    return Fernet(fernet_key.encode()).encrypt(private_key.encode()).decode()


def decrypt_pk(encrypted: str, fernet_key: str) -> str:
    return Fernet(fernet_key.encode()).decrypt(encrypted.encode()).decode()
