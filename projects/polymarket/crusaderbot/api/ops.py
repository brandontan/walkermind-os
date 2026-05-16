"""Operator HTML dashboard at ``GET /ops`` plus kill / resume buttons.

A lightweight, single-page operator console served as inline HTML so it
works from any phone or desktop browser without a JS bundle. The page
auto-refreshes every 30 seconds via ``<meta http-equiv="refresh">``.

Surfaces
--------
GET /ops          single HTML page with system snapshot
POST /ops/kill    flips the kill switch to ACTIVE (pauses new trades)
POST /ops/resume  releases the kill switch (resumes new trades)

The kill / resume actions delegate to ``domain.ops.kill_switch.set_active``
which is the single source of truth shared with the Telegram operator
surface (``/kill`` / ``/resume`` / ``/killswitch``) and the bearer-protected
``/admin/kill`` REST endpoint. Every flip writes one row to
``kill_switch_history`` AND one row to ``audit.log`` (action
``kill_switch_pause`` / ``_resume``) so the full operator timeline is
queryable.

Auth
----
``GET /ops`` is open by design — the read-only dashboard is reachable
from any phone browser during the demo. The POST mutators
(``/ops/kill`` and ``/ops/resume``) are gated by a shared secret read
from ``OPS_SECRET`` via either the ``X-Ops-Token`` header OR the
``?token=<value>`` query / form param so the operator can bookmark
``https://crusaderbot.fly.dev/ops?token=<OPS_SECRET>`` and trigger
kill / resume with one tap on a phone. ``OPS_SECRET`` unset disables
the mutators (503); missing / wrong token returns 403.

DEFERRED (tracked in PROJECT_STATE KNOWN ISSUES, not a blocker for the
paper-mode public beta): full auth hardening — per-operator login, token
rotation, removing the token from the URL. Rationale: paper mode moves no
real capital, the mutators are timing-safe secret-gated, every flip is
audited (now with a ``client_host`` breadcrumb), and the bearer-protected
``/admin/kill`` REST endpoint is the hardened path for scripts and CI.
This deferral is intentional and documented — not an incomplete stub.
"""
from __future__ import annotations

import html
import logging
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import audit
from ..config import get_settings
from ..database import get_pool
from ..domain.ops import kill_switch
from ..integrations.clob import get_clob_breaker
from ..monitoring.health import run_health_checks

logger = logging.getLogger(__name__)

router = APIRouter()

# Captured at module import so the dashboard reports time since process boot.
_PROCESS_START_MONOTONIC: float = time.monotonic()

REFRESH_SECONDS: int = 30
AUDIT_TAIL_LIMIT: int = 10


def _uptime_seconds() -> int:
    return int(time.monotonic() - _PROCESS_START_MONOTONIC)


def _format_uptime(seconds: int) -> str:
    """Render ``seconds`` as ``Xd Yh Zm`` (or ``Yh Zm``, ``Zm Ws``)."""
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {minutes}m"


def _resolve_mode() -> str:
    """Mirror ``api.health._resolve_mode`` — paper unless every guard is open."""
    s = get_settings()
    if s.ENABLE_LIVE_TRADING and s.EXECUTION_PATH_VALIDATED and s.CAPITAL_MODE_CONFIRMED:
        return "live"
    return "paper"


def _resolve_version() -> str:
    s = get_settings()
    v = (s.APP_VERSION or "").strip()
    return v or "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def _count_users() -> int | None:
    """Return total user count, or ``None`` on DB failure."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            return int(await conn.fetchval("SELECT COUNT(*) FROM users") or 0)
    except Exception as exc:  # noqa: BLE001 — UI degrades to N/A
        logger.warning("ops dashboard: count_users failed: %s", exc)
        return None


async def _fetch_audit_tail(limit: int = AUDIT_TAIL_LIMIT) -> list[dict] | None:
    """Last ``limit`` audit rows, newest first. ``None`` on DB failure."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT ts, action, actor_role FROM audit.log "
                "ORDER BY ts DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001 — UI degrades to N/A
        logger.warning("ops dashboard: audit tail fetch failed: %s", exc)
        return None


def _circuit_state_snapshot() -> dict[str, object]:
    """Read-only snapshot of the CLOB circuit breaker.

    Returned shape: ``{"state": str, "failures": int, "threshold": int,
    "seconds_until_half_open": float}`` -- keys the dashboard renderer
    consumes directly. A failure resolving the breaker (e.g. import
    error in a degraded environment) degrades the card to N/A rather
    than 5xx-ing the whole page.
    """
    try:
        snap = get_clob_breaker().snapshot()
    except Exception as exc:  # noqa: BLE001 -- UI degrades to N/A
        logger.warning("ops dashboard: circuit snapshot failed: %s", exc)
        return {
            "state": "N/A",
            "failures": 0,
            "threshold": 0,
            "seconds_until_half_open": 0.0,
        }
    return {
        "state": str(snap.get("state", "N/A")),
        "failures": int(snap.get("failures", 0) or 0),
        "threshold": int(snap.get("threshold", 0) or 0),
        "seconds_until_half_open": float(
            snap.get("seconds_until_half_open", 0.0) or 0.0
        ),
    }


