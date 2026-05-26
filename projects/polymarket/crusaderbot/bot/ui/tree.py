"""Telegram MarkdownV2 message helpers — MVP v2 (WARP/telegram-ux-v2).

Format rules for Telegram MarkdownV2 parse mode:
- *bold* for headers and section titles
- `value` for inline values (monospace)
- ```block``` for 2+ numerical values (monospace aligned)
- _italic_ for CTA prompts
- · (middle dot) as row separator — clean on all mobile clients
- ─ repeated as section divider — safe unicode
- Special chars must be escaped with \\ outside formatting markers:
  _ * [ ] ( ) ~ ` > # + - = | { } . !
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

# Section divider — light box chars, renders cleanly inline
DIV = "─" * 28
LIGHT_DIV = "· · · · ·"

# Backwards-compatible aliases
DIVIDER = DIV
CARD_DIVIDER = DIV

# Status constants
STATUS_RUNNING  = "🟢 Running"
STATUS_STOPPED  = "🔴 Stopped"
STATUS_PAUSED   = "🟡 Paused"
STATUS_NOT_SET  = "⚪ Not Set"
STATUS_SYNCING  = "🔵 Syncing"
PAPER           = "📝 Paper Trading"
LIVE            = "💸 Live Trading"
LOCKED          = "🔒 Locked"

# Characters that must be escaped in MarkdownV2 raw text
_MDV2_SPECIAL = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')


def md_v2_escape(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 raw text regions."""
    return _MDV2_SPECIAL.sub(r'\\\1', str(text))


# html_escape kept as alias for backward compat with any callers that import it
html_escape = md_v2_escape


def pnl(amount: float, currency: str = "$") -> str:
    """Format PnL value — output goes inside code spans so no escaping needed."""
    if amount > 0:
        return f"+{currency}{amount:,.2f}"
    if amount < 0:
        return f"-{currency}{abs(amount):,.2f}"
    return f"={currency}0.00"


def title(text: str) -> str:
    """Bold screen title: *text*"""
    return f"*{md_v2_escape(text)}*"


def leaf(label: str, value: str, last: bool = False) -> str:
    """Single key·value row with inline code value."""
    return f"{md_v2_escape(label)}: `{value}`"


def section(label: str, rows: Sequence[tuple[str, str]], last: bool = False) -> str:
    """Bold section header + indented key·value rows."""
    lines: list[str] = [f"*{md_v2_escape(label)}*"]
    for sub_label, sub_value in rows:
        lines.append(f"  · {md_v2_escape(sub_label)}: `{sub_value}`")
    return "\n".join(lines)


def pre_block(rows: Sequence[tuple[str, str]]) -> str:
    """Monospaced code block for aligned numerical data.

    Inside ``` blocks Telegram renders raw text without MarkdownV2 parsing,
    so no escaping is needed for the values.
    """
    if not rows:
        return ""
    max_label = max(len(str(r[0])) for r in rows)
    lines = []
    for label, value in rows:
        lines.append(f"{str(label):<{max_label}}  {str(value)}")
    return "```\n" + "\n".join(lines) + "\n```"


def nested(label: str, lines_iter: Iterable[str], last: bool = False) -> str:
    """Bold header + bullet list."""
    out: list[str] = [f"*{md_v2_escape(label)}*"]
    for line in lines_iter:
        out.append(f"  • {md_v2_escape(line)}")
    return "\n".join(out)


def divider() -> str:
    return DIV


def cta(text: str) -> str:
    """Italic call-to-action prompt."""
    return f"_{md_v2_escape(text)}_"


def join_blocks(blocks: Iterable[str], spacer: str = "\n") -> str:
    parts = [b for b in blocks if b]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return parts[0] + "\n\n" + "\n".join(parts[1:])
