"""Tests for the Phase 4A CLOB authentication primitives.

These tests are pure (no network, no fs). They lock the EIP-712 + HMAC
output shapes against deterministic test vectors so a regression in the
signer (e.g. domain version drift, wrong message string) breaks loudly.
"""
from __future__ import annotations

import base64

import pytest

from projects.polymarket.crusaderbot.integrations.clob.auth import (
    CLOB_AUTH_MESSAGE,
    CLOB_DOMAIN_NAME,
    CLOB_DOMAIN_VERSION,
    DEFAULT_CHAIN_ID,
    ClobAuthSigner,
    build_builder_headers,
    build_hmac_signature,
    build_l1_headers,
    build_l2_headers,
)
from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobAuthError,
)


# --- Deterministic vectors ------------------------------------------

DETERMINISTIC_PK = "0x" + ("aa" * 32)
DETERMINISTIC_ADDR = "0x8fd379246834eac74B8419FfdA202CF8051F7A03"
DETERMINISTIC_TS = 1_700_000_000
EXPECTED_L1_SIG = (
    "0xd26cc35884048a6223f0530c5d6b86d757bf10c77147a75b9f8b78154773aa79"
    "09a883170ba952ac61691af31bd51a230387c613bcefd960efd1f1e6cd485d241b"
)

# 32-byte ASCII payload, urlsafe-b64 encoded (matches Polymarket secret shape)
DETERMINISTIC_SECRET = base64.urlsafe_b64encode(
    b"test-secret-32-bytes-for-hmac-aa"
).decode()


# --- L1 (EIP-712) ---------------------------------------------------


class TestClobAuthSigner:
    def test_signer_address_is_derived_from_private_key(self) -> None:
        signer = ClobAuthSigner(private_key=DETERMINISTIC_PK)
        assert signer.address == DETERMINISTIC_ADDR

    def test_signer_accepts_unprefixed_private_key(self) -> None:
        signer = ClobAuthSigner(private_key="aa" * 32)
        assert signer.address == DETERMINISTIC_ADDR

    def test_signer_rejects_short_private_key(self) -> None:
        with pytest.raises(ClobAuthError):
            ClobAuthSigner(private_key="0xdead").sign_clob_auth(
                timestamp=DETERMINISTIC_TS, nonce=0,
            )

    def test_eip712_signature_matches_known_vector(self) -> None:
        """Locks the L1 signature against a reference key + clock so any
        future drift in domain name / version / message string is caught.
        """
        signer = ClobAuthSigner(private_key=DETERMINISTIC_PK)
        sig, addr, ts = signer.sign_clob_auth(
            timestamp=DETERMINISTIC_TS, nonce=0,
        )
        assert addr == DETERMINISTIC_ADDR
        assert ts == DETERMINISTIC_TS
        assert sig == EXPECTED_L1_SIG

    def test_clob_constants_unchanged(self) -> None:
        # If any of these constants drift the L1 vector above will fail
        # too — but locking them explicitly makes the failure clearer.
        assert CLOB_DOMAIN_NAME == "ClobAuthDomain"
        assert CLOB_DOMAIN_VERSION == "1"
        assert DEFAULT_CHAIN_ID == 137
        assert CLOB_AUTH_MESSAGE == (
            "This message attests that I control the given wallet"
        )


class TestBuildL1Headers:
    def test_l1_headers_have_required_keys_only(self) -> None:
        signer = ClobAuthSigner(private_key=DETERMINISTIC_PK)
        h = build_l1_headers(signer, timestamp=DETERMINISTIC_TS, nonce=0)
        assert set(h.keys()) == {
            "POLY_ADDRESS",
            "POLY_SIGNATURE",
            "POLY_TIMESTAMP",
            "POLY_NONCE",
        }
        assert h["POLY_ADDRESS"] == DETERMINISTIC_ADDR
        assert h["POLY_TIMESTAMP"] == str(DETERMINISTIC_TS)
        assert h["POLY_NONCE"] == "0"
        assert h["POLY_SIGNATURE"] == EXPECTED_L1_SIG

    def test_nonce_bumps_change_signature(self) -> None:
        signer = ClobAuthSigner(private_key=DETERMINISTIC_PK)
        h0 = build_l1_headers(signer, timestamp=DETERMINISTIC_TS, nonce=0)
        h1 = build_l1_headers(signer, timestamp=DETERMINISTIC_TS, nonce=1)
        assert h0["POLY_SIGNATURE"] != h1["POLY_SIGNATURE"]
        assert h1["POLY_NONCE"] == "1"


# --- L2 (HMAC) ------------------------------------------------------


