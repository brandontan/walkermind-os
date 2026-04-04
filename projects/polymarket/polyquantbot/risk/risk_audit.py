"""Phase 24 — RiskAudit: Per-trade compliance verification.

Audits every executed trade against the risk rules mandated by CLAUDE.md:

    1. EV > 0            — only positive-expected-value trades are accepted.
    2. Position size     — must not exceed 10% of reported bankroll.
    3. Correlation check — placeholder (always passes; reserved for future use).

Violations are logged as CRITICAL structured events and re-raised so that the
caller can decide whether to halt execution or only log the breach.

Usage::

    auditor = RiskAudit(bankroll=10_000.0)
    ok = auditor.audit_trade(trade)   # True → compliant; raises on violation
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

# Max position size as a fraction of bankroll (10% per CLAUDE.md)
_MAX_POSITION_FRACTION: float = 0.10


class RiskAuditError(Exception):
    """Raised when a trade violates a mandatory risk rule."""


class RiskAudit:
    """Verifies that each trade obeys the mandatory risk rules.

    Args:
        bankroll: Total capital (USD) used to compute the max position limit.
                  Must be > 0.
    """

    def __init__(self, bankroll: float = 10_000.0) -> None:
        if bankroll <= 0.0:
            raise ValueError(f"bankroll must be > 0, got {bankroll}")
        self._bankroll: float = bankroll

    # ── Public ────────────────────────────────────────────────────────────────

    def audit_trade(self, trade: dict[str, Any]) -> bool:
        """Check that ``trade`` complies with all mandatory risk rules.

        Required trade keys:
            ``ev``   — expected value of the trade (float).
            ``size`` — position size in USD (float).

        Args:
            trade: Dict describing the executed trade.

        Returns:
            ``True`` when all checks pass.

        Raises:
            TypeError:       If ``trade`` is not a dict.
            ValueError:      If a required key is missing.
            RiskAuditError:  If any risk rule is violated.
        """
        if not isinstance(trade, dict):
            raise TypeError(f"trade must be a dict, got {type(trade).__name__}")

        for key in ("ev", "size"):
            if key not in trade:
                raise ValueError(f"Trade is missing required key: '{key}'")

        ev: float = float(trade["ev"])
        size: float = float(trade["size"])
        violations: list[str] = []

        # ── Rule 1: Positive EV ───────────────────────────────────────────────
        if ev <= 0.0:
            violations.append(f"EV {ev:.6f} ≤ 0 — trade has non-positive expected value")

        # ── Rule 2: Position size ≤ 10% of bankroll ──────────────────────────
        max_size = self._bankroll * _MAX_POSITION_FRACTION
        if size > max_size:
            violations.append(
                f"size {size:.2f} > max allowed {max_size:.2f} "
                f"({_MAX_POSITION_FRACTION * 100:.0f}% of bankroll {self._bankroll:.2f})"
            )

        # ── Rule 3: Correlation — placeholder (always passes) ─────────────────
        # TODO: implement inter-position correlation guard in a future phase.

        if violations:
            for reason in violations:
                log.critical(
                    "risk_audit_violation",
                    reason=reason,
                    ev=round(ev, 6),
                    size=round(size, 2),
                    bankroll=round(self._bankroll, 2),
                )
            raise RiskAuditError(
                f"Trade violated {len(violations)} risk rule(s): "
                + "; ".join(violations)
            )

        log.debug(
            "risk_audit_passed",
            ev=round(ev, 6),
            size=round(size, 2),
            bankroll=round(self._bankroll, 2),
        )
        return True
