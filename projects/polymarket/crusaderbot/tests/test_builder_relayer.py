"""Builder relayer foundation — credential gating + clean unavailable errors.

This module is purely a foundation layer: no active code path consumes it yet.
The tests pin the contract that other phases will rely on:
  * unconfigured ⇒ is_relayer_configured()=False and factory raises BuilderRelayerUnavailable
  * configured   ⇒ factory returns real SDK objects (no monkeypatching of SDK internals)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from projects.polymarket.crusaderbot.integrations import builder_relayer as br


class _UnconfiguredSettings:
    USE_BUILDER_RELAYER = False
    POLY_BUILDER_API_KEY = None
    POLY_BUILDER_SECRET = None
    POLY_BUILDER_PASSPHRASE = None
    POLY_RELAYER_URL = "https://relayer-v2.polymarket.com"


class _ConfiguredSettings:
    USE_BUILDER_RELAYER = True
    POLY_BUILDER_API_KEY = "key"
    POLY_BUILDER_SECRET = "secret"
    POLY_BUILDER_PASSPHRASE = "pass"
    POLY_RELAYER_URL = "https://relayer-v2.polymarket.com"


class _PartialSettings:
    """Toggle on but creds missing — must still report unconfigured."""
    USE_BUILDER_RELAYER = True
    POLY_BUILDER_API_KEY = "key"
    POLY_BUILDER_SECRET = None
    POLY_BUILDER_PASSPHRASE = "pass"
    POLY_RELAYER_URL = "https://relayer-v2.polymarket.com"


def test_relayer_unconfigured_by_default() -> None:
    with patch.object(br, "get_settings", return_value=_UnconfiguredSettings()):
        assert br.is_relayer_configured() is False


def test_relayer_partial_credentials_count_as_unconfigured() -> None:
    with patch.object(br, "get_settings", return_value=_PartialSettings()):
        assert br.is_relayer_configured() is False


def test_relayer_fully_configured_is_detected() -> None:
    with patch.object(br, "get_settings", return_value=_ConfiguredSettings()):
        assert br.is_relayer_configured() is True


def test_build_builder_config_raises_when_unconfigured() -> None:
    with patch.object(br, "get_settings", return_value=_UnconfiguredSettings()):
        with pytest.raises(br.BuilderRelayerUnavailable, match="POLY_BUILDER"):
            br.build_builder_config()


def test_make_relayer_client_raises_without_signer() -> None:
    with patch.object(br, "get_settings", return_value=_ConfiguredSettings()):
        with pytest.raises(br.BuilderRelayerUnavailable, match="signer key"):
            br.make_relayer_client("")


def test_make_relayer_client_raises_when_unconfigured() -> None:
    with patch.object(br, "get_settings", return_value=_UnconfiguredSettings()):
        with pytest.raises(br.BuilderRelayerUnavailable):
            br.make_relayer_client("0xabc")


def test_build_builder_config_returns_sdk_object_when_configured() -> None:
    pytest.importorskip("py_builder_signing_sdk")
    with patch.object(br, "get_settings", return_value=_ConfiguredSettings()):
        cfg = br.build_builder_config()
    # SDK type — assert by class name to avoid binding the test to the import path.
    assert type(cfg).__name__ == "BuilderConfig"


def test_make_relayer_client_returns_sdk_object_when_configured() -> None:
    pytest.importorskip("py_builder_relayer_client")
    with patch.object(br, "get_settings", return_value=_ConfiguredSettings()):
        client = br.make_relayer_client(
            "0x" + "1" * 64  # syntactically valid 32-byte hex pk; never broadcast
        )
    assert type(client).__name__ == "RelayClient"


def test_relayer_sdk_importable_returns_bool() -> None:
    # The probe must never raise regardless of credential state and must
    # return a bool that matches actual SDK availability — not hard-pinned
    # True, so the test stays honest if the dep is ever removed.
    import importlib.util
    expected = (
        importlib.util.find_spec("py_builder_relayer_client") is not None
        and importlib.util.find_spec("py_builder_signing_sdk") is not None
    )
    assert br.relayer_sdk_importable() is expected
