"""Centralized UI formatting blocks for Telegram premium views."""
from __future__ import annotations

from typing import Iterable

_LABEL_WIDTH: int = 14
_SEPARATOR = "━━━━━━━━━━━━━━━"
_NULL = "—"


def _safe_text(value: object) -> str:
    if value is None:
        return _NULL
    if isinstance(value, str):
        text = value.strip()
        return _NULL if not text or text.replace("/", "").upper() == "NA" else text
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    text = str(value).strip()
    return _NULL if not text or text.replace("/", "").upper() == "NA" else text


def row(label: str, value: object) -> str:
    """Render one aligned key-value row."""
    left = label.strip()[:_LABEL_WIDTH].ljust(_LABEL_WIDTH)
    return f"{left} {_safe_text(value)}"


def section(title: str, rows: list[str]) -> str:
    """Render one section with a premium separator and no tree connectors."""
    safe_rows = rows or [row("Status", _NULL)]
    return "\n".join([str(title).strip(), *safe_rows, _SEPARATOR])


def insight(text: object) -> str:
    """Render one compact insight line."""
    return section("🧠 Insight", [row("Note", text)])


def format_position_lines(lines: Iterable[str]) -> list[str]:
    """Convert arbitrary position lines into safe renderable rows."""
    rendered = [str(line).strip() for line in lines if str(line).strip()]
    return rendered or [_NULL]


# Backward-compatible aliases for existing callers.
format_row = row
format_block = section
format_insight = insight
