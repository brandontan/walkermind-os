"""Centralized UI formatting blocks for Telegram monospace views."""
from __future__ import annotations

from typing import Iterable

_LABEL_WIDTH: int = 13


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


def format_section(title: str) -> str:
    """Render a section header line."""
    return f"• {title.strip().upper()}"


def format_row(label: str, value: str) -> str:
    """Render one aligned key-value row."""
    left = label.strip().upper()[:_LABEL_WIDTH].ljust(_LABEL_WIDTH)
    return f"{left} { _safe_text(value)}"


def format_block(title: str, rows: list[str]) -> str:
    """Render a section with tree connectors and aligned rows."""
    body: list[str] = [format_section(title)]
    if not rows:
        body.append(f"└ {format_row('STATUS', 'N/A')}")
        return "\n".join(body)

    for idx, row in enumerate(rows):
        prefix = "└" if idx == len(rows) - 1 else "├"
        body.append(f"{prefix} {row}")
    return "\n".join(body)


def format_insight(text: str) -> str:
    """Render one compact insight section."""
    return "\n".join([
        format_section("💡 INSIGHT"),
        f"└ {_safe_text(text)}",
    ])


def format_position_lines(lines: Iterable[str]) -> list[str]:
    """Convert arbitrary position lines into safe renderable rows."""
    rendered = [str(line).strip() for line in lines if str(line).strip()]
    return rendered or ["No open positions"]
