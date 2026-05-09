#!/usr/bin/env python3
"""Mainnet preflight checklist for the Polymarket CLOB live lane.

Run BEFORE flipping any activation guard. Validates:

    1. Activation guards     -- ENABLE_LIVE_TRADING / EXECUTION_PATH_VALIDATED
                                / CAPITAL_MODE_CONFIRMED are all True.
    2. Polymarket secrets    -- API key + secret + passphrase + private key
                                are present (values never logged).
    3. USE_REAL_CLOB toggle  -- True in the runtime env supplied to this
                                script. CI defaults are NOT mutated.
    4. EIP-712 signing       -- signs one ClobAuth payload locally; no
                                network call is made.
    5. HMAC headers          -- builds one L2 auth header tuple locally;
                                no network call is made.

Exit code:
    0  every check PASS
    1  at least one check FAIL

Usage:
    python -m projects.polymarket.crusaderbot.scripts.mainnet_preflight

Safety:
    * No broker call is made under any branch.
    * No environment variable is mutated.
    * Secret values are NEVER printed; only the key name + PASS/FAIL.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..config import Settings, get_settings
from ..integrations.clob.auth import (
    ClobAuthSigner,
    build_l2_headers,
)
from ..integrations.clob.exceptions import ClobAuthError


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str

    def line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name} -- {self.detail}"


def _check_activation_guards(s: Settings) -> CheckResult:
    """Every activation guard must be True before the operator can flip
    USE_REAL_CLOB safely. The capital-safety contract from CLAUDE.md.
    """
    missing: list[str] = []
    if not s.ENABLE_LIVE_TRADING:
        missing.append("ENABLE_LIVE_TRADING")
    if not s.EXECUTION_PATH_VALIDATED:
        missing.append("EXECUTION_PATH_VALIDATED")
    if not s.CAPITAL_MODE_CONFIRMED:
        missing.append("CAPITAL_MODE_CONFIRMED")
    if missing:
        return CheckResult(
            name="activation_guards",
            passed=False,
            detail="not SET: " + ", ".join(missing),
        )
    return CheckResult(
        name="activation_guards",
        passed=True,
        detail="all three guards SET",
    )


def _check_polymarket_secrets(s: Settings) -> CheckResult:
    """Confirm every credential the live lane needs is present.

    Values are never read into the result detail -- only key names. The
    private key check accepts both names supported by the adapter
    (``POLYMARKET_PRIVATE_KEY`` is the canonical name; legacy deployments
    may still use ``PRIVATE_KEY``).
    """
    required = {
        "POLYMARKET_API_KEY": s.POLYMARKET_API_KEY,
        "POLYMARKET_API_SECRET": s.POLYMARKET_API_SECRET,
        "POLYMARKET_API_PASSPHRASE": (
            s.POLYMARKET_API_PASSPHRASE or s.POLYMARKET_PASSPHRASE
        ),
        "POLYMARKET_PRIVATE_KEY": s.POLYMARKET_PRIVATE_KEY,
    }
    missing = [name for name, val in required.items() if not val]
    if missing:
        return CheckResult(
            name="polymarket_secrets",
            passed=False,
            detail="not SET: " + ", ".join(missing),
        )
    return CheckResult(
        name="polymarket_secrets",
        passed=True,
        detail="all four secrets SET",
    )


def _check_use_real_clob(s: Settings) -> CheckResult:
    """``USE_REAL_CLOB`` must be True in the supplied runtime env.

    Default in the codebase remains False (paper-safe). This check
    confirms the operator has flipped it in the runtime config /
    environment they intend to launch with -- preflight is the moment
    to catch the mismatch, not after a paper order arrives at the
    broker.
    """
    if not s.USE_REAL_CLOB:
        return CheckResult(
            name="use_real_clob",
            passed=False,
            detail="USE_REAL_CLOB is False in runtime env",
        )
    return CheckResult(
        name="use_real_clob",
        passed=True,
        detail="USE_REAL_CLOB=True",
    )


def _check_eip712_sign(s: Settings) -> CheckResult:
    """Sign one ClobAuth EIP-712 payload locally. No broker call.

    Uses the configured ``POLYMARKET_PRIVATE_KEY``. A failure here means
    the key is malformed or eth_account can't process it -- both are
    boot blockers and must be caught before any order submission.
    """
    if not s.POLYMARKET_PRIVATE_KEY:
        return CheckResult(
            name="eip712_sign",
            passed=False,
            detail="POLYMARKET_PRIVATE_KEY not SET",
        )
    try:
        signer = ClobAuthSigner(private_key=s.POLYMARKET_PRIVATE_KEY)
        sig, addr, ts = signer.sign_clob_auth(timestamp=int(time.time()))
    except ClobAuthError as exc:
        return CheckResult(
            name="eip712_sign",
            passed=False,
            detail=f"signing failed: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 -- final safety net
        return CheckResult(
            name="eip712_sign",
            passed=False,
            detail=f"unexpected signing error: {type(exc).__name__}: {exc}",
        )
    if not sig.startswith("0x") or not addr.startswith("0x"):
        return CheckResult(
            name="eip712_sign",
            passed=False,
            detail="signature/address shape unexpected",
        )
    return CheckResult(
        name="eip712_sign",
        passed=True,
        detail=f"signed payload at ts={ts} addr={addr}",
    )


def _check_hmac_headers(s: Settings) -> CheckResult:
    """Build one L2 HMAC header set locally. No broker call.

    Confirms the urlsafe-base64 secret decodes cleanly and the HMAC
    primitive runs end-to-end. A bad secret would raise inside the
    helper -- preflight catches it before live trading.
    """
    api_key = s.POLYMARKET_API_KEY
    api_secret = s.POLYMARKET_API_SECRET
    passphrase = s.POLYMARKET_API_PASSPHRASE or s.POLYMARKET_PASSPHRASE
    private_key = s.POLYMARKET_PRIVATE_KEY
    if not (api_key and api_secret and passphrase and private_key):
        return CheckResult(
            name="hmac_headers",
            passed=False,
            detail="prerequisite secret missing",
        )
    try:
        signer = ClobAuthSigner(private_key=private_key)
        headers = build_l2_headers(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            address=signer.address,
            method="POST",
            path="/order",
            body="",
            timestamp=int(time.time()),
        )
    except ClobAuthError as exc:
        return CheckResult(
            name="hmac_headers",
            passed=False,
            detail=f"hmac build failed: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="hmac_headers",
            passed=False,
            detail=f"unexpected hmac error: {type(exc).__name__}: {exc}",
        )
    required = {
        "POLY_ADDRESS",
        "POLY_SIGNATURE",
        "POLY_TIMESTAMP",
        "POLY_API_KEY",
        "POLY_PASSPHRASE",
    }
    missing = required - set(headers.keys())
    if missing:
        return CheckResult(
            name="hmac_headers",
            passed=False,
            detail=f"header tuple missing keys: {sorted(missing)}",
        )
    return CheckResult(
        name="hmac_headers",
        passed=True,
        detail="L2 header set built (5 keys)",
    )


# Ordered list -- keep activation_guards FIRST so an unsafe runtime
# fails loudly before secrets are even probed. The remaining checks are
# independent; we run them all so the operator gets a single PASS/FAIL
# report instead of a fix-one-then-rerun loop.
DEFAULT_CHECKS: tuple[Callable[[Settings], CheckResult], ...] = (
    _check_activation_guards,
    _check_polymarket_secrets,
    _check_use_real_clob,
    _check_eip712_sign,
    _check_hmac_headers,
)


def run_preflight(
    *,
    settings: Optional[Settings] = None,
    checks: Optional[tuple[Callable[[Settings], CheckResult], ...]] = None,
) -> tuple[bool, list[CheckResult]]:
    """Run every check and return ``(all_passed, results)``.

    ``settings`` is injectable so unit tests can pass a synthesised
    ``Settings`` instance without poking ``os.environ``. ``checks`` is
    injectable for the same reason -- tests can pin a single failing
    check to assert the exit-1 path.
    """
    s = settings or get_settings()
    selected = checks or DEFAULT_CHECKS
    results = [check(s) for check in selected]
    return all(r.passed for r in results), results


def main() -> int:
    print("CrusaderBot mainnet preflight")
    print("-" * 50)
    all_passed, results = run_preflight()
    for r in results:
        print(r.line())
    print("-" * 50)
    if all_passed:
        print("RESULT: PASS -- safe to proceed with operator activation flip.")
        return 0
    print("RESULT: FAIL -- do NOT activate live trading until checks pass.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