async def _kill_switch_state() -> str:
    """Return ``"ACTIVE"`` (paused) / ``"PAUSED"`` (running) / ``"N/A"``.

    The brief uses the labels ``ACTIVE`` (kill switch engaged → bot paused)
    vs ``PAUSED`` (kill switch released → bot running). We mirror that
    vocabulary in the rendered page so the operator sees identical
    wording across Telegram and the web dashboard.
    """
    try:
        active = await kill_switch.is_active()
    except Exception as exc:  # noqa: BLE001 — UI degrades to N/A
        logger.warning("ops dashboard: kill_switch.is_active failed: %s", exc)
        return "N/A"
    return "ACTIVE" if active else "PAUSED"


def _badge(state: str) -> str:
    """Render a coloured ok / fail / warn badge."""
    state = state.lower()
    if state == "ok":
        cls = "ok"
        label = "ok"
    elif state.startswith("error") or state == "fail":
        cls = "fail"
        label = "fail"
    else:
        cls = "warn"
        label = state
    return f'<span class="badge {cls}">{html.escape(label)}</span>'


def _render_audit_rows(rows: list[dict] | None) -> str:
    if rows is None:
        return '<tr><td colspan="3" class="muted">N/A — data not available</td></tr>'
    if not rows:
        return '<tr><td colspan="3" class="muted">no audit entries yet</td></tr>'
    out: list[str] = []
    for r in rows:
        ts = r.get("ts")
        ts_str = ts.isoformat(timespec="seconds") if ts is not None else "?"
        action = html.escape(str(r.get("action", "")))
        actor = html.escape(str(r.get("actor_role", "")))
        out.append(
            f'<tr><td><code>{html.escape(ts_str)}</code></td>'
            f'<td>{action}</td><td>{actor}</td></tr>'
        )
    return "\n".join(out)


def _render_health_rows(checks: dict[str, str]) -> str:
    out: list[str] = []
    for name in ("database", "telegram", "alchemy_rpc", "alchemy_ws"):
        state = checks.get(name, "N/A")
        out.append(
            f'<tr><td>{html.escape(name)}</td>'
            f'<td>{_badge(state)}</td></tr>'
        )
    return "\n".join(out)


