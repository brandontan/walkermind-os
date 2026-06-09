"""Corrected L1 (and L2 address) authentication for Polymarket POLY_1271
*deposit wallets* (the EIP-7702 / ERC-4337 smart accounts every Magic-Link /
email account was migrated to after 2026-04-28).

WHY THIS EXISTS
---------------
``py-clob-client-v2`` builds POLY_1271 **order** signatures correctly
(``exchange_order_builder_v2._build_poly_1271_order_signature`` — maker == signer
== deposit wallet, ERC-7739 / Solady ``TypedDataSign`` wrapped under the
``DepositWallet`` domain). But its **L1 auth** path is broken for deposit wallets
(upstream Polymarket/py-clob-client-v2 issue #70, OPEN, unfixed):

* ``headers.create_level_1_headers`` sets ``POLY_ADDRESS = signer.address()`` —
  the *EOA*, never the deposit-wallet funder.
* ``signing.eip712.sign_clob_auth_message`` signs the ``ClobAuth`` struct hash with
  a **plain ECDSA** signature over the EOA — never the ERC-7739 wrapper the
  deposit wallet's ``isValidSignature`` (EIP-1271) requires.

Net effect: ``create_or_derive_api_key`` mints an API key bound to the EOA, while
orders correctly carry ``signer = deposit_wallet``. The CLOB then rejects every
order with ``"the order signer address has to be the address of the API KEY"``
(or, when the legacy proxy is used as maker, ``"maker address not allowed, please
use the deposit wallet flow"``).

THE FIX
-------
Mirror the SDK's *order* ERC-7739 wrapping for the **ClobAuth** struct so the
derived API key binds to the deposit wallet:

* ``POLY_ADDRESS = deposit_wallet`` (the funder).
* ``ClobAuth.address = deposit_wallet``.
* signature = ERC-7739 ``TypedDataSign`` envelope over the ``ClobAuth`` contents,
  under the ``DepositWallet`` domain, signed by the EOA key — byte-identical
  structure to ``_build_poly_1271_order_signature`` but with the ``ClobAuth``
  contents and the ``ClobAuthDomain`` verifier separator.

All hashing constants are cross-checked against the SDK / ``poly_eip712_structs``
in ``tests/test_deposit_wallet_1271_auth.py`` so a silent upstream encoding change
cannot drift this out of sync.

SCOPE / SAFETY
--------------
* Used ONLY when ``signature_type == POLY_1271`` (3). Every other wallet type
  (EOA/0, POLY_PROXY/1, POLY_GNOSIS_SAFE/2) keeps the SDK's native path untouched.
* No capital movement here — this is auth only. ``ENABLE_LIVE_TRADING`` and fill
  gating are unaffected and remain authoritative.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_utils import keccak

# Reuse the SDK's own DepositWallet domain constants so this can never drift from
# the order-signature wrapper the same SDK builds.
from py_clob_client_v2.order_utils.exchange_order_builder_v2 import (
    DEPOSIT_WALLET_DOMAIN_SALT,
    DEPOSIT_WALLET_NAME_HASH,
    DEPOSIT_WALLET_VERSION_HASH,
)
from py_clob_client_v2.signing.eip712 import MSG_TO_SIGN

logger = logging.getLogger(__name__)

# ---- ClobAuth EIP-712 type system (verified byte-exact vs poly_eip712_structs) -

# poly_eip712_structs renders the field named ``address`` literally, so the type
# string is "ClobAuth(address address,...)". Confirmed equal to
# ClobAuth(...).encode_type() in the unit test.
CLOBAUTH_TYPE_STRING = (
    "ClobAuth(address address,string timestamp,uint256 nonce,string message)"
)
CLOBAUTH_TYPE_HASH = keccak(text=CLOBAUTH_TYPE_STRING)

# ERC-7739 / Solady nested TypedDataSign envelope for the ClobAuth contents.
SOLADY_AUTH_TYPE_STRING = (
    "TypedDataSign(ClobAuth contents,string name,string version,uint256 chainId,"
    "address verifyingContract,bytes32 salt)" + CLOBAUTH_TYPE_STRING
)
SOLADY_AUTH_TYPE_HASH = keccak(text=SOLADY_AUTH_TYPE_STRING)

# ClobAuthDomain is a 3-field EIP712Domain (NO verifyingContract) — the verifier
# domain the CLOB uses for L1 auth (mirrors how the order wrapper uses the CTF
# Exchange domain as its verifier separator).
_CLOBAUTH_DOMAIN_TYPE_STRING = (
    "EIP712Domain(string name,string version,uint256 chainId)"
)
_CLOBAUTH_DOMAIN_TYPE_HASH = keccak(text=_CLOBAUTH_DOMAIN_TYPE_STRING)
_CLOBAUTH_DOMAIN_NAME_HASH = keccak(text="ClobAuthDomain")
_CLOBAUTH_DOMAIN_VERSION_HASH = keccak(text="1")


def _clobauth_domain_separator(chain_id: int) -> bytes:
    return keccak(
        primitive=abi_encode(
            ["bytes32", "bytes32", "bytes32", "uint256"],
            [
                _CLOBAUTH_DOMAIN_TYPE_HASH,
                _CLOBAUTH_DOMAIN_NAME_HASH,
                _CLOBAUTH_DOMAIN_VERSION_HASH,
                chain_id,
            ],
        )
    )


def _clobauth_contents_hash(
    deposit_wallet: str, timestamp: str, nonce: int, message: str
) -> bytes:
    return keccak(
        primitive=abi_encode(
            ["bytes32", "address", "bytes32", "uint256", "bytes32"],
            [
                CLOBAUTH_TYPE_HASH,
                deposit_wallet,
                keccak(text=str(timestamp)),
                int(nonce),
                keccak(text=message),
            ],
        )
    )


def build_poly_1271_clob_auth_signature(
    *,
    private_key: str,
    deposit_wallet: str,
    chain_id: int,
    timestamp: int,
    nonce: int,
    message: str = MSG_TO_SIGN,
) -> str:
    """ERC-7739 ``TypedDataSign`` envelope over ``ClobAuth`` for a deposit wallet.

    Structurally identical to the SDK's
    ``ExchangeOrderBuilderV2._build_poly_1271_order_signature`` (which wraps the
    *Order* contents) — here applied to the *ClobAuth* contents with the
    ``ClobAuthDomain`` separator as the verifier domain.

    Returns ``0x`` + innerSig(65) + verifierDomainSeparator(32) + contentsHash(32)
    + contentsTypeString + uint16(len(contentsTypeString)).
    """
    domain_sep = _clobauth_domain_separator(chain_id)
    contents_hash = _clobauth_contents_hash(
        deposit_wallet, str(timestamp), nonce, message
    )
    typed_data_sign_struct_hash = keccak(
        primitive=abi_encode(
            [
                "bytes32",
                "bytes32",
                "bytes32",
                "bytes32",
                "uint256",
                "address",
                "bytes32",
            ],
            [
                SOLADY_AUTH_TYPE_HASH,
                contents_hash,
                DEPOSIT_WALLET_NAME_HASH,
                DEPOSIT_WALLET_VERSION_HASH,
                chain_id,
                deposit_wallet,
                DEPOSIT_WALLET_DOMAIN_SALT,
            ],
        )
    )
    digest = keccak(primitive=b"\x19\x01" + domain_sep + typed_data_sign_struct_hash)
    signed = Account._sign_hash(digest, private_key=private_key)
    inner = signed.signature.hex()
    if inner.startswith("0x"):
        inner = inner[2:]

    contents_type = CLOBAUTH_TYPE_STRING.encode("utf-8").hex()
    contents_type_len = len(CLOBAUTH_TYPE_STRING).to_bytes(2, "big").hex()
    return (
        "0x"
        + inner
        + domain_sep.hex()
        + contents_hash.hex()
        + contents_type
        + contents_type_len
    )


def build_deposit_wallet_l1_headers(
    *,
    private_key: str,
    deposit_wallet: str,
    chain_id: int,
    timestamp: int,
    nonce: int = 0,
) -> dict:
    """L1 (POLY) headers whose POLY_ADDRESS is the deposit wallet and whose
    POLY_SIGNATURE is the ERC-7739-wrapped ClobAuth signature."""
    sig = build_poly_1271_clob_auth_signature(
        private_key=private_key,
        deposit_wallet=deposit_wallet,
        chain_id=chain_id,
        timestamp=timestamp,
        nonce=nonce,
    )
    return {
        "POLY_ADDRESS": deposit_wallet,
        "POLY_SIGNATURE": sig,
        "POLY_TIMESTAMP": str(timestamp),
        "POLY_NONCE": str(nonce),
    }


def derive_or_create_deposit_wallet_creds(
    *,
    host: str,
    private_key: str,
    deposit_wallet: str,
    chain_id: int,
    timestamp: int,
    nonce: int = 0,
    timeout: float = 20.0,
) -> dict:
    """Resolve L2 API creds bound to the *deposit wallet*.

    Tries ``GET /auth/derive-api-key`` first (idempotent — returns the existing
    key for a wallet that has one), then falls back to ``POST /auth/api-key``
    (create) for a wallet with no key yet. Raises on a definitive auth failure so
    a misconfiguration surfaces immediately rather than as a later order reject.

    Returns ``{"api_key", "api_secret", "passphrase"}``.
    """
    headers = build_deposit_wallet_l1_headers(
        private_key=private_key,
        deposit_wallet=deposit_wallet,
        chain_id=chain_id,
        timestamp=timestamp,
        nonce=nonce,
    )
    base = host.rstrip("/")
    last_err: Optional[str] = None

    for method, path in (("GET", "/auth/derive-api-key"), ("POST", "/auth/api-key")):
        try:
            resp = requests.request(
                method, f"{base}{path}", headers=headers, timeout=timeout
            )
        except requests.RequestException as exc:  # network — surface, do not mask
            last_err = f"{method} {path}: transport error: {exc}"
            logger.warning("deposit-wallet auth %s", last_err)
            continue
        if resp.status_code == 200:
            data = resp.json()
            key = data.get("apiKey") or data.get("api_key")
            secret = data.get("secret") or data.get("api_secret")
            passphrase = data.get("passphrase") or data.get("api_passphrase")
            if key and secret and passphrase:
                logger.info(
                    "deposit-wallet creds resolved via %s %s (key=%.8s…)",
                    method, path, key,
                )
                return {
                    "api_key": key,
                    "api_secret": secret,
                    "passphrase": passphrase,
                }
            last_err = f"{method} {path}: 200 but incomplete creds: {list(data)}"
        else:
            last_err = f"{method} {path}: {resp.status_code} {resp.text[:200]}"
        logger.warning("deposit-wallet auth %s", last_err)

    raise RuntimeError(
        f"deposit-wallet (POLY_1271) credential resolution failed: {last_err}"
    )
