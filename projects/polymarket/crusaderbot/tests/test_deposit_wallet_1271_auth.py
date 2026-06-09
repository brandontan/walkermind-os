"""POLY_1271 deposit-wallet L1 auth fix (WARP/root-deposit-wallet-1271-auth).

Pins the ERC-7739 / Solady ``TypedDataSign`` envelope this repo builds for the
``ClobAuth`` message of a deposit wallet against the SDK's own encoding
primitives, so a silent upstream change to ``py-clob-client-v2`` cannot drift the
auth signature out of sync with the order signature.

These are pure-crypto/structure tests -- no network, no private key material
beyond ephemeral throwaway accounts.
"""
from __future__ import annotations

from eth_account import Account
from py_clob_client_v2.signing.eip712 import MSG_TO_SIGN
from py_clob_client_v2.signing.model import ClobAuth

from projects.polymarket.crusaderbot.integrations.clob import (
    deposit_wallet_auth as dwa,
)

_DEPOSIT = "0x3feC63402DfF02EdD1bEd25774e0b53c147606A9"


def _pk() -> str:
    return Account.create().key.hex()


# ---------------------------------------------------------------------------
# Encoding parity with the SDK / poly_eip712_structs (drift guards).
# ---------------------------------------------------------------------------


def test_clobauth_type_string_matches_sdk():
    """The literal field name ``address`` in the ClobAuth type string must match
    poly_eip712_structs exactly, or the contents hash diverges from the server."""
    ca = ClobAuth(address="0x" + "00" * 20, timestamp="0", nonce=0, message=MSG_TO_SIGN)
    enc = ca.encode_type()
    enc = enc.decode() if isinstance(enc, (bytes, bytearray)) else enc
    assert enc == dwa.CLOBAUTH_TYPE_STRING


def test_contents_hash_matches_lib_hash_struct():
    """Our ClobAuth contents hash == poly_eip712_structs ClobAuth.hash_struct()."""
    ca = ClobAuth(
        address=_DEPOSIT, timestamp="1700000000", nonce=0, message=MSG_TO_SIGN
    )
    assert (
        dwa._clobauth_contents_hash(_DEPOSIT, "1700000000", 0, MSG_TO_SIGN)
        == ca.hash_struct()
    )


def test_clobauth_domain_separator_matches_lib():
    """3-field ClobAuthDomain separator == the SDK's make_domain hash_struct."""
    from py_clob_client_v2.signing.eip712 import get_clob_auth_domain

    assert dwa._clobauth_domain_separator(137) == get_clob_auth_domain(137).hash_struct()


# ---------------------------------------------------------------------------
# ERC-7739 envelope structure.
# ---------------------------------------------------------------------------


def test_envelope_byte_layout():
    """0x + innerSig(65) + domainSep(32) + contentsHash(32) + contentsType +
    uint16(len(contentsType))."""
    sig = dwa.build_poly_1271_clob_auth_signature(
        private_key=_pk(),
        deposit_wallet=_DEPOSIT,
        chain_id=137,
        timestamp=1700000000,
        nonce=0,
    )
    assert sig.startswith("0x")
    body = bytes.fromhex(sig[2:])
    expected = 65 + 32 + 32 + len(dwa.CLOBAUTH_TYPE_STRING) + 2
    assert len(body) == expected
    # trailing uint16 length must equal the contents-type byte length
    assert int.from_bytes(body[-2:], "big") == len(dwa.CLOBAUTH_TYPE_STRING)
    # contents-type string is embedded verbatim before the length suffix
    assert dwa.CLOBAUTH_TYPE_STRING.encode("utf-8") in body


def test_signature_is_deterministic_per_inputs():
    pk = _pk()
    a = dwa.build_poly_1271_clob_auth_signature(
        private_key=pk, deposit_wallet=_DEPOSIT, chain_id=137,
        timestamp=1700000000, nonce=0,
    )
    b = dwa.build_poly_1271_clob_auth_signature(
        private_key=pk, deposit_wallet=_DEPOSIT, chain_id=137,
        timestamp=1700000000, nonce=0,
    )
    assert a == b


def test_signature_varies_with_timestamp_and_wallet():
    pk = _pk()
    base = dwa.build_poly_1271_clob_auth_signature(
        private_key=pk, deposit_wallet=_DEPOSIT, chain_id=137,
        timestamp=1700000000, nonce=0,
    )
    later = dwa.build_poly_1271_clob_auth_signature(
        private_key=pk, deposit_wallet=_DEPOSIT, chain_id=137,
        timestamp=1700000001, nonce=0,
    )
    other = dwa.build_poly_1271_clob_auth_signature(
        private_key=pk, deposit_wallet="0x" + "11" * 20, chain_id=137,
        timestamp=1700000000, nonce=0,
    )
    assert base != later
    assert base != other


def test_l1_headers_bind_poly_address_to_deposit_wallet():
    """The L1 header POLY_ADDRESS is the deposit wallet, NOT the EOA -- this is the
    whole point of the fix."""
    pk = _pk()
    eoa = Account.from_key(pk).address
    headers = dwa.build_deposit_wallet_l1_headers(
        private_key=pk, deposit_wallet=_DEPOSIT, chain_id=137, timestamp=1700000000,
    )
    assert headers["POLY_ADDRESS"] == _DEPOSIT
    assert headers["POLY_ADDRESS"].lower() != eoa.lower()
    assert headers["POLY_SIGNATURE"].startswith("0x")
    assert headers["POLY_TIMESTAMP"] == "1700000000"
    assert headers["POLY_NONCE"] == "0"
