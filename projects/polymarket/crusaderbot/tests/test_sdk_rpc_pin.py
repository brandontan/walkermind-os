"""SDK RPC pin (WARP/root-sdk-rpc-pin).

The polymarket SDK defaults its on-chain deposit-wallet factory check to a
free third-party endpoint (``PRODUCTION.rpc_url = https://polygon.drpc.org``).
From the Fly production machine that endpoint throttles/fails — the
2026-06-11 admin backfill returned ``scanned 6, filled 0, skipped 6`` while
the configured RPC was healthy. Every ``AsyncSecureClient`` in this codebase
must do its chain reads through the operator-configured ``POLYGON_RPC_URL``.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from projects.polymarket.crusaderbot.integrations.clob import sdk_env

_CLOB_DIR = Path(__file__).resolve().parents[1] / "integrations" / "clob"


def test_production_environment_pins_rpc_to_settings():
    """The helper swaps ONLY rpc_url; every Polymarket service URL and the
    wallet-derivation constants stay byte-identical to the SDK's own values."""
    polymarket = pytest.importorskip("polymarket")  # noqa: F841
    from polymarket.environments import PRODUCTION

    fake = SimpleNamespace(POLYGON_RPC_URL="https://rpc.example/v2/OURKEY123")
    with patch.object(sdk_env, "get_settings", return_value=fake):
        env = sdk_env.production_environment()
    assert env.rpc_url == "https://rpc.example/v2/OURKEY123"
    assert env.rpc_url != PRODUCTION.rpc_url
    assert env.clob_url == PRODUCTION.clob_url
    assert env.relayer_url == PRODUCTION.relayer_url
    assert env.chain_id == PRODUCTION.chain_id
    assert env.wallet_derivation == PRODUCTION.wallet_derivation


def test_every_async_secure_client_create_passes_pinned_environment():
    """Source pin: any ``AsyncSecureClient.create(...)`` call in
    integrations/clob must carry ``environment=production_environment()`` — a
    new call site that forgets the pin reintroduces the third-party-RPC
    dependency silently. AST-based (Gemini #1765) so formatting, line splits
    and docstring mentions can never produce false results."""
    offenders: list[str] = []
    for py in _CLOB_DIR.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=py.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "AsyncSecureClient"
                and func.attr == "create"
            ):
                continue
            has_pin = any(
                kw.arg == "environment"
                and isinstance(kw.value, ast.Call)
                and isinstance(kw.value.func, ast.Name)
                and kw.value.func.id == "production_environment"
                for kw in node.keywords
            )
            if not has_pin:
                offenders.append(f"{py.name}:{node.lineno}")
    assert not offenders, (
        "AsyncSecureClient.create call(s) missing the RPC-pinned environment: "
        f"{offenders}"
    )


@pytest.mark.asyncio
async def test_resolve_deposit_wallet_builds_client_with_pinned_env(monkeypatch):
    """The backfill resolve path (the one that failed 6/6 in prod) passes the
    pinned environment object through to the SDK client build."""
    from projects.polymarket.crusaderbot.integrations.clob import user_client as uc

    captured: dict = {}

    class _FakeSC:
        wallet = "0x" + "ab" * 20

        @classmethod
        async def create(cls, **kwargs):
            captured.update(kwargs)
            return cls()

        async def close(self):
            return None

    import polymarket
    monkeypatch.setattr(polymarket, "AsyncSecureClient", _FakeSC)
    fake = SimpleNamespace(POLYGON_RPC_URL="https://rpc.example/v2/PINNED")
    monkeypatch.setattr(sdk_env, "get_settings", lambda: fake)

    wallet = await uc.resolve_deposit_wallet("0x" + "11" * 32)
    assert wallet == "0x" + "ab" * 20
    assert captured["environment"].rpc_url == "https://rpc.example/v2/PINNED"
