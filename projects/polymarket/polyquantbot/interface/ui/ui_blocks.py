"""Centralized UI formatting blocks for Telegram monospace views."""
from __future__ import annotations

from typing import Iterable

_LABEL_WIDTH: int = 12


def _safe_text(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, float):
            if value.is_integer():
                return f"{int(value):,}"
            return f"{value:,.2f}"
        return f"{value:,}"
    text = str(value).strip()
    return text or "N/A"


def row(label: str, value: str) -> str:
    """Render one strict-alignment key-value row."""
    left = label.strip()[:_LABEL_WIDTH].ljust(_LABEL_WIDTH)
    return f"{left} {_safe_text(value)}"


def section(title: str, rows: list[str]) -> str:
    """Render one section with tree connectors and no extra spacing."""
    body: list[str] = [str(title).strip()]
    if not rows:
        body.append(f"└ {row('Status', 'N/A')}")
        return "\n".join(body)

    for idx, item in enumerate(rows):
        prefix = "└" if idx == len(rows) - 1 else "├"
        body.append(f"{prefix} {item}")
    return "\n".join(body)


def insight(text: str) -> str:
    """Render one compact single-line insight section."""
    return section("Insight", [row("Note", text)])


def format_position_lines(lines: Iterable[str]) -> list[str]:
    """Convert arbitrary position lines into safe renderable rows."""
    rendered = [str(line).strip() for line in lines if str(line).strip()]
    return rendered or ["No open positions"]


# Backward-compatible aliases for existing callers.
format_row = row
format_block = section
format_insight = insight
