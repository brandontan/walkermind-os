"""Regression pin for the HOME-screen crash hotfix.

Production WebTrader HOME crashed with "Cannot read properties of undefined
(reading 'bg')": HeroCard's RiskTag did `RISK_COLOR[risk]` where risk came from
a backend string cast to RiskLevel. A `custom` risk_profile (a real profile in
this system) is not in the {safe,balanced,aggressive} map → undefined → `.bg`
crash → whole screen down via the ErrorBoundary.

This pins the defensive fallback so any unmapped risk value can never crash.
Source inspection only (frontend has no JS unit-test runner).
"""
from __future__ import annotations

import pathlib

_HERO = (
    pathlib.Path(__file__).resolve().parent.parent
    / "webtrader/frontend/src/components/HeroCard.tsx"
)


def test_risk_tag_has_color_fallback() -> None:
    src = _HERO.read_text(encoding="utf-8")
    assert "RISK_COLOR[risk] ?? RISK_COLOR.balanced" in src, (
        "RiskTag must fall back to a known color so an unmapped risk "
        "(e.g. 'custom') never crashes the HOME screen on c.bg"
    )


def test_risk_tag_has_label_fallback() -> None:
    src = _HERO.read_text(encoding="utf-8")
    assert "RISK_LABEL[risk] ??" in src, (
        "RiskTag label must tolerate an unmapped risk value"
    )
