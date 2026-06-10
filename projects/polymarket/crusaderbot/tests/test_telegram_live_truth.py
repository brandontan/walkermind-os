"""WARP/root-telegram-live-truth — gate-7 2FA truth sync + /wallet command.

Pins the readiness-matrix row 8(b)/(c) fixes:

* the gate-7 fix hint points users at the SHIPPED self-serve web 2FA flow
  (#1737) instead of telling them to contact an admin;
* the stale "does not yet exist" claim is gone from live_checklist;
* the /wallet command the deposit-gate hint references is actually
  registered in the dispatcher (source-regex layer, same pattern as
  tests/test_paper_default_invariant.py — the dispatcher module itself
  is too heavy to import hermetically).
"""
from __future__ import annotations

import re
from pathlib import Path

from projects.polymarket.crusaderbot.domain.activation.live_checklist import (
    GATE_ACTIVE_SUBACCOUNT,
    GATE_FIX_HINTS,
    GATE_TWO_FACTOR_SETUP,
)

_DISPATCHER_SRC = (
    Path(__file__).parents[1] / "bot" / "dispatcher.py"
).read_text(encoding="utf-8")


class TestGate7TwoFactorTruth:
    def test_fix_hint_points_to_shipped_web_flow(self) -> None:
        hint = GATE_FIX_HINTS[GATE_TWO_FACTOR_SETUP]
        assert "WebTrader" in hint
        assert "Settings" in hint
        # The pre-#1737 framing must be gone.
        assert "Contact an admin" not in hint
        assert "until self-serve 2FA ships" not in hint

    def test_module_carries_no_stale_unshipped_claim(self) -> None:
        src = (
            Path(__file__).parents[1] / "domain" / "activation"
            / "live_checklist.py"
        ).read_text(encoding="utf-8")
        assert "does not yet exist" not in src
        # The gate's contract anchor stays: it must keep reading the exact
        # key domain/auth/totp.verify_and_enable writes.
        assert "2fa_enabled:{user_id}" in src


class TestWalletCommandRegistered:
    def test_wallet_command_handler_registered(self) -> None:
        assert re.search(
            r'CommandHandler\(\s*"wallet",\s*wallet_root\s*\)', _DISPATCHER_SRC
        ), "/wallet CommandHandler(wallet_root) not registered in dispatcher"

    def test_deposit_gate_hint_references_a_real_command(self) -> None:
        # The deposit-gate hint has always told users "/wallet → Deposit";
        # this ties the hint to an actually-registered command so the pair
        # cannot drift apart again.
        hint = GATE_FIX_HINTS[GATE_ACTIVE_SUBACCOUNT]
        assert "/wallet" in hint
        assert 'CommandHandler("wallet"' in _DISPATCHER_SRC
