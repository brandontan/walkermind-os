"""WARP/root-admin-backfill-trigger — admin endpoint that runs backfill_deposit_wallets.

Pins the contract of the new POST /admin/backfill-deposit-wallets endpoint:

* admin-gated (the _require_admin dependency is exercised in test_admin_console);
* delegates to wallet.deposit_wallet.backfill_deposit_wallets (idempotent,
  sequential, no fund movement);
* surfaces the {scanned, filled, skipped} summary + an ``ok`` flag that turns
  False ONLY on the SDK-abort shape (scanned>0, filled==0, skipped==0) so an
  empty fill from a broken runtime is not mistaken for "nothing to do";
* audits the run.

Hermetic — patches the backfill function + audit; no DB, no network, no SDK.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from projects.polymarket.crusaderbot.webtrader.backend import router as r

_BACKFILL = (
    "projects.polymarket.crusaderbot.wallet.deposit_wallet.backfill_deposit_wallets"
)


def _run(summary: dict) -> dict:
    with (
        patch(_BACKFILL, new=AsyncMock(return_value=summary)),
        patch.object(r.audit, "write", new=AsyncMock()) as mock_audit,
    ):
        out = asyncio.run(
            r.admin_backfill_deposit_wallets({"user_id": str(uuid4())})
        )
    mock_audit.assert_awaited_once()
    return out


def test_backfill_happy_path_ok_true_and_audited() -> None:
    out = _run({"scanned": 3, "filled": 3, "skipped": 0})
    assert out == {"scanned": 3, "filled": 3, "skipped": 0, "ok": True}


def test_backfill_partial_skips_is_ok() -> None:
    out = _run({"scanned": 4, "filled": 3, "skipped": 1})
    assert out["ok"] is True
    assert out["filled"] == 3 and out["skipped"] == 1


def test_backfill_nothing_to_do_is_ok() -> None:
    # All rows already filled — scanned 0. Not an error.
    out = _run({"scanned": 0, "filled": 0, "skipped": 0})
    assert out["ok"] is True


def test_backfill_sdk_abort_shape_is_not_ok() -> None:
    # Resolver aborted at the first row (Polymarket SDK unavailable): scanned
    # advanced but nothing filled and nothing skipped.
    out = _run({"scanned": 1, "filled": 0, "skipped": 0})
    assert out["ok"] is False


def test_backfill_audits_the_summary_payload() -> None:
    summary = {"scanned": 2, "filled": 2, "skipped": 0}
    with (
        patch(_BACKFILL, new=AsyncMock(return_value=summary)),
        patch.object(r.audit, "write", new=AsyncMock()) as mock_audit,
    ):
        asyncio.run(r.admin_backfill_deposit_wallets({"user_id": str(uuid4())}))
    kwargs = mock_audit.await_args.kwargs
    assert kwargs["action"] == "admin_backfill_deposit_wallets"
    assert kwargs["payload"] == summary
