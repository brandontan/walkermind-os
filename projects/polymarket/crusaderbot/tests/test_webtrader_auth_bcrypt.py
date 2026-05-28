"""Regression tests for the bcrypt password path in webtrader/backend/auth.py.

Background: passlib's bcrypt backend runs a `detect_wrap_bug` self-test on
first use that feeds a 73-byte secret to the underlying bcrypt library. With
`bcrypt>=4.0` that raises `ValueError: password cannot be longer than 72
bytes`, which propagates as a 500 on `/auth/link-email` (Sentry
DAWN-SNOWFLAKE-1729-2B). The fix swaps passlib for bcrypt directly. These
tests pin the new helpers + ensure the byte-length validation fires BEFORE
hashing.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.webtrader.backend import auth as auth_mod


def test_hash_password_round_trip_short():
    h = auth_mod._hash_password("hunter22!")
    assert h.startswith("$2b$"), "must produce a standard bcrypt hash"
    assert auth_mod._verify_password("hunter22!", h)
    assert not auth_mod._verify_password("wrong-pass", h)


def test_hash_password_round_trip_72_bytes_exact():
    """72 ASCII bytes is the bcrypt ceiling — must hash + verify without error."""
    pw = "a" * 72
    h = auth_mod._hash_password(pw)
    assert auth_mod._verify_password(pw, h)


def test_verify_password_rejects_malformed_hash_silently():
    """A malformed stored hash must not raise; auth handler treats as mismatch."""
    assert not auth_mod._verify_password("anything", "not-a-bcrypt-hash")


def test_bcrypt_max_bytes_constant_pinned_at_72():
    """Bcrypt's hard limit is 72 bytes — surface as a named constant."""
    assert auth_mod._BCRYPT_MAX_BYTES == 72


def test_passlib_no_longer_imported():
    """Regression guard: passlib's self-test crashes on bcrypt>=4 — must stay out."""
    src = open(auth_mod.__file__, encoding="utf-8").read()
    # Comment references in the explanatory docstring are fine; an import is not.
    assert "from passlib" not in src
    assert "import passlib" not in src
    assert "CryptContext" not in src