def _render_page(
    *,
    version: str,
    mode: str,
    uptime: str,
    health: dict,
    user_count: int | None,
    kill_state: str,
    circuit: dict[str, object],
    audit_rows: list[dict] | None,
    flash: str | None = None,
    token: str | None = None,
) -> str:
    """Compose the HTML page. All variables are escape-controlled at source."""
    user_count_str = "N/A" if user_count is None else str(user_count)
    kill_class = "fail" if kill_state == "ACTIVE" else "ok" if kill_state == "PAUSED" else "warn"
    kill_label = html.escape(kill_state)
    circuit_state = str(circuit.get("state", "N/A"))
    if circuit_state == "CLOSED":
        circuit_class = "ok"
    elif circuit_state in ("OPEN", "HALF_OPEN"):
        circuit_class = "fail" if circuit_state == "OPEN" else "warn"
    else:
        circuit_class = "warn"
    circuit_label = html.escape(circuit_state)
    circuit_failures = int(circuit.get("failures", 0) or 0)
    circuit_threshold = int(circuit.get("threshold", 0) or 0)
    circuit_eta = float(circuit.get("seconds_until_half_open", 0.0) or 0.0)
    if circuit_state == "OPEN":
        circuit_detail = (
            f"{circuit_failures}/{circuit_threshold} failures "
            f"-- half-opens in {int(circuit_eta)}s"
        )
    elif circuit_state == "HALF_OPEN":
        circuit_detail = "trial allowed -- next failure re-opens"
    elif circuit_state == "CLOSED":
        circuit_detail = (
            f"{circuit_failures}/{circuit_threshold} consecutive failures"
        )
    else:
        circuit_detail = "unavailable"
    flash_html = (
        f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    )
    # The operator opens ``/ops?token=<OPS_SECRET>`` from a bookmark;
    # we forward that token into each form's action URL so the POST
    # carries it without a separate input the user has to remember.
    # Without a token in the GET, the buttons render but POST returns
    # 403 — the dashboard is open, the mutators are not.
    if token:
        from urllib.parse import quote
        token_qs = "?token=" + quote(token, safe="")
    else:
        token_qs = ""

    # The two action forms POST to /ops/kill and /ops/resume; both redirect
    # back to /ops with a flash query param so the operator sees a confirm
    # message after the round trip.
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>CrusaderBot ops</title>
<style>
  :root {{
    --bg:#0d1117; --fg:#e6edf3; --muted:#7d8590;
    --card:#161b22; --border:#30363d;
    --ok:#238636; --fail:#da3633; --warn:#9e6a03;
    --accent:#1f6feb;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; padding:1rem; background:var(--bg); color:var(--fg);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    line-height:1.4;
  }}
  h1 {{ margin:0 0 .25rem 0; font-size:1.4rem; }}
  .meta {{ color:var(--muted); font-size:.85rem; margin-bottom:1rem; }}
  .grid {{
    display:grid; gap:1rem;
    grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
    margin-bottom:1rem;
  }}
  .card {{
    background:var(--card); border:1px solid var(--border);
    border-radius:8px; padding:1rem;
  }}
  .card h2 {{ margin:0 0 .5rem 0; font-size:1rem; color:var(--muted);
              text-transform:uppercase; letter-spacing:.05em; }}
  .big {{ font-size:1.6rem; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
  td {{ padding:.35rem .25rem; border-bottom:1px solid var(--border); vertical-align:top; }}
  tr:last-child td {{ border-bottom:none; }}
  code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
          font-size:.85rem; color:var(--muted); }}
  .badge {{
    display:inline-block; padding:.1rem .5rem; border-radius:999px;
    font-size:.75rem; font-weight:600; text-transform:uppercase;
  }}
  .badge.ok   {{ background:var(--ok);   color:#fff; }}
  .badge.fail {{ background:var(--fail); color:#fff; }}
  .badge.warn {{ background:var(--warn); color:#fff; }}
  .actions {{ display:flex; gap:.5rem; flex-wrap:wrap; }}
  button {{
    flex:1; padding:.75rem 1rem; border:1px solid var(--border);
    border-radius:6px; background:var(--card); color:var(--fg);
    font-size:1rem; font-weight:600; cursor:pointer;
  }}
  button.kill   {{ background:var(--fail); border-color:var(--fail); color:#fff; }}
  button.resume {{ background:var(--ok);   border-color:var(--ok);   color:#fff; }}
  .flash {{
    margin:0 0 1rem 0; padding:.75rem 1rem;
    background:#0c2d6b; border:1px solid var(--accent);
    border-radius:6px;
  }}
  .muted {{ color:var(--muted); }}
  form {{ flex:1; margin:0; }}
</style>
</head>
<body>
<h1>CrusaderBot — ops</h1>
<div class="meta">
  Version <code>{html.escape(version)}</code>
  · Mode <code>{html.escape(mode.upper())}</code>
  · Uptime <code>{html.escape(uptime)}</code>
  · {html.escape(_now_iso())}
  · auto-refresh {REFRESH_SECONDS}s
</div>

{flash_html}

<div class="grid">
  <div class="card">
    <h2>Service</h2>
    <div>CrusaderBot</div>
    <div class="muted">FastAPI + Telegram + APScheduler</div>
  </div>
  <div class="card">
    <h2>Active users</h2>
    <div class="big">{html.escape(user_count_str)}</div>
    <div class="muted">total rows in users</div>
  </div>
  <div class="card">
    <h2>Kill switch</h2>
    <div class="big"><span class="badge {kill_class}">{kill_label}</span></div>
    <div class="muted">ACTIVE = paused, PAUSED = running</div>
  </div>
  <div class="card">
    <h2>CLOB circuit</h2>
    <div class="big"><span class="badge {circuit_class}">{circuit_label}</span></div>
    <div class="muted">{html.escape(circuit_detail)}</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Health checks</h2>
    <table>
      <tbody>
        {_render_health_rows(health.get("checks") or {})}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Controls</h2>
    <div class="actions">
      <form method="post" action="/ops/kill{token_qs}">
        <button class="kill" type="submit">Kill bot</button>
      </form>
      <form method="post" action="/ops/resume{token_qs}">
        <button class="resume" type="submit">Resume bot</button>
      </form>
    </div>
    <div class="muted" style="margin-top:.75rem;">
      Kill pauses NEW trades only. Existing positions stay open.
    </div>
  </div>
</div>

<div class="card">
  <h2>Audit log — last {AUDIT_TAIL_LIMIT}</h2>
  <table>
    <thead>
      <tr><td class="muted">ts</td><td class="muted">action</td><td class="muted">actor</td></tr>
    </thead>
    <tbody>
      {_render_audit_rows(audit_rows)}
    </tbody>
  </table>
</div>
</body>
</html>
"""


def _check_ops_token(provided: str | None) -> None:
    """Gate the POST mutators behind ``OPS_SECRET``.

    Resolution: the env-derived ``OPS_SECRET`` setting is the only
    accepted token. Unset → 503 (mutators disabled). Provided value
    missing or wrong → 403. Compared with ``secrets.compare_digest``
    to avoid timing oracles. Demo-grade — full per-operator auth is
    deferred (see module docstring TODO).
    """
    expected = (get_settings().OPS_SECRET or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="ops controls disabled (OPS_SECRET unset)",
        )
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/ops", response_class=HTMLResponse)
async def ops_dashboard(
    flash: str | None = None, token: str | None = None,
) -> HTMLResponse:
    """Render the operator HTML dashboard.

    Each I/O probe is independent: a DB outage degrades that card to N/A
    but the page still renders so the operator can see the kill switch
    state (cached) and the health badge that explains the failure.

    A ``?token=<value>`` query param is accepted but NOT validated here
    (GET is intentionally open). The value is forwarded into the
    kill / resume form action URLs so an operator who bookmarked the
    URL with the token can submit either button without re-entering
    it. The bookmark IS the auth.
    """
    try:
        health = await run_health_checks()
    except Exception as exc:  # noqa: BLE001 — UI degrades
        logger.error("ops dashboard: run_health_checks failed: %s", exc)
        health = {"checks": {}}

    user_count = await _count_users()
    kill_state = await _kill_switch_state()
    audit_rows = await _fetch_audit_tail()
    circuit = _circuit_state_snapshot()
    body = _render_page(
        version=_resolve_version(),
        mode=_resolve_mode(),
        uptime=_format_uptime(_uptime_seconds()),
        health=health,
        user_count=user_count,
        kill_state=kill_state,
        circuit=circuit,
        audit_rows=audit_rows,
        flash=flash,
        token=token,
    )
    return HTMLResponse(content=body)


@router.post("/ops/kill")
async def ops_kill(
    request: Request,
    token: str | None = None,
    x_ops_token: str | None = Header(default=None),
) -> RedirectResponse:
    """Engage the kill switch and redirect back to the dashboard.

    Auth: requires ``OPS_SECRET`` via the ``X-Ops-Token`` header
    (preferred, kept out of access logs) or the ``?token=<value>``
    query param (used by the dashboard's HTML form action URL so the
    operator can flip from a phone with a single tap on a bookmarked
    URL). ``OPS_SECRET`` unset → 503; missing / wrong token → 403.

    Delegates to the shared ``domain.ops.kill_switch.set_active`` so this
    flip writes ``kill_switch_history`` AND emits a ``kill_switch_pause``
    audit row. ``actor_id=None`` because the demo token is shared, not
    per-operator; the action label still distinguishes the ops surface
    from a Telegram flip via the ``source`` payload field.
    """
    _check_ops_token(x_ops_token or token)
    flash = "Kill switch engaged — new trades blocked."
    try:
        await kill_switch.set_active(
            action="pause",
            actor_id=None,
            reason="ops dashboard kill",
        )
        await audit.write(
            actor_role="operator",
            action="kill_switch_pause",
            payload={
                "source": "ops_dashboard_web",
                "client_host": request.client.host if request.client else None,
            },
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.error("ops dashboard: kill failed: %s", exc)
        flash = f"Kill failed: {type(exc).__name__}"
    return RedirectResponse(
        url=_redirect_url(flash, token), status_code=303,
    )


@router.post("/ops/resume")
async def ops_resume(
    request: Request,
    token: str | None = None,
    x_ops_token: str | None = Header(default=None),
) -> RedirectResponse:
    """Release the kill switch and redirect back to the dashboard.

    Auth contract identical to ``POST /ops/kill`` — see that handler's
    docstring.
    """
    _check_ops_token(x_ops_token or token)
    flash = "Kill switch released — bot resumed."
    try:
        await kill_switch.set_active(
            action="resume",
            actor_id=None,
            reason="ops dashboard resume",
        )
        await audit.write(
            actor_role="operator",
            action="kill_switch_resume",
            payload={
                "source": "ops_dashboard_web",
                "client_host": request.client.host if request.client else None,
            },
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.error("ops dashboard: resume failed: %s", exc)
        flash = f"Resume failed: {type(exc).__name__}"
    return RedirectResponse(
        url=_redirect_url(flash, token), status_code=303,
    )


def _redirect_url(flash: str, token: str | None) -> str:
    """Build the post-action redirect URL, preserving the operator's
    token query param so the next dashboard render still has it
    available for the form actions.
    """
    from urllib.parse import quote
    parts = [f"flash={quote(flash, safe='')}"]
    if token:
        parts.append(f"token={quote(token, safe='')}")
    return "/ops?" + "&".join(parts)
