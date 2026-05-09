"""Polymarket CLOB authentication primitives — L1 (EIP-712), L2 (HMAC),
and builder headers.

Every helper here is pure: no network I/O, no global state, no config
reads. Callers (the adapter, the factory, tests) supply credentials
explicitly. The functions are deterministic given a clock value, which
the tests exploit by injecting a fixed timestamp.

Reference: https://docs.polymarket.com/#authentication
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Optional, TypedDict

from eth_account import Account
from eth_account.messages import encode_typed_data

from .exceptions import ClobAuthError

CLOB_DOMAIN_NAME = "ClobAuthDomain"
CLOB_DOMAIN_VERSION = "1"
CLOB_AUTH_MESSAGE = "This message attests that I control the given wallet"
DEFAULT_CHAIN_ID = 137


class L1Headers(TypedDict):
    POLY_ADDRESS: str
    POLY_SIGNATURE: str
    POLY_TIMESTAMP: str
    POLY_NONCE: str


class L2Headers(TypedDict):
    POLY_ADDRESS: str
    POLY_SIGNATURE: str
    POLY_TIMESTAMP: str
    POLY_API_KEY: str
    POLY_PASSPHRASE: str


class BuilderHeaders(TypedDict):
    POLY_BUILDER_API_KEY: str
    POLY_BUILDER_TIMESTAMP: str
    POLY_BUILDER_PASSPHRASE: str
    POLY_BUILDER_SIGNATURE: str


def _now() -> int:
    """Seam — overridden by tests via monkeypatch to inject a fixed clock."""
    return int(time.time())


def _normalize_pk(private_key: str) -> str:
    """Accept hex with or without ``0x`` prefix; reject obviously bad input."""
    pk = private_key.strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    if len(pk) != 66:  # 0x + 64 hex chars
        raise ClobAuthError(
            f"private_key must be 32 bytes hex ({len(pk) - 2} chars supplied)"
        )
    return pk


@dataclass(frozen=True)
class ClobAuthSigner:
    """L1 signer — wraps a private key and produces ``ClobAuth`` EIP-712
    signatures the CLOB ``/auth/api-key`` and ``/auth/derive-api-key``
    endpoints require.

    The address is derived once at construction so callers don't pass it
    in separately; rotating the key requires constructing a new signer
    (intentional — credential rotation is an operator decision).
    """

    private_key: str
    chain_id: int = DEFAULT_CHAIN_ID

    @property
    def address(self) -> str:
        return Account.from_key(_normalize_pk(self.private_key)).address

    def sign_clob_auth(
        self, *, timestamp: Optional[int] = None, nonce: int = 0
    ) -> tuple[str, str, int]:
        """Produce ``(signature_hex, address, timestamp)`` for L1 auth.

        Returns the actual timestamp used so the caller can echo it into
        the ``POLY_TIMESTAMP`` header without a second clock read. Nonce
        defaults to 0 — Polymarket assigns API keys per (address, nonce),
        so callers wanting a fresh credential pair must bump it explicitly.
        """
        ts = int(timestamp) if timestamp is not None else _now()
        pk = _normalize_pk(self.private_key)
        addr = Account.from_key(pk).address
        signable = encode_typed_data(
            domain_data={
                "name": CLOB_DOMAIN_NAME,
                "version": CLOB_DOMAIN_VERSION,
                "chainId": self.chain_id,
            },
            message_types={
                "ClobAuth": [
                    {"name": "address", "type": "address"},
                    {"name": "timestamp", "type": "string"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "message", "type": "string"},
                ],
            },
            message_data={
                "address": addr,
                "timestamp": str(ts),
                "nonce": int(nonce),
                "message": CLOB_AUTH_MESSAGE,
            },
        )
        try:
            signed = Account.sign_message(signable, private_key=pk)
        except Exception as exc:  # eth-account raises ValueError on bad PK
            raise ClobAuthError(f"EIP-712 sign failed: {exc}") from exc
        sig = signed.signature.hex()
        if not sig.startswith("0x"):
            sig = "0x" + sig
        return sig, addr, ts


def build_l1_headers(
    signer: ClobAuthSigner,
    *,
    timestamp: Optional[int] = None,
    nonce: int = 0,
) -> L1Headers:
    """Headers required by ``POST /auth/api-key`` and
    ``GET /auth/derive-api-key``.

    Returns a ``TypedDict`` (plain ``dict`` at runtime) so callers can
    splat it into ``httpx.AsyncClient.request(..., headers=...)`` directly.
    """
    sig, addr, ts = signer.sign_clob_auth(timestamp=timestamp, nonce=nonce)
    return {
        "POLY_ADDRESS": addr,
        "POLY_SIGNATURE": sig,
        "POLY_TIMESTAMP": str(ts),
        "POLY_NONCE": str(int(nonce)),
    }


@dataclass(frozen=True)
class HMACSigner:
    """L2 signer — wraps an API secret (urlsafe-base64 encoded) and
    produces HMAC-SHA256 signatures over ``timestamp + method + path + body``.

    The CLOB stores the secret in urlsafe-base64; we decode once and keep
    the raw bytes in memory so each call is just an HMAC compute.
    """

    api_secret: str

    def sign(
        self,
        *,
        timestamp: int,
        method: str,
        path: str,
        body: str = "",
    ) -> str:
        return build_hmac_signature(
            secret=self.api_secret,
            timestamp=timestamp,
            method=method,
            path=path,
            body=body,
        )


def build_hmac_signature(
    *,
    secret: str,
    timestamp: int,
    method: str,
    path: str,
    body: str = "",
) -> str:
    """Compute the L2 HMAC signature.

    Polymarket uses urlsafe base64 for both the secret and the resulting
    signature (matches the ``py-clob-client`` reference implementation).
    Body must be the JSON the client actually sends — even a single
    whitespace difference breaks the signature.
    """
    # ``base64.urlsafe_b64decode`` silently strips chars outside the alphabet,
    # which would let a typo'd secret produce a valid-but-wrong HMAC and a
    # cryptic 401 from the broker. Convert to standard alphabet + validate=True
    # so a bad secret raises here instead.
    padded = _pad_b64(secret).replace("-", "+").replace("_", "/")
    try:
        decoded = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ClobAuthError(f"api_secret is not urlsafe-base64: {exc}") from exc
    message = f"{int(timestamp)}{method.upper()}{path}{body}"
    digest = hmac.new(decoded, message.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


def build_l2_headers(
    *,
    api_key: str,
    api_secret: str,
    passphrase: str,
    address: str,
    method: str,
    path: str,
    body: str = "",
    timestamp: Optional[int] = None,
) -> L2Headers:
    """Headers required by every authenticated CLOB endpoint."""
    ts = int(timestamp) if timestamp is not None else _now()
    sig = build_hmac_signature(
        secret=api_secret,
        timestamp=ts,
        method=method,
        path=path,
        body=body,
    )
    return {
        "POLY_ADDRESS": address,
        "POLY_SIGNATURE": sig,
        "POLY_TIMESTAMP": str(ts),
        "POLY_API_KEY": api_key,
        "POLY_PASSPHRASE": passphrase,
    }


def build_builder_headers(
    *,
    builder_api_key: str,
    builder_api_secret: str,
    builder_passphrase: str,
    method: str,
    path: str,
    body: str = "",
    timestamp: Optional[int] = None,
) -> BuilderHeaders:
    """Order-attribution headers for the Polymarket builder program.

    Same HMAC scheme as L2 but stamped under the ``POLY_BUILDER_*`` prefix.
    Caller decides whether to include them — orders without builder
    headers still post normally, just without builder attribution.
    """
    ts = int(timestamp) if timestamp is not None else _now()
    sig = build_hmac_signature(
        secret=builder_api_secret,
        timestamp=ts,
        method=method,
        path=path,
        body=body,
    )
    return {
        "POLY_BUILDER_API_KEY": builder_api_key,
        "POLY_BUILDER_TIMESTAMP": str(ts),
        "POLY_BUILDER_PASSPHRASE": builder_passphrase,
        "POLY_BUILDER_SIGNATURE": sig,
    }


def _pad_b64(value: str) -> str:
    """Pad a urlsafe-base64 string to a multiple of 4 chars.

    Polymarket sometimes returns secrets without the trailing ``=`` pad
    bytes; ``base64.urlsafe_b64decode`` rejects unpadded input. Padding
    here makes the decoder tolerant of both forms.
    """
    rem = len(value) % 4
    if rem:
        return value + "=" * (4 - rem)
    return value