class TestHMACSignature:
    def test_hmac_matches_known_vector(self) -> None:
        sig = build_hmac_signature(
            secret=DETERMINISTIC_SECRET,
            timestamp=DETERMINISTIC_TS,
            method="POST",
            path="/order",
            body='{"a":1}',
        )
        # Captured live from the implementation; fail-loud on drift.
        assert sig == "gkIXW1DbVAgR5Eo2M4QUfqa2WXbMRKckaEVD043fVXM="

    def test_hmac_method_case_normalized(self) -> None:
        a = build_hmac_signature(
            secret=DETERMINISTIC_SECRET,
            timestamp=DETERMINISTIC_TS,
            method="post",
            path="/order",
            body="",
        )
        b = build_hmac_signature(
            secret=DETERMINISTIC_SECRET,
            timestamp=DETERMINISTIC_TS,
            method="POST",
            path="/order",
            body="",
        )
        assert a == b

    def test_hmac_body_difference_changes_signature(self) -> None:
        a = build_hmac_signature(
            secret=DETERMINISTIC_SECRET,
            timestamp=DETERMINISTIC_TS,
            method="POST",
            path="/order",
            body='{"a":1}',
        )
        b = build_hmac_signature(
            secret=DETERMINISTIC_SECRET,
            timestamp=DETERMINISTIC_TS,
            method="POST",
            path="/order",
            body='{"a":2}',
        )
        assert a != b

    def test_hmac_rejects_non_base64_secret(self) -> None:
        with pytest.raises(ClobAuthError):
            build_hmac_signature(
                secret="!!!not-valid-base64!!!",
                timestamp=DETERMINISTIC_TS,
                method="POST",
                path="/order",
                body="",
            )

    def test_hmac_tolerates_unpadded_b64(self) -> None:
        unpadded = DETERMINISTIC_SECRET.rstrip("=")
        a = build_hmac_signature(
            secret=DETERMINISTIC_SECRET,
            timestamp=DETERMINISTIC_TS,
            method="POST",
            path="/order",
            body="",
        )
        b = build_hmac_signature(
            secret=unpadded,
            timestamp=DETERMINISTIC_TS,
            method="POST",
            path="/order",
            body="",
        )
        assert a == b


class TestBuildL2Headers:
    def test_l2_headers_match_polymarket_spec(self) -> None:
        h = build_l2_headers(
            api_key="abc",
            api_secret=DETERMINISTIC_SECRET,
            passphrase="pp",
            address=DETERMINISTIC_ADDR,
            method="POST",
            path="/order",
            body='{"a":1}',
            timestamp=DETERMINISTIC_TS,
        )
        assert set(h.keys()) == {
            "POLY_ADDRESS",
            "POLY_SIGNATURE",
            "POLY_TIMESTAMP",
            "POLY_API_KEY",
            "POLY_PASSPHRASE",
        }
        assert h["POLY_API_KEY"] == "abc"
        assert h["POLY_PASSPHRASE"] == "pp"
        assert h["POLY_TIMESTAMP"] == str(DETERMINISTIC_TS)
        # Signature must equal the standalone HMAC for the same inputs
        expected = build_hmac_signature(
            secret=DETERMINISTIC_SECRET,
            timestamp=DETERMINISTIC_TS,
            method="POST",
            path="/order",
            body='{"a":1}',
        )
        assert h["POLY_SIGNATURE"] == expected


# --- Builder headers ------------------------------------------------


class TestBuildBuilderHeaders:
    def test_builder_headers_required_keys(self) -> None:
        h = build_builder_headers(
            builder_api_key="bk",
            builder_api_secret=DETERMINISTIC_SECRET,
            builder_passphrase="bp",
            method="POST",
            path="/order",
            body='{}',
            timestamp=DETERMINISTIC_TS,
        )
        assert set(h.keys()) == {
            "POLY_BUILDER_API_KEY",
            "POLY_BUILDER_TIMESTAMP",
            "POLY_BUILDER_PASSPHRASE",
            "POLY_BUILDER_SIGNATURE",
        }
        assert h["POLY_BUILDER_API_KEY"] == "bk"
        assert h["POLY_BUILDER_PASSPHRASE"] == "bp"
        assert h["POLY_BUILDER_TIMESTAMP"] == str(DETERMINISTIC_TS)

    def test_builder_signature_matches_l2_hmac_for_same_inputs(self) -> None:
        h = build_builder_headers(
            builder_api_key="bk",
            builder_api_secret=DETERMINISTIC_SECRET,
            builder_passphrase="bp",
            method="POST",
            path="/order",
            body='{}',
            timestamp=DETERMINISTIC_TS,
        )
        expected = build_hmac_signature(
            secret=DETERMINISTIC_SECRET,
            timestamp=DETERMINISTIC_TS,
            method="POST",
            path="/order",
            body='{}',
        )
        assert h["POLY_BUILDER_SIGNATURE"] == expected
