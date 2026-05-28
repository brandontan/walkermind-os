"""Public legal documents — Terms of Service + Privacy Policy.

Serves the markdown files at ``crusaderbot/legal/`` as minimal HTML so
the WebTrader sign-up flow can link to them in a new tab. Single source
of truth: the .md files. Renderer is intentionally conservative — no
client-side fetch, no JS, no external CDN — because legal pages must
load even when the SPA is down or the user has scripts disabled.

Endpoints:
  * ``GET /legal/terms``   — terms-of-service.md
  * ``GET /legal/privacy`` — privacy-policy.md

Anonymous + rate-limit-exempt is intentional: a user reading the ToS
before signing up has no auth context yet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/legal", tags=["legal"])

_LEGAL_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "legal"

_DOCS: Final[dict[str, tuple[str, str]]] = {
    # slug -> (filename, page title)
    "terms": ("terms-of-service.md", "Terms of Service — CrusaderBot"),
    "privacy": ("privacy-policy.md", "Privacy Policy — CrusaderBot"),
}


def _render_markdown(md: str) -> str:
    """Minimal Markdown → HTML for the two legal docs only.

    Supports the subset the legal docs actually use: ``#`` / ``##`` / ``###``
    headings, ordered + unordered lists, ``[text](url)`` links, ``**bold**``,
    ``_italic_``, paragraphs separated by a blank line. Anything richer is
    intentionally NOT supported — these are static legal pages, not a CMS.
    Falls back to escaping any unhandled character so untrusted content
    cannot inject HTML if the .md is ever edited externally.
    """
    import html
    import re

    lines = md.splitlines()
    out: list[str] = []
    in_ul = False
    in_ol = False
    paragraph: list[str] = []

    def _flush_paragraph() -> None:
        if not paragraph:
            return
        text = " ".join(paragraph).strip()
        if text:
            out.append(f"<p>{_inline(text)}</p>")
        paragraph.clear()

    def _close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def _inline(s: str) -> str:
        # Escape first, then re-introduce the limited inline syntax we accept.
        s = html.escape(s, quote=False)
        # Links — only http(s) and relative paths (/legal/...) allowed.
        def _link_sub(m: re.Match[str]) -> str:
            text, url = m.group(1), m.group(2)
            safe = url.startswith("http://") or url.startswith("https://") or url.startswith("/")
            return (
                f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'
                if safe
                else html.escape(m.group(0), quote=False)
            )
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_sub, s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<em>\1</em>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            _flush_paragraph()
            _close_lists()
            continue
        h = re.match(r"^(#{1,3})\s+(.+)$", line)
        if h:
            _flush_paragraph()
            _close_lists()
            level = len(h.group(1))
            out.append(f"<h{level}>{_inline(h.group(2).strip())}</h{level}>")
            continue
        ol = re.match(r"^\s*\d+\.\s+(.+)$", line)
        ul = re.match(r"^\s*[-*]\s+(.+)$", line)
        if ol:
            _flush_paragraph()
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline(ol.group(1).strip())}</li>")
            continue
        if ul:
            _flush_paragraph()
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(ul.group(1).strip())}</li>")
            continue
        _close_lists()
        paragraph.append(line)
    _flush_paragraph()
    _close_lists()
    return "\n".join(out)


_PAGE_TEMPLATE: Final[str] = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    margin: 0;
    padding: 32px 20px 64px;
    background: #060B16;
    color: #E5EAF2;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    line-height: 1.55;
  }}
  main {{ max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 24px; color: #F5C842; margin: 0 0 16px; }}
  h2 {{ font-size: 18px; color: #F5C842; margin: 32px 0 8px; }}
  h3 {{ font-size: 15px; color: #C8D0DC; margin: 20px 0 6px; }}
  p, li {{ font-size: 14px; color: #C8D0DC; }}
  ul, ol {{ padding-left: 22px; }}
  li {{ margin: 4px 0; }}
  a {{ color: #F5C842; }}
  code {{
    background: #0E1830;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 13px;
  }}
  strong {{ color: #E5EAF2; }}
  hr {{ border: 0; border-top: 1px solid #1B2741; margin: 24px 0; }}
  footer {{
    margin-top: 40px;
    padding-top: 16px;
    border-top: 1px solid #1B2741;
    font-size: 12px;
    color: #6B7689;
  }}
</style>
</head>
<body>
<main>
{body}
<footer>CrusaderBot · part of WalkerMind OS</footer>
</main>
</body>
</html>
"""


@router.get("/{slug}", response_class=HTMLResponse)
async def get_legal_doc(slug: str) -> HTMLResponse:
    """Serve one of the two known legal docs as HTML."""
    entry = _DOCS.get(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="legal doc not found")
    filename, title = entry
    path = _LEGAL_DIR / filename
    try:
        md = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="legal doc missing on disk")
    body = _render_markdown(md)
    return HTMLResponse(content=_PAGE_TEMPLATE.format(title=title, body=body))
